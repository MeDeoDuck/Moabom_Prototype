"""Node 5: Azure GPT-4.1-mini로 topical_fit 점수 + 짧은 rationale 부여.

LLM 호출 1회 (배치). 실패 시 `llm_topical_fit=0.0` 유지하고 계속 진행.
"""
from __future__ import annotations

import json
import logging

from video_selection_agent.core.models import RerankResult
from video_selection_agent.graph.state import SelectionState
from video_selection_agent.llm.azure_openai_client import AzureOpenAIClient, LLMError
from video_selection_agent.llm.rationale_prompts import (
    RERANK_JSON_SCHEMA,
    RERANK_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)


def _build_user_message(state: SelectionState, eligible_ids: list[str]) -> str:
    product = state["product"]
    candidates = {c.video_id: c for c in state.get("candidates", [])}
    scores = state.get("scores", {})
    items = []
    for vid in eligible_ids:
        c = candidates.get(vid)
        if c is None:
            continue
        sb = scores.get(vid)
        items.append({
            "video_id": vid,
            "title": c.title,
            "channel_name": c.channel_name,
            "duration_min": round(c.duration_seconds / 60.0, 1),
            "tier": sb.tier if sb else "mid",
            "description_snippet": (c.description or "")[:240],
        })
    payload = {
        "product": {
            "name": product.name,
            "brand": product.brand,
            "category": product.category,
        },
        "candidates": items,
    }
    return (
        "다음 제품과 후보 영상들에 대해 topical_fit(0-1)과 rationale_short를 매겨주세요.\n"
        "각 후보에 대해 반드시 하나의 결과를 반환하세요.\n\n"
        + json.dumps(payload, ensure_ascii=False)
    )


def llm_rerank(state: SelectionState) -> SelectionState:
    """살아남은 후보들을 LLM에 배치로 전달 → topical_fit + rationale_short."""
    trace = list(state.get("trace", []))
    scores = dict(state.get("scores", {}))
    weights = state["policy"].weights.as_dict()

    eligible_ids = [vid for vid, sb in scores.items() if sb.rank > 0]
    if not eligible_ids:
        trace.append("llm_rerank: no eligible candidates — skip")
        return {**state, "llm_reranked": [], "trace": trace}

    client = AzureOpenAIClient()
    user_msg = _build_user_message(state, eligible_ids)

    try:
        response = client.chat_structured(
            system=RERANK_SYSTEM_PROMPT,
            user=user_msg,
            json_schema=RERANK_JSON_SCHEMA,
            max_tokens=2000,
            temperature=0.2,
        )
    except LLMError as e:
        logger.warning("llm_rerank LLM failure, degrading gracefully: %s", e)
        trace.append(f"llm_rerank: LLM failed ({type(e).__name__}) — degraded")
        return {**state, "llm_reranked": [], "trace": trace}

    reranked: list[RerankResult] = []
    updated = 0
    for item in response.get("results", []):
        vid = item.get("video_id")
        if not vid or vid not in scores:
            continue
        fit = max(0.0, min(1.0, float(item.get("topical_fit", 0.0))))
        rationale = (item.get("rationale_short") or "")[:200]
        reranked.append(RerankResult(video_id=vid, topical_fit=fit, rationale_short=rationale))

        sb = scores[vid]
        dims = dict(sb.dimensions)
        dims["llm_topical_fit"] = fit
        contributions = {k: dims[k] * weights[k] for k in dims}
        sb.dimensions = dims
        sb.weighted_contributions = contributions
        sb.final_score = sum(contributions.values())
        sb.llm_rationale_short = rationale
        updated += 1

    trace.append(
        f"llm_rerank: LLM scored {updated}/{len(eligible_ids)} candidates"
    )
    return {**state, "llm_reranked": reranked, "scores": scores, "trace": trace}
