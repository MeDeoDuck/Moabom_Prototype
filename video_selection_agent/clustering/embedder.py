"""임베딩 provider 추상화 (설계 §5·§10).

1순위: 데스크탑 Qwen3-Embedding-4B 워커(`/embed`, HTTP). 품질 정답(PoC).
2순위(fallback): RunYourAI 게이트웨이 text-embedding-3-large. 워커 부재/실패 시.

호출부(coarse_cluster)는 backend 를 모르고 `embed_texts()` 만 쓴다. 어느 backend
가 쓰였는지는 meta["backend"] 로 노출 — shadow 지표에서 품질 해석에 필요.

env:
  - EMBED_WORKER_URL / EMBED_WORKER_TOKEN  → Qwen3 워커(미설정 시 fallback 직행)
  - EMBED_FALLBACK_MODEL (default "openai/text-embedding-3-large")
  - EMBED_WORKER_TIMEOUT (default 90초 — 첫 호출 cold-load 대비)
"""
from __future__ import annotations

import os
import time
from typing import Optional

import requests

_DEFAULT_FALLBACK_MODEL = "openai/text-embedding-3-large"
_RUNYOURAI_BATCH = 64


class EmbeddingError(RuntimeError):
    """모든 backend 가 실패했을 때."""


def _worker_credentials() -> tuple[Optional[str], Optional[str]]:
    """워커 base_url + token 을 우선순위대로 해석.

    임베딩/scope/transcript 는 전부 동일한 데스크탑 워커(8080)다. 전용
    EMBED_WORKER_* → scope 용 SCOPE_WORKER_* → 자막용 YOUTUBE_FETCH_WORKER_*
    순으로 폴백한다. 운영(Azure)은 워커 주소를 YOUTUBE_FETCH_WORKER_URL/TOKEN
    로만 들고 있으므로(자막 경로), 이 폴백이 있어야 Azure 에서도 추가 설정 없이
    Qwen3 워커에 닿는다. 셋 다 없으면 (None, None) → 호출부가 3-large 폴백.
    """
    base_url = (
        os.environ.get("EMBED_WORKER_URL")
        or os.environ.get("SCOPE_WORKER_URL")
        or os.environ.get("YOUTUBE_FETCH_WORKER_URL")
    )
    token = (
        os.environ.get("EMBED_WORKER_TOKEN")
        or os.environ.get("SCOPE_WORKER_TOKEN")
        or os.environ.get("YOUTUBE_FETCH_WORKER_TOKEN")
    )
    return base_url, token


def _embed_via_worker(texts: list[str]) -> Optional[tuple[list[list[float]], dict]]:
    """Qwen3 워커 /embed. 미설정/실패 시 None (호출부가 fallback)."""
    base_url, token = _worker_credentials()
    if not base_url or not token:
        return None

    url = base_url.rstrip("/") + "/embed"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        timeout = float(os.environ.get("EMBED_WORKER_TIMEOUT", "90"))
    except ValueError:
        timeout = 90.0

    t0 = time.perf_counter()
    for attempt in range(3):
        try:
            resp = requests.post(
                url, json={"texts": texts}, headers=headers, timeout=timeout
            )
            if resp.status_code == 200:
                data = resp.json()
                vectors = data.get("vectors", [])
                if len(vectors) != len(texts):
                    print(
                        f"[EMBED] worker count mismatch {len(vectors)}!={len(texts)}",
                        flush=True,
                    )
                    return None
                meta = {
                    "backend": "qwen3_worker",
                    "model_version": data.get("model_version"),
                    "dim": data.get("dim"),
                    "embed_ms": int((time.perf_counter() - t0) * 1000),
                }
                return vectors, meta
            if 500 <= resp.status_code < 600:
                print(f"[EMBED] worker 5xx ({resp.status_code}), retry {attempt+1}/3", flush=True)
                time.sleep(2 ** attempt)
                continue
            print(f"[EMBED] worker {resp.status_code}: {resp.text[:200]}", flush=True)
            return None
        except requests.RequestException as e:
            print(f"[EMBED] worker request failed (attempt {attempt+1}/3): {e}", flush=True)
            time.sleep(2 ** attempt)
    return None


def _embed_via_runyourai(texts: list[str]) -> tuple[list[list[float]], dict]:
    """RunYourAI 게이트웨이 임베딩(3-large). 실패 시 EmbeddingError."""
    model = os.environ.get("EMBED_FALLBACK_MODEL", _DEFAULT_FALLBACK_MODEL)
    try:
        from scripts.reports.transcript_report import get_report_llm_client

        client = get_report_llm_client()
    except Exception as e:  # config/import 실패
        raise EmbeddingError(f"runyourai client init failed: {e}") from e

    vectors: list[list[float]] = []
    t0 = time.perf_counter()
    try:
        for i in range(0, len(texts), _RUNYOURAI_BATCH):
            batch = texts[i : i + _RUNYOURAI_BATCH]
            resp = client.embeddings.create(model=model, input=batch)
            for d in resp.data:  # SDK 가 input 순서 보장
                vectors.append(list(d.embedding))
    except Exception as e:
        raise EmbeddingError(f"runyourai embeddings failed: {e}") from e

    if len(vectors) != len(texts):
        raise EmbeddingError(
            f"runyourai count mismatch {len(vectors)}!={len(texts)}"
        )
    meta = {
        "backend": "runyourai_3large",
        "model_version": model,
        "dim": len(vectors[0]) if vectors else 0,
        "embed_ms": int((time.perf_counter() - t0) * 1000),
    }
    return vectors, meta


def embed_texts(texts: list[str]) -> tuple[list[list[float]], dict]:
    """텍스트 → (벡터, meta). Qwen3 워커 우선, 실패 시 3-large fallback.

    둘 다 실패하면 EmbeddingError. 빈 입력은 ([], {backend:"none"}).
    """
    if not texts:
        return [], {"backend": "none", "dim": 0, "embed_ms": 0}

    worker = _embed_via_worker(texts)
    if worker is not None:
        return worker
    return _embed_via_runyourai(texts)
