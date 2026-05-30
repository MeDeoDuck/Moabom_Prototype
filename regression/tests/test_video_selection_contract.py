"""video_selection 계약 + golden 픽스처 회귀 테스트.

오프라인 (DB·LLM·네트워크 없음)에서 통과한다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from regression.contracts.video_selection_contract import (
    REPORT_KIND,
    VALID_SCOPES,
    validate_video_selection,
)

GOLDEN = Path(__file__).resolve().parents[1] / "golden" / "video_selection"


def _load(name: str) -> list[dict]:
    return json.loads((GOLDEN / name).read_text(encoding="utf-8"))


def test_valid_sample_passes() -> None:
    result = validate_video_selection(_load("valid_sample.json"))
    assert result.status == "ok", result.detail()
    assert result.report_kind == REPORT_KIND
    assert result.is_ok is True


def test_broken_sample_violates() -> None:
    result = validate_video_selection(_load("broken_sample.json"))
    assert result.status == "violated", result.detail()
    codes = {v.code for v in result.errors}
    # broken row 1: scope enum 위반 + confidence range + bool 타입
    assert "VS.SCOPE_ENUM" in codes
    assert "VS.CONF_RANGE" in codes
    assert "VS.FLOOR_PASS_TYPE" in codes
    # broken row 2: judgment 키 4개 모두 누락
    assert "VS.MISSING_JUDGMENT_KEY" in codes


def test_empty_list_is_generation_failed() -> None:
    result = validate_video_selection([])
    assert result.status == "generation_failed"
    assert result.is_ok is True  # 게이트 하드 실패 아님


def test_non_list_input() -> None:
    result = validate_video_selection("not a list")  # type: ignore[arg-type]
    assert result.status == "generation_failed"


def test_single_dict_treated_as_one_row() -> None:
    row = _load("valid_sample.json")[0]
    result = validate_video_selection(row)
    assert result.status == "ok", result.detail()


def test_valid_scopes_contract() -> None:
    """VALID_SCOPES 가 review_scope 모듈과 일치해야 한다."""
    from video_selection_agent.scoring.review_scope import _VALID_SCOPES as agent_scopes
    assert set(VALID_SCOPES) == set(agent_scopes)


def test_real_dimension_missing_violates() -> None:
    """실제 차원이 빠지면 백워드 호환 위반."""
    row = {
        "video_id": "x",
        "selected": True,
        "dimensions_json": {
            # relevance 빠짐
            "engagement": 0.5,
            "recency": 0.3,
            "channel_anti_bias": 0.2,
            "duration_fit": 0.9,
            "llm_topical_fit": 0.7,
            "_floor_pass_relevance": True,
            "_floor_pass_duration": True,
            "_review_scope": "single",
            "_review_scope_confidence": 0.8,
        },
    }
    result = validate_video_selection([row])
    assert result.status == "violated"
    codes = {v.code for v in result.errors}
    assert "VS.MISSING_REAL_DIM" in codes


@pytest.mark.parametrize("scope", VALID_SCOPES)
def test_each_valid_scope_passes(scope: str) -> None:
    row = {
        "video_id": "x",
        "selected": True,
        "dimensions_json": {
            "relevance": 0.5,
            "engagement": 0.5,
            "recency": 0.5,
            "channel_anti_bias": 0.5,
            "duration_fit": 0.5,
            "llm_topical_fit": 0.5,
            "_floor_pass_relevance": True,
            "_floor_pass_duration": True,
            "_review_scope": scope,
            "_review_scope_confidence": 0.5,
        },
    }
    result = validate_video_selection([row])
    assert result.status == "ok", result.detail()
