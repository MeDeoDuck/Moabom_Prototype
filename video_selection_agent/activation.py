"""v3_cluster 활성화 (PR4) — v1 위의 재선택기.

v1 그래프가 만든 후보(enrich/score/scope 완료) 를 그대로 재사용해 coarse+fine 을
동기 실행하고, verifier 가 낸 깔끔한 선택으로 v1 결과를 교체한다. 실패/fallback 이면
v1 을 그대로 둔다(안전 복귀). FastAPI 의존 없이 단위 테스트 가능하도록 routes 와 분리.
"""
from __future__ import annotations

from video_selection_agent.core.models import SelectedVideo, SelectionDecision

_K_MIN = 3  # SelectionPolicyConfig.k_min


def shadow_candidates(decision: SelectionDecision) -> list[dict]:
    """decision 의 후보+점수에서 v3(coarse/fine) 입력 dict 생성.

    tier 는 v1 score, scope_label 은 scope_filter 가 extras 에 남긴 값.
    """
    tier_by_id = {vid: sb.tier for vid, sb in decision.all_scores.items()}
    scope_by_id = {
        vid: (sb.extras or {}).get("scope_label", 0)
        for vid, sb in decision.all_scores.items()
    }
    return [
        {
            "video_id": c.video_id,
            "title": c.title,
            "description": c.description,
            "subscriber_count": c.channel_subscriber_count,
            "engagement": (c.like_count or 0) + (c.comment_count or 0),
            "published_at": c.published_at.isoformat() if c.published_at else "",
            "tier": tier_by_id.get(c.video_id, ""),
            "channel_id": c.channel_id,
            "scope_label": scope_by_id.get(c.video_id, 0),
        }
        for c in decision.candidates_preview
    ]


def run_v3_sync(decision: SelectionDecision) -> dict:
    """coarse+fine 동기 실행 → shadow dict. 실패는 run_shadow 내부에서 격리."""
    from video_selection_agent.clustering.shadow import run_shadow

    cands = shadow_candidates(decision)
    v1_ids = [v.video_id for v in decision.selected]
    return run_shadow(cands, v1_ids, do_fine=True)


def apply_v3_selection(decision: SelectionDecision, shadow: dict) -> bool:
    """v3 final_select 로 decision.selected 교체. 성공 시 True.

    검증: shadow ok · final_select 존재 · verifier fallback 아님 · 선정 수 ≥ k_min.
    하나라도 어긋나면 decision 을 안 건드리고 False (v1 유지).
    """
    if not shadow or not shadow.get("ok"):
        return False
    fs = shadow.get("final_select") or {}
    if fs.get("error") or fs.get("fallback"):
        return False
    detail = fs.get("detail") or []
    if len(detail) < _K_MIN:
        return False

    cand_by_id = {c.video_id: c for c in decision.candidates_preview}
    new_selected: list[SelectedVideo] = []
    for idx, d in enumerate(detail, start=1):
        vid = d["video_id"]
        c = cand_by_id.get(vid)
        sb = decision.all_scores.get(vid)
        if c is None or sb is None:
            return False  # 데이터 불일치 → 안전하게 v1 유지
        reason = d.get("reason", "")
        # 저장 경로(all_scores)가 반영하도록 score 객체의 rationale/rank 갱신
        sb.rank = idx
        sb.llm_rationale_short = reason[:200]
        sb.llm_rationale_full = reason
        cluster_id = d.get("cluster_id")
        new_selected.append(
            SelectedVideo(
                video_id=vid,
                title=c.title,
                channel_name=c.channel_name,
                tier=sb.tier,
                rank=idx,
                final_score=sb.final_score,
                dimensions=sb.dimensions,
                weighted_contributions=sb.weighted_contributions,
                rationale_short=reason[:200],
                rationale_full=reason,
                selection_reasons=[f"cluster {cluster_id}" if cluster_id is not None else "v3"],
            )
        )
    decision.selected = new_selected
    decision.trace.append(
        f"v3_cluster: replaced selection with {len(new_selected)} fine-selected videos"
    )
    return True
