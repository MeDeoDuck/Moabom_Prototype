"""Node 6: 최종 k개 선정 (k_min ≤ k ≤ k_max).

다양성 통과(rank > 0) 후보 중 final_score 상위 k개를 선택.
Auto 모드: top-k 자동. Custom 모드: state['selected_video_ids'] 존중.
"""
from __future__ import annotations

from video_selection_agent.core.models import SelectedVideo
from video_selection_agent.graph.state import SelectionState


def _build_selection_reasons(
    dims: dict[str, float],
    tier: str,
) -> list[str]:
    """점수 차원을 사람이 읽을 수 있는 문구 1~3개로 요약."""
    reasons: list[str] = []
    # 가장 기여도 큰 2개 차원 라벨링
    ranked = sorted(dims.items(), key=lambda kv: kv[1], reverse=True)
    label = {
        "relevance": "높은 관련도",
        "engagement": "높은 시청자 참여도",
        "recency": "최신 리뷰",
        "channel_anti_bias": "중소 채널 관점",
        "duration_fit": "심층 리뷰 길이",
        "llm_topical_fit": "리뷰 적합성",
    }
    for key, val in ranked[:2]:
        if val >= 0.5:
            reasons.append(label.get(key, key))
    if tier in {"small", "micro"} and "중소 채널 관점" not in reasons:
        reasons.append("중소 채널 관점")
    return reasons or ["종합 점수 상위"]


def finalize_selection(state: SelectionState) -> SelectionState:
    scores = state.get("scores", {})
    candidates = {c.video_id: c for c in state.get("candidates", [])}
    policy = state["policy"]
    k = policy.clamp_k(state.get("k_requested", policy.k_min))
    mode = state.get("mode", "auto")
    requested_ids = state.get("selected_video_ids") or []

    eligible = [s for s in scores.values() if s.rank > 0]
    eligible.sort(key=lambda s: s.final_score, reverse=True)

    trace = list(state.get("trace", []))

    if mode == "custom" and requested_ids:
        id_set = set(requested_ids)
        picked = [s for s in eligible if s.video_id in id_set]
        # 요청된 순서로 재정렬
        picked.sort(key=lambda s: requested_ids.index(s.video_id))
        picked = picked[: policy.k_max]
        trace.append(f"finalize_selection[custom]: {len(picked)} requested")
    else:
        picked = eligible[:k]
        trace.append(f"finalize_selection[auto]: top-{len(picked)} / k={k}")

    final: list[SelectedVideo] = []
    for idx, sb in enumerate(picked, start=1):
        c = candidates.get(sb.video_id)
        if c is None:
            continue
        sb.rank = idx
        sb.selection_reasons = _build_selection_reasons(sb.dimensions, sb.tier)
        final.append(
            SelectedVideo(
                video_id=sb.video_id,
                title=c.title,
                channel_name=c.channel_name,
                tier=sb.tier,
                rank=idx,
                final_score=sb.final_score,
                dimensions=sb.dimensions,
                weighted_contributions=sb.weighted_contributions,
                rationale_short=sb.llm_rationale_short,
                rationale_full=sb.llm_rationale_full,
                selection_reasons=sb.selection_reasons,
            )
        )

    return {**state, "final_selection": final, "scores": scores, "trace": trace}
