"""Phase-1 smoke test: graph가 import 되고 invoke가 완주하는지 확인."""
from __future__ import annotations

from video_selection_agent.core.agent import VideoSelectionAgent
from video_selection_agent.core.models import ProductContext


def test_agent_select_smoke() -> None:
    """Skeleton은 빈 결과를 반환하되 예외 없이 완주해야 함."""
    agent = VideoSelectionAgent()
    product = ProductContext(product_id=1, name="iPhone 15 Pro", brand="Apple", category="phone")
    decision = agent.select(product=product, mode="auto", k=5)

    assert decision.product_id == 1
    assert decision.mode == "auto"
    assert decision.candidate_count == 0
    assert len(decision.selected) == 0
    # 모든 노드가 trace를 남겨야 함 (fetch/enrich/score/diversity/rerank/finalize/rationale + 시작)
    assert len(decision.trace) >= 8


def test_policy_clamp() -> None:
    from video_selection_agent.core.policy import SelectionPolicyConfig

    p = SelectionPolicyConfig()
    assert p.clamp_k(1) == p.k_min
    assert p.clamp_k(100) == p.k_max
    assert p.clamp_k(5) == 5
