"""Phase-1 smoke test: graph가 import 되고 invoke가 완주하는지 확인."""
from __future__ import annotations

from video_selection_agent.core.agent import VideoSelectionAgent
from video_selection_agent.core.models import ProductContext


def test_agent_select_smoke() -> None:
    """graph 가 예외 없이 완주하고 SelectionDecision 을 반환하는지(오프라인 smoke).

    후보 수/선정 수는 네트워크(YOUTUBE_API_KEY) 유무에 좌우되므로 단언하지 않는다.
    """
    agent = VideoSelectionAgent()
    product = ProductContext(product_id=1, name="iPhone 15 Pro", brand="Apple", category="phone")
    decision = agent.select(product=product, mode="auto", k=5)

    assert decision.product_id == 1
    assert decision.mode == "auto"
    assert isinstance(decision.selected, list)
    assert decision.trace  # 최소한 시작 trace 는 존재


def test_policy_clamp() -> None:
    from video_selection_agent.core.policy import SelectionPolicyConfig

    p = SelectionPolicyConfig()
    assert p.clamp_k(1) == p.k_min
    assert p.clamp_k(100) == p.k_max
    assert p.clamp_k(5) == 5
