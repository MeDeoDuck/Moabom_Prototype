"""coarse shadow 오케스트레이터 (설계 §8).

v1 선정 직후, 같은 후보 풀로 lang_normalize → embed → coarse_cluster →
shortlist 를 돌려 결과를 dict 로 반환한다. **사용자 반환·v1 동작은 건드리지
않는다** — 호출부(routes)가 별도 스레드에서 실행해 metrics_json 에만 기록.

모든 단계 실패는 격리: 어느 단계가 깨져도 {error} 를 단 dict 를 돌려주고
selection 본류에는 영향이 없다.
"""
from __future__ import annotations

import time

_TEXT_DESC_TRUNC = 500
_K = 5


def _jaccard(a: set[str], b: set[str]) -> float | None:
    if not a and not b:
        return None
    union = a | b
    return round(len(a & b) / len(union), 4) if union else None


def run_shadow(candidates: list[dict], v1_selected_ids: list[str]) -> dict:
    """coarse shadow 1회 실행.

    candidates: [{video_id, title, description, subscriber_count, engagement,
                  published_at, tier}, ...]
    반환 dict (metrics_json.shadow_v3 에 그대로 저장):
      {ok, n_candidates, backend, lang, cluster, shortlist[...],
       overlap_with_v1, latency_ms, error?}
    """
    t0 = time.perf_counter()
    out: dict = {"ok": False, "n_candidates": len(candidates)}
    if not candidates:
        out["error"] = "no candidates"
        out["latency_ms"] = 0
        return out

    try:
        from video_selection_agent.clustering import (
            coarse,
            embedder,
            lang_normalize,
            shortlist,
        )

        texts = [
            f"{c.get('title', '')}\n{(c.get('description', '') or '')[:_TEXT_DESC_TRUNC]}"
            for c in candidates
        ]
        normed, lang_meta = lang_normalize.normalize_texts(texts)
        out["lang"] = lang_meta

        vectors, embed_meta = embedder.embed_texts(normed)
        out["backend"] = embed_meta.get("backend")
        out["embed"] = embed_meta

        labels, cluster_meta = coarse.kmeans_labels(vectors, k=_K)
        out["cluster"] = cluster_meta

        sl, sl_meta = shortlist.build_shortlist(candidates, labels)
        out["shortlist"] = sl
        out["shortlist_meta"] = sl_meta

        sl_ids = {s["video_id"] for s in sl}
        v1_ids = set(v1_selected_ids or [])
        out["overlap_with_v1"] = {
            "jaccard": _jaccard(sl_ids, v1_ids),
            "v1_in_shortlist": len(sl_ids & v1_ids),
            "v1_total": len(v1_ids),
        }
        out["ok"] = True
    except Exception as e:  # 전체 격리
        out["error"] = f"shadow failed: {type(e).__name__}: {e}"
        print(f"[shadow] {out['error']}", flush=True)

    out["latency_ms"] = int((time.perf_counter() - t0) * 1000)
    return out
