"""영상 선정 결과 정량 지표 계산기 (순수 함수, 네트워크/DB 없음).

입력: `video_selection_scores` 행 리스트 (또는 동등한 dict). 각 항목 키:
    video_id (str)
    selected (bool)
    rank (int|None)
    final_score (float|None)
    dimensions_json (dict) — `_floor_pass_*`, `_review_scope*` underscore-prefix 키 포함
    tier (str|None)
    channel_id (str|None, 옵션)   — 채널 다양성 산출용 (있을 때만)

출력 dict 구조는 stable: 키 추가는 OK, 키 의미 변경 X (regression 안정성).
"""
from __future__ import annotations

from collections import Counter
from statistics import mean
from typing import Any, Iterable

# dimensions_json 안의 underscore-prefix 키 (persist 시 routes.py 가 박는 값)
KEY_FLOOR_RELEVANCE = "_floor_pass_relevance"
KEY_FLOOR_DURATION = "_floor_pass_duration"
KEY_REVIEW_SCOPE = "_review_scope"
KEY_REVIEW_SCOPE_CONF = "_review_scope_confidence"

# 진짜 dimension 키 — average 계산 시 underscore 키와 구분하기 위함
_REAL_DIM_KEYS = (
    "relevance",
    "engagement",
    "recency",
    "channel_anti_bias",
    "duration_fit",
    "llm_topical_fit",
)


def _dims(row: dict[str, Any]) -> dict[str, Any]:
    return row.get("dimensions_json") or row.get("dimensions") or {}


def _scope(row: dict[str, Any]) -> str:
    return str(_dims(row).get(KEY_REVIEW_SCOPE, "unknown"))


def _selected(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r.get("selected")]


def _real_dim_avg(rows: Iterable[dict[str, Any]]) -> dict[str, float]:
    """selected/rejected 그룹의 실제 dimension 평균 (underscore 키 제외)."""
    sums: dict[str, float] = {k: 0.0 for k in _REAL_DIM_KEYS}
    counts: dict[str, int] = {k: 0 for k in _REAL_DIM_KEYS}
    for r in rows:
        d = _dims(r)
        for k in _REAL_DIM_KEYS:
            v = d.get(k)
            if isinstance(v, (int, float)):
                sums[k] += float(v)
                counts[k] += 1
    return {k: (sums[k] / counts[k]) if counts[k] else 0.0 for k in _REAL_DIM_KEYS}


def compute_selection_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """단일 run 의 video_selection_scores 행을 받아 지표 계산.

    rows 가 비어 있으면 모든 카운터는 0, 비율은 0.0 으로 반환.
    """
    total = len(rows)
    selected = _selected(rows)
    k = len(selected)

    # 1. single_product_ratio@k — 선정 k개 중 단일 제품 리뷰 비율
    single_in_selected = sum(1 for r in selected if _scope(r) == "single")
    comparison_in_selected = sum(1 for r in selected if _scope(r) == "comparison")
    roundup_in_selected = sum(1 for r in selected if _scope(r) == "roundup")
    unknown_in_selected = sum(1 for r in selected if _scope(r) == "unknown")

    # 2. floor_pass_rate — 후보 전체 기준
    rel_pass = sum(1 for r in rows if _dims(r).get(KEY_FLOOR_RELEVANCE) is True)
    dur_pass = sum(1 for r in rows if _dims(r).get(KEY_FLOOR_DURATION) is True)

    # 3. scope_distribution — 후보 전체 기준 enum 분포
    scope_counter: Counter[str] = Counter(_scope(r) for r in rows)

    # 4. channel diversity (channel_id 있을 때만 의미 있음)
    selected_channels = [r.get("channel_id") for r in selected if r.get("channel_id")]
    selected_tiers = [r.get("tier") for r in selected if r.get("tier")]

    # 5. score distribution (selected vs rejected 의 dim 평균)
    rejected = [r for r in rows if not r.get("selected")]
    selected_avg = _real_dim_avg(selected)
    rejected_avg = _real_dim_avg(rejected)

    # 6. bias_audit — 채널 anti-bias 가중치가 selected/rejected 분포에 어떻게 작용했나
    sel_anti_bias = [
        float(_dims(r).get("channel_anti_bias", 0.0))
        for r in selected
        if isinstance(_dims(r).get("channel_anti_bias"), (int, float))
    ]
    rej_anti_bias = [
        float(_dims(r).get("channel_anti_bias", 0.0))
        for r in rejected
        if isinstance(_dims(r).get("channel_anti_bias"), (int, float))
    ]

    return {
        "candidate_count": total,
        "selected_count": k,
        "single_product_ratio_at_k": (single_in_selected / k) if k else 0.0,
        "selected_scope_distribution": {
            "single": single_in_selected,
            "comparison": comparison_in_selected,
            "roundup": roundup_in_selected,
            "unknown": unknown_in_selected,
        },
        "candidate_scope_distribution": dict(scope_counter),
        "floor_pass_rate": {
            "relevance": (rel_pass / total) if total else 0.0,
            "duration": (dur_pass / total) if total else 0.0,
        },
        "channel_diversity": {
            "unique_channels": len(set(selected_channels)),
            "max_per_channel": (
                max(Counter(selected_channels).values()) if selected_channels else 0
            ),
            "tier_distribution": dict(Counter(selected_tiers)),
        },
        "score_distribution": {
            "selected_avg_dimensions": selected_avg,
            "rejected_avg_dimensions": rejected_avg,
        },
        "bias_audit": {
            "selected_anti_bias_avg": mean(sel_anti_bias) if sel_anti_bias else 0.0,
            "rejected_anti_bias_avg": mean(rej_anti_bias) if rej_anti_bias else 0.0,
        },
    }


def aggregate_metrics(runs: list[list[dict[str, Any]]]) -> dict[str, Any]:
    """여러 run 을 합쳐 평균 지표 산출. 운영 모니터링용."""
    per_run = [compute_selection_metrics(r) for r in runs if r]
    if not per_run:
        return {"runs": 0}

    def avg(key_path: list[str]) -> float:
        vals: list[float] = []
        for m in per_run:
            v: Any = m
            for k in key_path:
                v = v.get(k) if isinstance(v, dict) else None
            if isinstance(v, (int, float)):
                vals.append(float(v))
        return mean(vals) if vals else 0.0

    return {
        "runs": len(per_run),
        "avg_single_product_ratio_at_k": avg(["single_product_ratio_at_k"]),
        "avg_floor_pass_relevance": avg(["floor_pass_rate", "relevance"]),
        "avg_floor_pass_duration": avg(["floor_pass_rate", "duration"]),
        "avg_unique_channels": avg(["channel_diversity", "unique_channels"]),
        "avg_selected_anti_bias": avg(["bias_audit", "selected_anti_bias_avg"]),
        "avg_rejected_anti_bias": avg(["bias_audit", "rejected_anti_bias_avg"]),
    }
