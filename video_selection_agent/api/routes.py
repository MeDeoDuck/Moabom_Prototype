"""FR-005 엔드포인트.

POST /products/{product_id}/select-videos
GET  /products/{product_id}/selection-runs/{run_id}

Phase-1: 목업 응답 (agent는 빈 결과 반환). 기존 /sync는 손대지 않음.
"""
from __future__ import annotations

from typing import Any, Literal, Optional
from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from scripts.database.queries import query_one
from video_selection_agent.core.agent import VideoSelectionAgent
from video_selection_agent.core.models import ProductContext
from video_selection_agent.core.policy import SelectionPolicyConfig
from video_selection_agent.persistence.repository import load_selection, save_selection


class SelectVideosRequest(BaseModel):
    mode: Literal["auto", "custom"] = "auto"
    k: int = Field(5, ge=3, le=10)
    candidate_pool_size: int = Field(30, ge=25, le=50)
    selected_video_ids: Optional[list[str]] = None
    weights_override: Optional[dict[str, float]] = None


def _decision_to_response(decision: Any) -> dict:
    return {
        "run_id": str(decision.run_id),
        "mode": decision.mode,
        "selected": [
            {
                "video_id": v.video_id,
                "title": v.title,
                "channel_name": v.channel_name,
                "tier": v.tier,
                "rank": v.rank,
                "final_score": v.final_score,
                "dimensions": v.dimensions,
                "weighted_contributions": v.weighted_contributions,
                "rationale_short": v.rationale_short,
                "rationale_full": v.rationale_full,
                "selection_reasons": v.selection_reasons,
            }
            for v in decision.selected
        ],
        "candidates_preview": [
            {
                "video_id": c.video_id,
                "title": c.title,
                "channel_name": c.channel_name,
            }
            for c in decision.candidates_preview
        ],
        "diversity_report": {
            "channels_unique": decision.diversity_report.channels_unique,
            "tier_distribution": decision.diversity_report.tier_distribution,
            "max_channel_occurrence": decision.diversity_report.max_channel_occurrence,
        },
        "candidate_count": decision.candidate_count,
        "model_used": decision.model_used,
        "policy_version": decision.policy_version,
    }


def register_selection_routes(app: FastAPI) -> None:
    """main.py에서 1회 호출."""

    @app.post("/products/{product_id}/select-videos")
    async def select_videos(product_id: int, request: SelectVideosRequest) -> dict:
        product = query_one(
            "SELECT * FROM tech_products WHERE product_id = %s", (product_id,)
        )
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        context = ProductContext(
            product_id=product_id,
            name=product["name"],
            brand=product.get("brand"),
            category=product.get("category"),
            keywords=[],
        )

        policy = SelectionPolicyConfig(candidate_pool_size=request.candidate_pool_size)
        agent = VideoSelectionAgent(policy=policy)
        decision = agent.select(
            product=context,
            mode=request.mode,
            k=request.k,
            selected_video_ids=request.selected_video_ids,
        )

        selected_ids = {v.video_id for v in decision.selected}
        all_scores = {
            vid: {
                "final_score": float(sb.final_score),
                "dimensions": sb.dimensions,
                "tier": sb.tier,
                "rank": sb.rank,
                "rationale_short": sb.llm_rationale_short,
                "rationale_full": sb.llm_rationale_full,
                "selected": vid in selected_ids,
            }
            for vid, sb in decision.all_scores.items()
        }
        candidate_lookup = {
            c.video_id: {
                "title": c.title,
                "description": c.description,
                "published_at": c.published_at,
                "thumbnail_url": c.thumbnail_url,
                "view_count": c.view_count,
                "like_count": c.like_count,
                "comment_count": c.comment_count,
                "channel_id": c.channel_id,
                "channel_name": c.channel_name,
                "channel_subscriber_count": c.channel_subscriber_count,
                "duration_seconds": c.duration_seconds,
            }
            for c in decision.candidates_preview
        }
        save_selection(decision, all_scores=all_scores, candidate_lookup=candidate_lookup)
        return _decision_to_response(decision)

    @app.get("/products/{product_id}/selection-runs/{run_id}")
    async def get_selection_run(product_id: int, run_id: UUID) -> dict:
        decision = load_selection(run_id)
        if decision is None or decision.product_id != product_id:
            raise HTTPException(status_code=404, detail="Selection run not found")
        return _decision_to_response(decision)
