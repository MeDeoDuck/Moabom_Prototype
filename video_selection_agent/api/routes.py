"""FR-005 엔드포인트.

POST /products/{product_id}/select-videos
GET  /products/{product_id}/selection-runs/{run_id}

선정된 영상에 대해 댓글 수집·필터링 파이프라인까지 동기 실행해서 댓글/통합
보고서가 빈 채로 표시되지 않도록 한다 (Custom UI의 첫 번째 미리보기 호출은
`process_comments=false`로 스킵 가능).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Iterable, Literal, Optional
from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from scripts.database.queries import execute_update, query_one
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
    # Custom UI의 미리보기 호출에서는 false로 두어 댓글 파이프라인을 건너뛴다.
    # 그 외(Auto-only, Custom 확정)에서는 반드시 true 여야 댓글/통합 보고서가 채워짐.
    process_comments: bool = True


def _process_comments_for_videos(product_name: str, video_ids: Iterable[str]) -> None:
    """선정된 영상들에 대해 댓글 수집·LLM 분류·감정 분석 파이프라인을 병렬 실행."""
    ids = [vid for vid in video_ids if vid]
    if not ids:
        return

    try:
        from scripts.api.sync import (
            AGENT_AVAILABLE,
            PARALLEL_WORKERS,
            process_comments_with_agent,
        )
    except ImportError as exc:
        print(f"[SELECT] Comment agent module unavailable: {exc}")
        return

    if not AGENT_AVAILABLE:
        print("[SELECT] Comment filtering agent not available; skipping comment processing")
        return

    print(
        f"[SELECT] Comment processing start: videos={len(ids)}, parallel={PARALLEL_WORKERS}"
    )
    with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as executor:
        futures = {
            executor.submit(process_comments_with_agent, vid, product_name): vid
            for vid in ids
        }
        for future in as_completed(futures):
            vid = futures[future]
            try:
                stats = future.result()
                print(f"[SELECT] [{vid}] Comments processed: {stats}")
            except Exception as exc:  # noqa: BLE001 - log and continue per-video
                print(f"[SELECT] [{vid}] Comment processing failed: {exc}")


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
        # 새 선정 결과로 갈아끼우기 위해 이 제품의 기존 영상을 먼저 정리한다.
        # Custom UI의 "후보 미리보기" 호출(process_comments=False)은 사용자가 아직
        # 확정하지 않은 단계라 기존 데이터를 건드리지 않는다.
        # videos.product_id ON DELETE CASCADE 로 comments / video_transcripts /
        # video_reports / comment_sentiments / agent_decisions 까지 함께 정리됨.
        if request.process_comments:
            execute_update(
                "DELETE FROM videos WHERE product_id = %s",
                (product_id,),
            )

        save_selection(decision, all_scores=all_scores, candidate_lookup=candidate_lookup)

        if request.process_comments:
            _process_comments_for_videos(
                product_name=context.name,
                video_ids=[v.video_id for v in decision.selected],
            )

        return _decision_to_response(decision)

    @app.get("/products/{product_id}/selection-runs/{run_id}")
    async def get_selection_run(product_id: int, run_id: UUID) -> dict:
        decision = load_selection(run_id)
        if decision is None or decision.product_id != product_id:
            raise HTTPException(status_code=404, detail="Selection run not found")
        return _decision_to_response(decision)
