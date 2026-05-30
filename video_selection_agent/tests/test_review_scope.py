"""review_scope 휴리스틱 분류기 단위 테스트.

네트워크/DB/LLM 없이 결정적으로 통과해야 함.
"""
from __future__ import annotations

import pytest

from video_selection_agent.scoring.review_scope import (
    classify_review_scope,
    is_valid_scope,
)


@pytest.mark.parametrize(
    "title,expected",
    [
        # comparison
        ("iPhone 12 vs iPhone 13 비교 리뷰", "comparison"),
        ("Galaxy S24 vs S23 무엇이 달라졌나", "comparison"),
        ("아이폰 14 vs 15 차이점 정리", "comparison"),
        ("Pixel 8 versus Pixel 7a", "comparison"),
        # roundup
        ("2024년 무선이어폰 TOP 5 추천", "roundup"),
        ("Best 10 Android Phones in 2024", "roundup"),
        ("가성비 노트북 추천 5", "roundup"),
        ("스마트워치 베스트 리스트", "roundup"),
        # unboxing
        ("AirPods Pro 2 언박싱", "unboxing"),
        ("iPhone 15 Pro Max Unboxing", "unboxing"),
        ("갤럭시 S24 개봉기", "unboxing"),
        # news
        ("아이폰 16 출시 예정일 정리", "news"),
        ("Pixel 9 Leak: Everything we know", "news"),
        ("갤럭시 S25 루머 총정리", "news"),
        # single — 명확한 리뷰
        ("iPhone 15 Pro 한 달 사용 후기", "single"),
        ("갤럭시 S24 솔직 리뷰", "single"),
        ("MacBook Air M3 장기 사용 리뷰", "single"),
        ("AirPods Pro 2 Review: 6 Months Later", "single"),
        # unknown — 신호 없는 모호한 제목
        ("AirPods Pro 2", "unknown"),
        ("iPhone 15 Pro 영상", "unknown"),
    ],
)
def test_classify_review_scope_title_only(title: str, expected: str) -> None:
    result = classify_review_scope(title=title)
    assert result.scope == expected, (
        f"제목={title!r}, 기대={expected}, 실제={result.scope}, 신호={result.matched_signals}"
    )


def test_unboxing_with_review_signal_is_single() -> None:
    """언박싱+리뷰 동시 신호면 단일 리뷰로 보는 게 맞음."""
    result = classify_review_scope(title="iPhone 15 Pro 언박싱 + 솔직 리뷰")
    assert result.scope == "single"


def test_news_with_review_signal_is_single() -> None:
    """출시 소식 키워드라도 review 단어가 있으면 single로 처리."""
    result = classify_review_scope(title="iPhone 16 출시 소식 + 사전 리뷰")
    assert result.scope == "single"


def test_description_fallback_comparison() -> None:
    """제목엔 신호 없지만 설명에 비교 신호 있으면 comparison(저신뢰)."""
    result = classify_review_scope(
        title="아이폰 15",
        description="이번 영상에서는 14 Pro vs 15 Pro를 비교합니다.",
    )
    assert result.scope == "comparison"
    assert result.confidence < 0.7  # 저신뢰


def test_description_fallback_single() -> None:
    """제목 모호 + 설명에 사용기 신호 → single(저신뢰)."""
    result = classify_review_scope(
        title="아이폰 15",
        description="한 달 동안 매일 들고 다닌 실사용 후기를 정리했습니다.",
    )
    assert result.scope == "single"
    assert result.confidence < 0.7


def test_confidence_strong_for_explicit_comparison() -> None:
    result = classify_review_scope(title="iPhone 12 vs iPhone 13")
    assert result.confidence >= 0.8


def test_unknown_has_zero_confidence() -> None:
    result = classify_review_scope(title="아이폰 영상", description="")
    assert result.scope == "unknown"
    assert result.confidence == 0.0


def test_empty_inputs() -> None:
    result = classify_review_scope(title="", description="")
    assert result.scope == "unknown"
    assert result.confidence == 0.0


def test_matched_signals_recorded() -> None:
    result = classify_review_scope(title="iPhone vs Samsung")
    assert result.matched_signals, "매칭된 패턴이 기록되어야 함"
    assert any("vs" in s for s in result.matched_signals)


def test_is_valid_scope() -> None:
    for s in ("single", "comparison", "roundup", "news", "unboxing", "unknown"):
        assert is_valid_scope(s) is True
    assert is_valid_scope("bogus") is False
    assert is_valid_scope("") is False
