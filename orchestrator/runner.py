"""④ 통합보고서 Supervisor 진입점.

라우트(scripts/api/products.py)가 호출하는 단일 오케스트레이션 엔트리. 초기 상태를
조립해 그래프를 실행하고, 라우트가 기존 응답 JSON 을 그대로 조립할 수 있도록 평탄한
dict 를 반환한다. 예외는 삼키지 않고 FastAPI 로 전파한다(현행 동일). total_ms 는
라우트가 계속 소유한다.
"""
from __future__ import annotations

from typing import Any, Dict, List

from orchestrator.graph.builder import build_insight_graph

# 그래프는 stateless 하므로 1회만 컴파일해 재사용 (video_selection_agent 와 동일하게
# 빌드는 가볍고 멱등하다).
_GRAPH = build_insight_graph()


async def run_insight_supervisor(
    product_id: int,
    product_name: str,
    video_ids: List[str],
    selected_video_count: int,
    force: bool = False,
) -> Dict[str, Any]:
    """④ 파이프라인을 Supervisor 그래프로 실행하고 라우트용 결과 dict 를 반환한다."""
    from scripts.config import REPORT4_INPUT_EXPANSION

    initial: Dict[str, Any] = {
        "product_id": product_id,
        "product_name": product_name,
        "video_ids": list(video_ids),
        "selected_video_count": selected_video_count,
        "force": bool(force),
        "input_expansion": bool(REPORT4_INPUT_EXPANSION),
        "perf": {},
        "trace": [],
        "error": None,
    }

    final = await _GRAPH.ainvoke(initial)

    per_video_reports = final.get("per_video_reports", []) or []
    analyzed_video_ids = final.get("analyzed_video_ids", []) or []
    cache_hit = bool(final.get("cache_hit", False))

    # source_video_count: 일반 경로는 분석된 보고서 수, 캐시 경로는 기존 저장값(없으면
    # 분석 video_ids 수)을 사용한다.
    if cache_hit:
        prior = final.get("freshness", {}).get("prior_source_video_count")
        source_video_count = int(prior) if prior is not None else len(analyzed_video_ids)
    else:
        source_video_count = len(per_video_reports)

    return {
        "error": final.get("error"),
        "report_id": final.get("report_id"),
        "report_text": final.get("report_text", ""),
        "model_used": final.get("model_used"),
        "per_video_reports": per_video_reports,
        "analyzed_video_ids": analyzed_video_ids,
        "excluded_video_ids": final.get("excluded_video_ids", []) or [],
        "source_video_count": source_video_count,
        "selected_video_count": selected_video_count,
        "cache_hit": cache_hit,
        "perf": final.get("perf", {}) or {},
        "trace": final.get("trace", []) or [],
    }
