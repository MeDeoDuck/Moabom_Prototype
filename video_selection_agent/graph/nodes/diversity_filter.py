"""Node 4: 채널 상한·티어 쿼터로 다양성 강제.

이 노드는 후보를 **제거**하지 않고 **랭킹 기반으로 허용 여부**만 마킹하여
finalize_selection이 top-k를 안전하게 뽑을 수 있게 한다.
(후보 자체를 줄이면 relax 루프가 복잡해지므로 state를 보존.)
"""
from __future__ import annotations

from collections import Counter

from video_selection_agent.core.models import DiversityReport, ScoreBreakdown
from video_selection_agent.graph.state import SelectionState


def _sorted_score_items(scores: dict[str, ScoreBreakdown]) -> list[ScoreBreakdown]:
    return sorted(scores.values(), key=lambda s: s.final_score, reverse=True)


def diversity_filter(state: SelectionState) -> SelectionState:
    scores = state.get("scores", {})
    policy = state["policy"]
    if not scores:
        trace = list(state.get("trace", []))
        trace.append("diversity_filter: no scores — skip")
        return {
            **state,
            "diversity_report": DiversityReport(0, {}, 0),
            "trace": trace,
        }

    candidates = {c.video_id: c for c in state.get("candidates", [])}
    sorted_scores = _sorted_score_items(scores)

    channel_counter: Counter[str] = Counter()
    tier_counter: Counter[str] = Counter()
    survivors: list[str] = []
    budget = policy.k_max  # top-k 여유분

    for sb in sorted_scores:
        if len(survivors) >= budget * 3:
            break
        c = candidates.get(sb.video_id)
        if c is None:
            continue
        if channel_counter[c.channel_id] >= policy.max_per_channel:
            continue
        survivors.append(sb.video_id)
        channel_counter[c.channel_id] += 1
        tier_counter[sb.tier] += 1

    # 생존자에 rank 부여 (finalize에서 top-k를 고를 때 사용)
    for idx, vid in enumerate(survivors, start=1):
        scores[vid].rank = idx

    # 생존하지 못한 후보는 rank=0으로 남겨 finalize에서 제외
    for vid, sb in scores.items():
        if vid not in set(survivors):
            sb.rank = 0

    report = DiversityReport(
        channels_unique=len([c for c, n in channel_counter.items() if n > 0]),
        tier_distribution=dict(tier_counter),
        max_channel_occurrence=max(channel_counter.values()) if channel_counter else 0,
    )

    violated: list[str] = []
    if report.max_channel_occurrence > policy.max_per_channel:
        violated.append("max_per_channel")
    total = sum(tier_counter.values())
    if total:
        mega_ratio = tier_counter.get("mega", 0) / total
        if mega_ratio > policy.mega_tier_ratio_cap:
            violated.append("mega_tier_ratio_cap")
    report.violated_constraints = violated

    trace = list(state.get("trace", []))
    trace.append(
        f"diversity_filter: {len(survivors)} survivors, "
        f"unique_channels={report.channels_unique}, tiers={report.tier_distribution}"
    )
    return {**state, "scores": scores, "diversity_report": report, "trace": trace}
