"""Node 3: 6개 차원 정량 스코어링 (LLM 미사용).

`llm_topical_fit`은 llm_rerank 단계에서 병합되므로 여기서는 0.0으로 초기화.
"""
from __future__ import annotations

from video_selection_agent.core.models import ScoreBreakdown
from video_selection_agent.graph.state import SelectionState
from video_selection_agent.scoring.channel_bias import (
    channel_anti_bias_score,
    classify_channel_tier,
)
from video_selection_agent.scoring.duration import duration_fit_score
from video_selection_agent.scoring.engagement import engagement_scores
from video_selection_agent.scoring.recency import recency_score
from video_selection_agent.scoring.relevance import relevance_score


def score_quantitative(state: SelectionState) -> SelectionState:
    candidates = state.get("candidates", [])
    if not candidates:
        trace = list(state.get("trace", []))
        trace.append("score_quantitative: no candidates — skip")
        return {**state, "scores": {}, "trace": trace}

    product = state["product"]
    weights = state["policy"].weights
    engagement_map = engagement_scores(candidates)

    scores: dict[str, ScoreBreakdown] = {}
    for c in candidates:
        dims = {
            "relevance": relevance_score(c, product),
            "engagement": engagement_map.get(c.video_id, 0.0),
            "recency": recency_score(c),
            "channel_anti_bias": channel_anti_bias_score(c),
            "duration_fit": duration_fit_score(c),
            "llm_topical_fit": 0.0,  # llm_rerank 단계에서 채움
        }
        w = weights.as_dict()
        contributions = {k: dims[k] * w[k] for k in dims}
        final = sum(contributions.values())

        scores[c.video_id] = ScoreBreakdown(
            video_id=c.video_id,
            final_score=final,
            dimensions=dims,
            weighted_contributions=contributions,
            tier=classify_channel_tier(c.channel_subscriber_count),
        )

    trace = list(state.get("trace", []))
    trace.append(f"score_quantitative: scored {len(scores)} candidates")
    return {**state, "scores": scores, "trace": trace}
