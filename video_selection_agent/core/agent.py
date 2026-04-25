"""VideoSelectionAgent facade.

외부에서는 이 클래스만 사용 → graph/nodes/scoring/llm 내부 구조 노출 X.
`comment_filtering_agent.core.agent.AgentDecisionEngine` 컨벤션 참고.
"""
from __future__ import annotations

from uuid import UUID, uuid4

from video_selection_agent.core.models import (
    DiversityReport,
    ProductContext,
    SelectionDecision,
    SelectionMode,
)
from video_selection_agent.core.policy import SelectionPolicyConfig
from video_selection_agent.graph.builder import build_graph
from video_selection_agent.graph.state import SelectionState


class VideoSelectionAgent:
    """FR-005 영상 선택 에이전트 (Auto/Custom).

    사용:
        agent = VideoSelectionAgent()
        decision = agent.select(product=..., mode="auto", k=5)
    """

    def __init__(
        self,
        policy: SelectionPolicyConfig | None = None,
        model_name: str = "gpt-4.1-mini",
    ):
        self.policy = policy or SelectionPolicyConfig()
        self.model_name = model_name
        self._graph = build_graph()

    def select(
        self,
        product: ProductContext,
        mode: SelectionMode = "auto",
        k: int = 5,
        selected_video_ids: list[str] | None = None,
    ) -> SelectionDecision:
        """LangGraph를 실행해 SelectionDecision 반환.

        - `auto`: 에이전트가 상위 k개 자동 선정.
        - `custom`: 동일 풀 후보 30개 반환, `selected_video_ids`로 필터.
        """
        run_id: UUID = uuid4()
        k_clamped = self.policy.clamp_k(k)

        initial_state: SelectionState = {
            "run_id": run_id,
            "product": product,
            "mode": mode,
            "k_requested": k_clamped,
            "selected_video_ids": selected_video_ids or [],
            "policy": self.policy,
            "candidates": [],
            "scores": {},
            "llm_reranked": [],
            "final_selection": [],
            "errors": [],
            "trace": [f"agent.select start (mode={mode}, k={k_clamped})"],
            "relax_attempts": 0,
        }

        final_state: SelectionState = self._graph.invoke(initial_state)  # type: ignore[assignment]

        return SelectionDecision(
            run_id=run_id,
            product_id=product.product_id,
            mode=mode,
            selected=final_state.get("final_selection", []),
            candidates_preview=final_state.get("candidates", []),
            diversity_report=final_state.get(
                "diversity_report",
                DiversityReport(
                    channels_unique=0,
                    tier_distribution={},
                    max_channel_occurrence=0,
                ),
            ),
            candidate_count=len(final_state.get("candidates", [])),
            model_used=self.model_name,
            policy_version=final_state.get("policy", self.policy).policy_version,
            trace=final_state.get("trace", []),
            all_scores=final_state.get("scores", {}),
        )
