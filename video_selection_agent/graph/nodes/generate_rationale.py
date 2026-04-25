"""Node 7: 최종 k개에 대해 2~3문장 rationale_full 생성.

LLM 호출 1회 (배치). 실패 시 selection_reasons 기반 기본 문구로 대체.
"""
from __future__ import annotations

import json
import logging

from video_selection_agent.graph.state import SelectionState
from video_selection_agent.llm.azure_openai_client import AzureOpenAIClient, LLMError
from video_selection_agent.llm.rationale_prompts import (
    RATIONALE_JSON_SCHEMA,
    RATIONALE_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)


def _fallback_rationale(reasons: list[str], tier: str, channel_name: str) -> str:
    parts = []
    if reasons:
        parts.append(f"{', '.join(reasons)} 측면에서 선정되었습니다.")
    if tier in {"small", "micro", "mid"}:
        parts.append(f"{channel_name} 채널은 대형 채널 대비 다양한 관점을 제공합니다.")
    elif tier == "large":
        parts.append(f"{channel_name} 채널은 리뷰어 인지도와 참여도가 균형적입니다.")
    else:
        parts.append(f"{channel_name} 채널은 광범위한 시청자 참여를 확보했습니다.")
    return " ".join(parts) or "종합 점수 상위 후보로 선정되었습니다."


def _build_user_message(state: SelectionState) -> str:
    product = state["product"]
    selected = state.get("final_selection", [])
    items = []
    for v in selected:
        items.append({
            "video_id": v.video_id,
            "title": v.title,
            "channel_name": v.channel_name,
            "tier": v.tier,
            "dimensions": {k: round(val, 3) for k, val in v.dimensions.items()},
            "selection_reasons": v.selection_reasons,
        })
    payload = {
        "product": {
            "name": product.name,
            "brand": product.brand,
            "category": product.category,
        },
        "selected_videos": items,
    }
    return (
        "다음 선정된 영상들 각각에 대해 2-3문장 한국어 rationale_full을 작성하세요.\n"
        "각 영상의 점수 차원과 티어를 반영하되, 과장 없이 중립적으로 서술하세요.\n\n"
        + json.dumps(payload, ensure_ascii=False)
    )


def generate_rationale(state: SelectionState) -> SelectionState:
    """선정작 rationale_full 채움."""
    trace = list(state.get("trace", []))
    selected = list(state.get("final_selection", []))
    if not selected:
        trace.append("generate_rationale: no selection — skip")
        return {**state, "trace": trace}

    client = AzureOpenAIClient()
    user_msg = _build_user_message(state)

    try:
        response = client.chat_structured(
            system=RATIONALE_SYSTEM_PROMPT,
            user=user_msg,
            json_schema=RATIONALE_JSON_SCHEMA,
            max_tokens=1500,
            temperature=0.3,
        )
        rationale_map = {
            r.get("video_id"): (r.get("rationale_full") or "")[:600]
            for r in response.get("rationales", [])
            if r.get("video_id")
        }
        filled = 0
        for v in selected:
            if v.video_id in rationale_map and rationale_map[v.video_id]:
                v.rationale_full = rationale_map[v.video_id]
                filled += 1
            else:
                v.rationale_full = _fallback_rationale(
                    v.selection_reasons, v.tier, v.channel_name
                )
        trace.append(f"generate_rationale: LLM filled {filled}/{len(selected)}")
    except LLMError as e:
        logger.warning("generate_rationale LLM failure, using fallback: %s", e)
        for v in selected:
            v.rationale_full = _fallback_rationale(
                v.selection_reasons, v.tier, v.channel_name
            )
        trace.append(f"generate_rationale: LLM failed ({type(e).__name__}) — fallback")

    scores = state.get("scores", {})
    for v in selected:
        sb = scores.get(v.video_id)
        if sb is not None:
            sb.llm_rationale_full = v.rationale_full

    return {**state, "final_selection": selected, "scores": scores, "trace": trace}
