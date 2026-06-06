"""Qwen3-Embedding-4B inference on the worker (GPU).

v3 영상선정 coarse_cluster(설계 §6)용 임베딩. scope_logic 과 동일 패턴 —
첫 호출에 모델 1회 lazy-load(bf16/cuda) 후 배치 임베딩 서빙.

모델은 HF 캐시에 이미 받아져 있음(`Qwen/Qwen3-Embedding-4B`, dim 2560,
bf16 native). sentence-transformers 가 Qwen3 의 last-token pooling +
normalize 를 모델 설정대로 처리하므로 풀링을 직접 구현하지 않는다.

env:
  - EMBED_MODEL_ID   (default "Qwen/Qwen3-Embedding-4B") — HF id 또는 로컬 경로
  - EMBED_BATCH_SIZE (default 16)
"""
from __future__ import annotations

import os
import time
from threading import Lock
from typing import Iterable

# 무거운 deps 는 _ensure_loaded 안에서만 import — import-time 경량 유지 +
# 유닛 테스트가 torch 없이 stub 가능.
_MODEL_LOCK = Lock()
_MODEL_STATE: dict = {}

MODEL_VERSION = "qwen3-embedding-4b-v1"
DEFAULT_MODEL_ID = "Qwen/Qwen3-Embedding-4B"
DEFAULT_BATCH_SIZE = 16
EMBED_DIM = 2560


def _ensure_loaded() -> None:
    if _MODEL_STATE.get("ready"):
        return
    with _MODEL_LOCK:
        if _MODEL_STATE.get("ready"):
            return
        import torch  # type: ignore
        from sentence_transformers import SentenceTransformer  # type: ignore

        model_id = os.environ.get("EMBED_MODEL_ID", DEFAULT_MODEL_ID)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        # bf16 native — fp16 강제 downcast 시 overflow/NaN 위험(설계 §6 정정).
        dtype = torch.bfloat16 if device == "cuda" else torch.float32

        model = SentenceTransformer(
            model_id,
            device=device,
            model_kwargs={"torch_dtype": dtype},
        )

        _MODEL_STATE.update(model=model, device=device, ready=True)
        print(
            f"[EMBED] Loaded {MODEL_VERSION} ({model_id}) on {device} (dtype={dtype})",
            flush=True,
        )


def embed_texts(texts: Iterable[str]) -> tuple[list[list[float]], int]:
    """텍스트 배치 → (L2-normalized 임베딩 리스트, 전체 latency_ms).

    반환 벡터는 입력 순서 보장. 빈 입력은 ([], 0).
    """
    texts_list = [t if isinstance(t, str) else str(t) for t in texts]
    if not texts_list:
        return [], 0

    _ensure_loaded()
    model = _MODEL_STATE["model"]
    batch_size = int(os.environ.get("EMBED_BATCH_SIZE", DEFAULT_BATCH_SIZE))

    t0 = time.perf_counter()
    vectors = model.encode(
        texts_list,
        batch_size=batch_size,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return [v.tolist() for v in vectors], elapsed_ms
