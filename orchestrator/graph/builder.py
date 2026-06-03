"""Supervisor StateGraph 빌더.

video_selection_agent/graph/builder.py 의 패턴을 따른다:
  - langgraph 로 StateGraph 구성 + 조건부 엣지
  - langgraph 미설치 시 _FallbackLinearGraph 가 동일 라우팅을 순수 파이썬으로 에뮬레이션

차이점: ④ 파이프라인 함수는 코루틴이므로 노드도 async 다. 따라서 fallback 은 sync
`invoke` 대신 **async `ainvoke`** 를 노출하고, runner 는 real/fallback 모두에 대해
`await graph.ainvoke(state)` 단일 호출부를 쓴다(duck typing).

라우팅:
  START → inspect_freshness
  inspect_freshness ─→ load_cached | heal_comments | ensure_reports | collect_and_heal_parallel
  load_cached → END
  heal_comments → ensure_reports
  ensure_reports / collect_and_heal_parallel ─→ synthesize | mark_insufficient
  mark_insufficient → END
  synthesize → persist → END
"""
from __future__ import annotations

from typing import Any

from orchestrator.graph.nodes import (
    collect_and_heal_parallel,
    ensure_reports,
    heal_comments,
    inspect_freshness,
    load_cached,
    mark_insufficient,
    persist,
    synthesize,
)
from orchestrator.graph.state import InsightState


def _cache_hit(freshness: dict, input_expansion: bool) -> bool:
    """동일 조합 ④ 가 있고, ④ 가 소비할 입력이 전부 신선하면 True.

    - ON(input_expansion): ④ 는 영상별 ①②③ 을 종합 → 모든 영상이 fully_reported.
    - OFF(레거시): ④ 는 자막 기반 ① 만 소비 → 모든 영상이 r1 보유.
    두 경우 모두 댓글 분석 완료(⑤ 집계용) + 자막 누락 없음을 요구한다.
    """
    if not freshness.get("prior_exact_match"):
        return False
    if not freshness.get("all_comment_analyzed"):
        return False
    if freshness.get("transcript_missing_ids"):
        return False
    video_ids = set(freshness.get("video_ids", []))
    if input_expansion:
        return set(freshness.get("fully_reported_ids", [])) >= video_ids
    status = freshness.get("reports_status", {})
    return all(status.get(v, {}).get("r1") for v in video_ids)


def route_after_freshness(state: InsightState) -> str:
    f = state["freshness"]
    if (not state.get("force")) and _cache_hit(f, state.get("input_expansion", True)):
        return "load_cached"
    if not state.get("input_expansion", True):
        return "collect_and_heal_parallel"  # OFF: 기존 gather 병렬 보존
    return "ensure_reports" if f["all_comment_analyzed"] else "heal_comments"


def route_after_reports(state: InsightState) -> str:
    return "synthesize" if len(state.get("per_video_reports", [])) >= 2 else "mark_insufficient"


def build_insight_graph() -> Any:
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError:
        return _FallbackLinearGraph()

    graph = StateGraph(InsightState)
    graph.add_node("inspect_freshness", inspect_freshness)
    graph.add_node("load_cached", load_cached)
    graph.add_node("heal_comments", heal_comments)
    graph.add_node("ensure_reports", ensure_reports)
    graph.add_node("collect_and_heal_parallel", collect_and_heal_parallel)
    graph.add_node("mark_insufficient", mark_insufficient)
    graph.add_node("synthesize", synthesize)
    graph.add_node("persist", persist)

    graph.add_edge(START, "inspect_freshness")
    graph.add_conditional_edges(
        "inspect_freshness",
        route_after_freshness,
        {
            "load_cached": "load_cached",
            "heal_comments": "heal_comments",
            "ensure_reports": "ensure_reports",
            "collect_and_heal_parallel": "collect_and_heal_parallel",
        },
    )
    graph.add_edge("load_cached", END)
    graph.add_edge("heal_comments", "ensure_reports")
    graph.add_conditional_edges(
        "ensure_reports",
        route_after_reports,
        {"synthesize": "synthesize", "mark_insufficient": "mark_insufficient"},
    )
    graph.add_conditional_edges(
        "collect_and_heal_parallel",
        route_after_reports,
        {"synthesize": "synthesize", "mark_insufficient": "mark_insufficient"},
    )
    graph.add_edge("mark_insufficient", END)
    graph.add_edge("synthesize", "persist")
    graph.add_edge("persist", END)

    return graph.compile()


class _FallbackLinearGraph:
    """langgraph 미설치 시 동일 라우팅을 async 로 에뮬레이션."""

    async def ainvoke(self, state: InsightState) -> InsightState:
        state = await inspect_freshness(state)  # type: ignore[assignment]
        f = state["freshness"]

        if (not state.get("force")) and _cache_hit(f, state.get("input_expansion", True)):
            return await load_cached(state)  # type: ignore[return-value]

        if state.get("input_expansion", True):
            if not f["all_comment_analyzed"]:
                state = await heal_comments(state)  # type: ignore[assignment]
            state = await ensure_reports(state)  # type: ignore[assignment]
        else:
            state = await collect_and_heal_parallel(state)  # type: ignore[assignment]

        if len(state.get("per_video_reports", [])) < 2:
            return await mark_insufficient(state)  # type: ignore[return-value]

        state = await synthesize(state)  # type: ignore[assignment]
        state = await persist(state)  # type: ignore[assignment]
        return state

    def invoke(self, state: InsightState) -> InsightState:  # pragma: no cover
        raise RuntimeError("InsightGraph has async nodes — use `await graph.ainvoke(state)`")
