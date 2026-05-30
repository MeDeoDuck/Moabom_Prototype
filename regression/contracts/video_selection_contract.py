"""영상 선정 결과 (`video_selection_scores.dimensions_json`) 계약 검증기.

PR #1 관찰 단계의 계약:
- 각 row 의 `dimensions_json` 에 6개 실제 차원이 존재한다.
- PR #1 관찰 필드 4종이 존재하고 값 범위가 맞다:
    `_floor_pass_relevance` (bool)
    `_floor_pass_duration`  (bool)
    `_review_scope`         (단일/비교/랭킹/뉴스/언박싱/unknown)
    `_review_scope_confidence` (0.0~1.0)

본 검증기는 단일 row 또는 row list 둘 다 받으며, list 검증은 모든 row 가 통과해야
status="ok". 한 row 라도 위반이면 위반 모두를 누적한 뒤 `violated`.
"""
from __future__ import annotations

from typing import Any

from regression.contracts.result import ContractResult

REPORT_KIND = "video_selection"

REQUIRED_REAL_DIMENSIONS = (
    "relevance",
    "engagement",
    "recency",
    "channel_anti_bias",
    "duration_fit",
    "llm_topical_fit",
)

REQUIRED_JUDGMENT_KEYS = (
    "_floor_pass_relevance",
    "_floor_pass_duration",
    "_review_scope",
    "_review_scope_confidence",
)

VALID_SCOPES = ("single", "comparison", "roundup", "news", "unboxing", "unknown")


def _check_row(result: ContractResult, idx: int, row: dict[str, Any]) -> None:
    prefix = f"row[{idx}]"

    dims = row.get("dimensions_json")
    if dims is None:
        dims = row.get("dimensions")
    if not isinstance(dims, dict):
        result.add(
            "VS.MISSING_DIMENSIONS",
            f"{prefix} dimensions_json 이 dict 가 아닙니다 (got {type(dims).__name__}).",
        )
        return

    # 실제 차원 6개 존재 — 백워드 호환
    for k in REQUIRED_REAL_DIMENSIONS:
        if k not in dims:
            result.add(
                "VS.MISSING_REAL_DIM",
                f"{prefix} 실제 차원 키 누락: {k}",
            )
        elif not isinstance(dims[k], (int, float)):
            result.add(
                "VS.REAL_DIM_TYPE",
                f"{prefix} '{k}' 값이 숫자가 아님 (got {type(dims[k]).__name__}).",
            )

    # PR #1 관찰 필드 존재
    for k in REQUIRED_JUDGMENT_KEYS:
        if k not in dims:
            result.add(
                "VS.MISSING_JUDGMENT_KEY",
                f"{prefix} 관찰 필드 키 누락: {k}",
            )

    # 타입·값 범위 검증
    rel_pass = dims.get("_floor_pass_relevance")
    if rel_pass is not None and not isinstance(rel_pass, bool):
        result.add(
            "VS.FLOOR_PASS_TYPE",
            f"{prefix} _floor_pass_relevance 가 bool 이 아님 (got {type(rel_pass).__name__}).",
        )
    dur_pass = dims.get("_floor_pass_duration")
    if dur_pass is not None and not isinstance(dur_pass, bool):
        result.add(
            "VS.FLOOR_PASS_TYPE",
            f"{prefix} _floor_pass_duration 가 bool 이 아님 (got {type(dur_pass).__name__}).",
        )

    scope = dims.get("_review_scope")
    if scope is not None and scope not in VALID_SCOPES:
        result.add(
            "VS.SCOPE_ENUM",
            f"{prefix} _review_scope 값 '{scope}' 가 enum 범위 밖. 허용: {VALID_SCOPES}",
        )

    conf = dims.get("_review_scope_confidence")
    if conf is not None:
        if not isinstance(conf, (int, float)):
            result.add(
                "VS.CONF_TYPE",
                f"{prefix} _review_scope_confidence 가 숫자가 아님 (got {type(conf).__name__}).",
            )
        elif not (0.0 <= float(conf) <= 1.0):
            result.add(
                "VS.CONF_RANGE",
                f"{prefix} _review_scope_confidence 값 {conf} 가 [0.0, 1.0] 밖.",
            )


def validate_video_selection(rows: Any) -> ContractResult:
    """`video_selection_scores` 행 list (또는 단일 dict) 의 계약 검증."""
    result = ContractResult(report_kind=REPORT_KIND)

    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        result.status = "generation_failed"
        result.add(
            "VS.NOT_LIST",
            f"입력이 list/dict 이 아닙니다 (got {type(rows).__name__}).",
            severity="warning",
        )
        return result

    if not rows:
        result.status = "generation_failed"
        result.add(
            "VS.EMPTY",
            "score row list 가 비어 있습니다.",
            severity="warning",
        )
        return result

    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            result.add(
                "VS.ROW_NOT_DICT",
                f"row[{i}] 가 dict 가 아님 (got {type(row).__name__}).",
            )
            continue
        _check_row(result, i, row)

    return result.finalize()
