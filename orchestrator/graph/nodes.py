"""Supervisor 그래프 노드 — 기존 ④ 파이프라인 함수의 얇은 래퍼.

각 노드는 async 이며 state 를 읽어 기존 함수를 호출하고, 직후 해당
get_last_*_perf() 스냅샷을 perf 에 담아 `{**state, ...}` 로 반환한다. 기존 함수의
내부 구조·YouTube API 호출은 일절 수정하지 않는다 — 블랙박스 호출만 한다.

sync 함수(build/save)와 blocking SELECT(freshness)는 레포 관례대로 asyncio.to_thread
로 감싸 이벤트 루프를 막지 않는다.
"""
from __future__ import annotations

import asyncio
from time import perf_counter
from typing import List

from orchestrator.freshness import inspect_freshness as _inspect_freshness
from orchestrator.graph.state import InsightState
from orchestrator.progress import emit_insight_progress
from scripts.reports.product_integrated_insight import (
    build_product_integrated_insight_report,
    collect_transcript_reports_for_product,
    ensure_all_reports_for_product,
    ensure_comment_analysis_for_videos,
    get_last_collect_perf,
    get_last_comment_heal_perf,
    get_last_input_expansion_perf,
    get_last_llm_perf,
    get_product_integrated_report,
    save_product_integrated_report,
)


def _trace(state: InsightState, line: str) -> List[str]:
    trace = list(state.get("trace", []))
    trace.append(line)
    return trace


async def inspect_freshness(state: InsightState) -> InsightState:
    perf = dict(state.get("perf", {}))
    t0 = perf_counter()
    freshness = await asyncio.to_thread(
        _inspect_freshness, state["product_id"], state["video_ids"]
    )
    perf["freshness_ms"] = round((perf_counter() - t0) * 1000, 1)
    return {
        **state,
        "freshness": freshness,
        "perf": perf,
        "trace": _trace(
            state,
            f"inspect_freshness: all_comment_analyzed={freshness['all_comment_analyzed']} "
            f"transcript_missing={len(freshness['transcript_missing_ids'])} "
            f"fully_reported={len(freshness['fully_reported_ids'])}/{freshness['total']} "
            f"prior_exact_match={freshness['prior_exact_match']}",
        ),
    }


async def load_cached(state: InsightState) -> InsightState:
    """동일 조합 + 모든 입력 신선 → 기존 ④ 보고서를 DB 에서 즉시 반환."""
    perf = dict(state.get("perf", {}))
    f = state["freshness"]
    prior_id = f["prior_report_id"]
    t0 = perf_counter()
    row = await asyncio.to_thread(
        get_product_integrated_report, state["product_id"], prior_id
    )
    perf["cache_load_ms"] = round((perf_counter() - t0) * 1000, 1)
    perf["cache_hit"] = True

    analyzed = list(f["prior_video_ids"]) or list(state["video_ids"])
    excluded = [v for v in state["video_ids"] if v not in set(analyzed)]
    return {
        **state,
        "report_id": prior_id,
        "report_text": (row or {}).get("report_text", ""),
        "model_used": (row or {}).get("model_used") or "cache",
        "analyzed_video_ids": analyzed,
        "excluded_video_ids": excluded,
        "cache_hit": True,
        "perf": perf,
        "trace": _trace(state, f"load_cached: report_id={prior_id} (cache hit, LLM skip)"),
    }


async def heal_comments(state: InsightState) -> InsightState:
    emit_insight_progress(state["product_id"], phase="comments_heal")
    perf = dict(state.get("perf", {}))
    t0 = perf_counter()
    stats = await ensure_comment_analysis_for_videos(
        state["product_name"], state["video_ids"]
    )
    perf["collect_ms"] = round(perf.get("collect_ms", 0.0) + (perf_counter() - t0) * 1000, 1)
    perf["comment_heal_detail"] = get_last_comment_heal_perf()
    return {
        **state,
        "comment_heal_stats": stats,
        "perf": perf,
        "trace": _trace(
            state,
            f"heal_comments: healed={stats.get('healed')} "
            f"already={stats.get('already_analyzed')} failed={stats.get('failed')}",
        ),
    }


async def ensure_reports(state: InsightState) -> InsightState:
    """ON 경로: ①②③ 보장 + bundle 수집 (ensure_all_reports_for_product)."""
    emit_insight_progress(state["product_id"], phase="reports")
    perf = dict(state.get("perf", {}))
    t0 = perf_counter()
    bundles = await ensure_all_reports_for_product(
        state["product_id"], state["product_name"], state["video_ids"]
    )
    perf["collect_ms"] = round(perf.get("collect_ms", 0.0) + (perf_counter() - t0) * 1000, 1)
    perf["collect_detail"] = get_last_collect_perf()
    perf["input_expansion_detail"] = get_last_input_expansion_perf()
    analyzed = [r["video_id"] for r in bundles]
    excluded = [v for v in state["video_ids"] if v not in set(analyzed)]
    return {
        **state,
        "per_video_reports": bundles,
        "analyzed_video_ids": analyzed,
        "excluded_video_ids": excluded,
        "perf": perf,
        "trace": _trace(state, f"ensure_reports(ON): bundles={len(bundles)}"),
    }


async def collect_and_heal_parallel(state: InsightState) -> InsightState:
    """OFF(레거시) 경로: 자막 ① 수집과 댓글 self-heal 을 기존처럼 병렬 실행.

    기존 라우트의 asyncio.gather 동작을 byte-for-byte 보존한다.
    """
    emit_insight_progress(state["product_id"], phase="reports")
    perf = dict(state.get("perf", {}))
    t0 = perf_counter()
    per_video_reports, comment_heal_stats = await asyncio.gather(
        collect_transcript_reports_for_product(state["product_id"], state["video_ids"]),
        ensure_comment_analysis_for_videos(state["product_name"], state["video_ids"]),
    )
    perf["collect_ms"] = round((perf_counter() - t0) * 1000, 1)
    perf["collect_detail"] = get_last_collect_perf()
    perf["input_expansion_detail"] = get_last_input_expansion_perf()
    perf["comment_heal_detail"] = get_last_comment_heal_perf()
    analyzed = [r["video_id"] for r in per_video_reports]
    excluded = [v for v in state["video_ids"] if v not in set(analyzed)]
    return {
        **state,
        "per_video_reports": per_video_reports,
        "comment_heal_stats": comment_heal_stats,
        "analyzed_video_ids": analyzed,
        "excluded_video_ids": excluded,
        "perf": perf,
        "trace": _trace(state, f"collect_and_heal_parallel(OFF): reports={len(per_video_reports)}"),
    }


async def mark_insufficient(state: InsightState) -> InsightState:
    """분석 가능한 보고서가 2개 미만 — 라우트가 HTTP 400 으로 변환."""
    return {
        **state,
        "error": "insufficient_reports",
        "trace": _trace(
            state,
            f"mark_insufficient: per_video_reports={len(state.get('per_video_reports', []))} < 2",
        ),
    }


async def synthesize(state: InsightState) -> InsightState:
    emit_insight_progress(state["product_id"], phase="synthesize")
    perf = dict(state.get("perf", {}))
    t0 = perf_counter()
    report_text, model_used = await asyncio.to_thread(
        build_product_integrated_insight_report,
        state["product_name"],
        state["per_video_reports"],
        state["analyzed_video_ids"],
        state["selected_video_count"],
    )
    perf["build_ms"] = round((perf_counter() - t0) * 1000, 1)
    perf["llm_detail"] = get_last_llm_perf()
    return {
        **state,
        "report_text": report_text,
        "model_used": model_used,
        "perf": perf,
        "trace": _trace(state, f"synthesize: model={model_used} len={len(report_text)}"),
    }


async def persist(state: InsightState) -> InsightState:
    emit_insight_progress(state["product_id"], phase="save")
    perf = dict(state.get("perf", {}))
    t0 = perf_counter()
    report_id = await asyncio.to_thread(
        save_product_integrated_report,
        state["product_id"],
        [r["video_id"] for r in state["per_video_reports"]],
        state["report_text"],
        state["model_used"],
    )
    perf["save_ms"] = round((perf_counter() - t0) * 1000, 1)
    return {
        **state,
        "report_id": report_id,
        "perf": perf,
        "trace": _trace(state, f"persist: report_id={report_id}"),
    }
