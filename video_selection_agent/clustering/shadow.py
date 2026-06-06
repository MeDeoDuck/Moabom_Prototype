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


def run_shadow(
    candidates: list[dict],
    v1_selected_ids: list[str],
    do_fine: bool = False,
) -> dict:
    """coarse(+옵션 fine) shadow 1회 실행.

    candidates: [{video_id, title, description, subscriber_count, engagement,
                  published_at, tier, channel_id, scope_label}, ...]
    do_fine: True 면 shortlist 자막 fetch + llm_final_select + verifier 까지(PR3).
      자막 fetch 차단 위험 때문에 호출부가 별도 플래그로 좁게 게이트.
    반환 dict (metrics_json.shadow_v3 에 그대로 저장):
      {ok, n_candidates, backend, lang, cluster, shortlist[...],
       overlap_with_v1, final_select?, fine?, latency_ms, error?}
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

        # fine 은 best-effort: 실패해도 coarse 결과(shortlist 등)는 보존.
        if do_fine and sl:
            try:
                out["final_select"] = _run_fine(sl, candidates)
            except Exception as e:
                out["final_select"] = {"error": f"fine failed: {type(e).__name__}: {e}"}
                print(f"[shadow] fine failed (coarse preserved): {e}", flush=True)

        out["ok"] = True
    except Exception as e:  # 전체 격리
        out["error"] = f"shadow failed: {type(e).__name__}: {e}"
        print(f"[shadow] {out['error']}", flush=True)

    out["latency_ms"] = int((time.perf_counter() - t0) * 1000)
    return out


def _run_fine(shortlist_items: list[dict], candidates: list[dict]) -> dict:
    """PR3 fine: shortlist 자막 fetch → llm_final_select → verifier 조합 선택.

    shortlist 와 원본 candidates(tier/scope_label/channel_id 보유)를 video_id 로
    join. 실패는 격리해 {error} 반환(coarse 결과엔 영향 없음).
    """
    from video_selection_agent.clustering import fine, final_select

    by_id = {c["video_id"]: c for c in candidates}
    sl_ids = [s["video_id"] for s in shortlist_items]

    transcripts, tx_meta = fine.fetch_shortlist_transcripts(sl_ids)
    judgments, judge_meta = final_select.llm_final_select(
        [by_id[v] for v in sl_ids if v in by_id], transcripts
    )

    # verifier 입력: shortlist 메타 + LLM 판단 + tier/scope/channel join
    verify_in: list[dict] = []
    for s in shortlist_items:
        vid = s["video_id"]
        c = by_id.get(vid, {})
        j = judgments.get(vid, {})
        verify_in.append(
            {
                "video_id": vid,
                "cluster_id": s.get("cluster_id"),
                "tier": c.get("tier", ""),
                "channel_id": c.get("channel_id", ""),
                "scope_label": c.get("scope_label", 0),
                "fit": j.get("fit", 0.0),
                "depth": j.get("depth", 0.0),
                "risk": j.get("risk", 0.0),
                "reason": j.get("reason", s.get("reason", "")),
            }
        )

    result = final_select.verify_and_select(verify_in)
    result["transcript_fetch"] = tx_meta
    result["judge_meta"] = judge_meta
    # 선택된 영상의 전체 자막을 첨부 — 저장(videos 적재) 후 routes 가 video_transcripts
    # 로 캐시해 보고서가 재fetch 없이 재사용한다(이중 fetch/429 제거). metrics_json 에는
    # 안 들어가게 routes 가 pop 으로 분리.
    result["_selected_transcripts"] = {
        vid: transcripts[vid] for vid in result.get("selected", []) if vid in transcripts
    }
    return result
