"""v3 coarse 클러스터링 단위 테스트 (PR2).

LLM·임베딩·GPU 경계는 stub. KMeans 만 sklearn 사용(--with scikit-learn).
"""
from __future__ import annotations

import pytest

from video_selection_agent.clustering import (
    coarse,
    embedder,
    lang_normalize,
    shadow,
    shortlist,
)


# ---------- lang_normalize.is_english ----------

def test_is_english():
    assert lang_normalize.is_english("iPhone 17 Pro Max Review After 3 Months") is True
    assert lang_normalize.is_english("아이폰 17 프로 리뷰 3개월 사용기") is False
    assert lang_normalize.is_english("아이폰17 iPhone Pro 장단점") is False  # 혼용=한국어
    assert lang_normalize.is_english("") is False


def test_lang_normalize_translates_english_only(monkeypatch):
    def fake_structured(self, system, user, json_schema, **kw):
        # 영문 항목(index 1)만 payload 에 들어옴 → 그 id 로 번역 반환
        import json as _j
        items = _j.loads(user)
        return {"items": [{"id": it["id"], "ko": "번역됨"} for it in items]}

    monkeypatch.setattr(
        "video_selection_agent.llm.azure_openai_client.AzureOpenAIClient.chat_structured",
        fake_structured,
    )
    texts = ["아이폰 리뷰", "iPhone Review After Months", "갤럭시 후기"]
    out, meta = lang_normalize.normalize_texts(texts)
    assert out[0] == "아이폰 리뷰"  # 한국어 그대로
    assert out[2] == "갤럭시 후기"
    assert out[1] == "번역됨"  # 영문만 번역
    assert meta["n_english"] == 1 and meta["translated"] is True


def test_lang_normalize_no_english_skips_llm(monkeypatch):
    # 영문 0개면 LLM 안 부름 — chat_structured 호출되면 실패하도록
    def boom(self, *a, **k):
        raise AssertionError("LLM should not be called when no English")

    monkeypatch.setattr(
        "video_selection_agent.llm.azure_openai_client.AzureOpenAIClient.chat_structured",
        boom,
    )
    out, meta = lang_normalize.normalize_texts(["아이폰 리뷰", "갤럭시 후기"])
    assert out == ["아이폰 리뷰", "갤럭시 후기"]
    assert meta["n_english"] == 0 and meta["translated"] is False


# ---------- coarse.kmeans_labels (sklearn) ----------

def test_kmeans_deterministic_and_k_reduction():
    pytest.importorskip("sklearn")
    vecs = [[0.0, 0.0], [0.1, 0.0], [9.0, 9.0], [9.1, 9.0]]
    labels1, meta1 = coarse.kmeans_labels(vecs, k=2)
    labels2, _ = coarse.kmeans_labels(vecs, k=2)
    assert labels1 == labels2  # seed 고정 → 결정적
    assert meta1["k_effective"] == 2
    # 가까운 두 점은 같은 군집
    assert labels1[0] == labels1[1]
    assert labels1[2] == labels1[3]
    assert labels1[0] != labels1[2]
    # n<k → k 축소
    _, meta3 = coarse.kmeans_labels(vecs[:1], k=5)
    assert meta3["k_effective"] == 1


# ---------- shortlist ----------

_CANDS = [
    {"video_id": "a", "title": "ta", "tier": "mega"},
    {"video_id": "b", "title": "tb", "tier": "small"},
    {"video_id": "c", "title": "tc", "tier": "mid"},
]


def test_shortlist_filters_hallucinated_ids(monkeypatch):
    def fake_structured(self, system, user, json_schema, **kw):
        return {
            "clusters": [
                {"cluster_id": 0, "label": "세대비교", "picks": [
                    {"video_id": "a", "reason": "r1"},
                    {"video_id": "ZZZ", "reason": "환각"},  # 입력에 없는 id
                ]},
                {"cluster_id": 1, "label": "내구성", "picks": [
                    {"video_id": "b", "reason": "r2"},
                ]},
            ]
        }

    monkeypatch.setattr(
        "video_selection_agent.llm.azure_openai_client.AzureOpenAIClient.chat_structured",
        fake_structured,
    )
    labels = [0, 1, 0]
    sl, meta = shortlist.build_shortlist(_CANDS, labels)
    ids = {s["video_id"] for s in sl}
    assert ids == {"a", "b"}  # ZZZ 환각 차단
    assert meta["shortlist_size"] == 2


def test_shortlist_llm_failure_returns_empty(monkeypatch):
    def boom(self, *a, **k):
        raise RuntimeError("llm down")

    monkeypatch.setattr(
        "video_selection_agent.llm.azure_openai_client.AzureOpenAIClient.chat_structured",
        boom,
    )
    sl, meta = shortlist.build_shortlist(_CANDS, [0, 1, 2])
    assert sl == [] and "error" in meta


# ---------- embedder fallback ----------

def test_embedder_uses_worker_when_available(monkeypatch):
    monkeypatch.setattr(
        embedder, "_embed_via_worker",
        lambda texts: ([[1.0]] * len(texts), {"backend": "qwen3_worker", "dim": 1}),
    )
    vecs, meta = embedder.embed_texts(["x", "y"])
    assert meta["backend"] == "qwen3_worker" and len(vecs) == 2


def test_embedder_falls_back_to_runyourai(monkeypatch):
    monkeypatch.setattr(embedder, "_embed_via_worker", lambda texts: None)
    monkeypatch.setattr(
        embedder, "_embed_via_runyourai",
        lambda texts: ([[0.5]] * len(texts), {"backend": "runyourai_3large", "dim": 1}),
    )
    vecs, meta = embedder.embed_texts(["x"])
    assert meta["backend"] == "runyourai_3large"


def test_embedder_empty():
    vecs, meta = embedder.embed_texts([])
    assert vecs == [] and meta["backend"] == "none"


# ---------- shadow orchestrator ----------

def _patch_shadow_steps(monkeypatch, *, embed_backend="qwen3_worker", raise_embed=False):
    monkeypatch.setattr(
        lang_normalize, "normalize_texts",
        lambda texts: (list(texts), {"n_total": len(texts), "n_english": 0, "translated": False}),
    )
    if raise_embed:
        def _boom(texts):
            raise RuntimeError("embed dead")
        monkeypatch.setattr(embedder, "embed_texts", _boom)
    else:
        monkeypatch.setattr(
            embedder, "embed_texts",
            lambda texts: ([[float(i)] for i in range(len(texts))], {"backend": embed_backend, "dim": 1}),
        )
    monkeypatch.setattr(
        coarse, "kmeans_labels",
        lambda vecs, k=5: ([i % 2 for i in range(len(vecs))], {"k_effective": 2, "cluster_sizes": {}}),
    )
    monkeypatch.setattr(
        shortlist, "build_shortlist",
        lambda cands, labels: (
            [{"video_id": cands[0]["video_id"], "cluster_id": 0, "cluster_label": "L", "reason": "r"}],
            {"shortlist_size": 1},
        ),
    )


def test_shadow_assembles_and_overlap(monkeypatch):
    _patch_shadow_steps(monkeypatch)
    cands = [{"video_id": "a", "title": "ta"}, {"video_id": "b", "title": "tb"}]
    out = shadow.run_shadow(cands, v1_selected_ids=["a", "z"])
    assert out["ok"] is True
    assert out["backend"] == "qwen3_worker"
    assert out["n_candidates"] == 2
    # shortlist {a} vs v1 {a,z} → jaccard 1/2
    assert out["overlap_with_v1"]["jaccard"] == pytest.approx(0.5, abs=1e-3)
    assert out["overlap_with_v1"]["v1_in_shortlist"] == 1
    assert "latency_ms" in out


def test_shadow_error_isolation(monkeypatch):
    _patch_shadow_steps(monkeypatch, raise_embed=True)
    out = shadow.run_shadow([{"video_id": "a", "title": "t"}], v1_selected_ids=["a"])
    assert out["ok"] is False and "error" in out  # 예외 안 던지고 격리


def test_shadow_empty_candidates():
    out = shadow.run_shadow([], v1_selected_ids=[])
    assert out["ok"] is False and out["error"] == "no candidates"
