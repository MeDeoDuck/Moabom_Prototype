"""Supervisor 그래프 상태.

video_selection_agent/graph/state.py 의 TypedDict(total=False) 관례를 따른다.
노드는 reducer 없이 `return {**state, ...}` 로 전체 치환한다 (병렬 fan-in 없음 —
OFF 경로 병렬은 단일 노드 내부 asyncio.gather 로 처리되므로 그래프 레벨 동시
쓰기가 발생하지 않는다).
"""
from __future__ import annotations

from typing import List, Optional, TypedDict

from orchestrator.freshness import FreshnessReport


class InsightState(TypedDict, total=False):
    # ── 입력 ────────────────────────────────────────────────
    product_id: int
    product_name: str
    video_ids: List[str]          # 라우트에서 dedup/정규화 완료된 입력 순서
    selected_video_count: int
    force: bool                   # True 면 캐시 무시하고 재생성
    input_expansion: bool         # REPORT4_INPUT_EXPANSION 1회 스냅샷

    # ── inspect_freshness 산출 ──────────────────────────────
    freshness: FreshnessReport

    # ── heal/ensure/collect 산출 ────────────────────────────
    comment_heal_stats: dict
    per_video_reports: List[dict]
    analyzed_video_ids: List[str]
    excluded_video_ids: List[str]

    # ── synthesize / persist 산출 ───────────────────────────
    report_text: str
    model_used: str
    report_id: int
    cache_hit: bool

    # ── perf / 제어 ─────────────────────────────────────────
    perf: dict                    # collect_ms/build_ms/save_ms + detail dicts
    error: Optional[str]          # "insufficient_reports" | None
    trace: List[str]
