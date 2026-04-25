"""LangGraph 공유 state 타입."""
from __future__ import annotations

from typing import TypedDict
from uuid import UUID

from video_selection_agent.core.models import (
    DiversityReport,
    ProductContext,
    RerankResult,
    ScoreBreakdown,
    SelectedVideo,
    SelectionMode,
    VideoCandidate,
)
from video_selection_agent.core.policy import SelectionPolicyConfig


class SelectionState(TypedDict, total=False):
    """노드 간 전달되는 공유 상태.

    total=False로 선언해 각 노드가 필요한 키만 추가하게 함.
    """
    run_id: UUID
    product: ProductContext
    mode: SelectionMode
    k_requested: int
    selected_video_ids: list[str]
    policy: SelectionPolicyConfig

    candidates: list[VideoCandidate]
    scores: dict[str, ScoreBreakdown]
    diversity_report: DiversityReport
    llm_reranked: list[RerankResult]
    final_selection: list[SelectedVideo]

    errors: list[str]
    trace: list[str]
    relax_attempts: int
