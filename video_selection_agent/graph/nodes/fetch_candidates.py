"""Node 1: 다중 쿼리로 YouTube 후보 풀 수집."""
from __future__ import annotations

from video_selection_agent.graph.state import SelectionState
from video_selection_agent.youtube.candidate_pool import build_candidate_pool


def fetch_candidates(state: SelectionState) -> SelectionState:
    product = state["product"]
    policy = state["policy"]
    pool = build_candidate_pool(product, target_size=policy.candidate_pool_size)

    trace = list(state.get("trace", []))
    trace.append(f"fetch_candidates: {len(pool)} candidates")
    return {**state, "candidates": pool, "trace": trace}
