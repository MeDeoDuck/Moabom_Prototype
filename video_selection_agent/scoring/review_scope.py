"""제목·설명 기반 리뷰 스코프 휴리스틱 분류기.

PR #1 관찰 단계: 결정적 분류만. 다음 PR에서 hard filter / LLM 분류 검증에 활용.

분류 라벨:
- `single`     : 단일 제품 심층 리뷰
- `comparison` : 둘 이상 제품 비교 (`vs`, `비교`, `대결`)
- `roundup`    : 베스트/순위/추천 리스트 (`TOP N`, `BEST`, `순위`)
- `news`       : 출시·루머·발표 (실리뷰 아님)
- `unboxing`   : 언박싱 위주 (사용기 신호 없음)
- `unknown`    : 신호 부족

LLM 미사용. 회귀 안정성 위해 키워드 매칭만.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

ReviewScope = Literal["single", "comparison", "roundup", "news", "unboxing", "unknown"]

_VALID_SCOPES: tuple[ReviewScope, ...] = (
    "single", "comparison", "roundup", "news", "unboxing", "unknown",
)


# 단어 경계로 잡아야 오탐 적음 (예: "versus"의 "vs" vs "Bose QC ULTRA")
_COMPARISON_PATTERNS = [
    re.compile(r"\bvs\.?\b", re.IGNORECASE),
    re.compile(r"\bversus\b", re.IGNORECASE),
    re.compile(r"비교"),
    re.compile(r"대결"),
    re.compile(r"차이점"),
    re.compile(r"대비"),
]

_ROUNDUP_PATTERNS = [
    re.compile(r"\btop\s*\d+\b", re.IGNORECASE),
    re.compile(r"\bbest\s*\d+\b", re.IGNORECASE),
    re.compile(r"추천\s*\d"),       # "추천 5", "추천5"
    re.compile(r"\d+\s*추천"),      # "5 추천"
    re.compile(r"순위"),
    re.compile(r"베스트"),
    re.compile(r"랭킹"),
    re.compile(r"라인업\s*정리"),
]

_NEWS_PATTERNS = [
    re.compile(r"출시\s*(예정|일|소식|확정|임박)"),
    re.compile(r"\bleak\b", re.IGNORECASE),
    re.compile(r"루머"),
    re.compile(r"\brumor\b", re.IGNORECASE),
    re.compile(r"공개\s*(예정|임박)"),
    re.compile(r"\bteaser\b", re.IGNORECASE),
    re.compile(r"티저"),
    re.compile(r"발표"),
]

_UNBOXING_PATTERNS = [
    re.compile(r"\bunboxing\b", re.IGNORECASE),
    re.compile(r"언박싱"),
    re.compile(r"개봉(기|식)?"),
]

_SINGLE_REVIEW_PATTERNS = [
    re.compile(r"\breview\b", re.IGNORECASE),
    re.compile(r"리뷰"),
    re.compile(r"사용기"),
    re.compile(r"한\s*달|한달|1\s*개월"),
    re.compile(r"\d+\s*주(일|간)?\s*(사용|써)"),
    re.compile(r"장기\s*사용|장기사용"),
    re.compile(r"솔직(한)?\s*후기|솔직후기"),
    re.compile(r"실\s*사용|실사용"),
    re.compile(r"구매\s*후기|구매후기"),
    re.compile(r"\blong[\s-]?term\b", re.IGNORECASE),
]


@dataclass(frozen=True)
class ReviewScopeResult:
    scope: ReviewScope
    confidence: float          # 0.0~1.0
    matched_signals: list[str] # 디버그용 — 어떤 패턴이 잡혔는지


def _match_any(patterns: list[re.Pattern[str]], text: str) -> list[str]:
    """매칭된 패턴 source 리스트 반환 (디버깅용)."""
    hits: list[str] = []
    for p in patterns:
        if p.search(text):
            hits.append(p.pattern)
    return hits


def classify_review_scope(title: str, description: str = "") -> ReviewScopeResult:
    """제목 + 설명으로 review scope 분류.

    우선순위: comparison > roundup > unboxing(리뷰 신호 없을 때) >
              news(리뷰 신호 없을 때) > single > unknown.

    설명은 제목의 보조 — 제목에서 신호 없으면 설명에서 한 번 더 확인.
    """
    title = title or ""
    description = description or ""
    title_lower = title  # 패턴이 re.IGNORECASE라 lower 불필요
    full_text = f"{title}\n{description}"

    comparison_hits = _match_any(_COMPARISON_PATTERNS, title_lower)
    roundup_hits = _match_any(_ROUNDUP_PATTERNS, title_lower)
    unboxing_hits = _match_any(_UNBOXING_PATTERNS, title_lower)
    news_hits = _match_any(_NEWS_PATTERNS, title_lower)
    single_hits = _match_any(_SINGLE_REVIEW_PATTERNS, title_lower)

    # 제목에 비교 신호 → 거의 확실 comparison
    if comparison_hits:
        return ReviewScopeResult(
            scope="comparison",
            confidence=0.9,
            matched_signals=[f"title:{p}" for p in comparison_hits],
        )

    # 제목에 roundup 신호 → 거의 확실 roundup
    if roundup_hits:
        return ReviewScopeResult(
            scope="roundup",
            confidence=0.9,
            matched_signals=[f"title:{p}" for p in roundup_hits],
        )

    # 제목에 unboxing 신호 + 단일 리뷰 신호 없음 → unboxing
    if unboxing_hits and not single_hits:
        return ReviewScopeResult(
            scope="unboxing",
            confidence=0.8,
            matched_signals=[f"title:{p}" for p in unboxing_hits],
        )

    # 제목에 news 신호 + 단일 리뷰 신호 없음 → news
    if news_hits and not single_hits:
        return ReviewScopeResult(
            scope="news",
            confidence=0.75,
            matched_signals=[f"title:{p}" for p in news_hits],
        )

    # 제목에 단일 리뷰 신호 → single (높은 신뢰)
    if single_hits:
        return ReviewScopeResult(
            scope="single",
            confidence=0.8,
            matched_signals=[f"title:{p}" for p in single_hits],
        )

    # 제목에서 신호 없음 → 설명에서 한 번 더
    desc_comparison = _match_any(_COMPARISON_PATTERNS, description)
    if desc_comparison:
        return ReviewScopeResult(
            scope="comparison",
            confidence=0.6,
            matched_signals=[f"desc:{p}" for p in desc_comparison],
        )

    desc_single = _match_any(_SINGLE_REVIEW_PATTERNS, description)
    if desc_single:
        return ReviewScopeResult(
            scope="single",
            confidence=0.5,
            matched_signals=[f"desc:{p}" for p in desc_single],
        )

    return ReviewScopeResult(scope="unknown", confidence=0.0, matched_signals=[])


def is_valid_scope(value: str) -> bool:
    """저장된 값이 enum 범위 안인지 검증 (regression contract용)."""
    return value in _VALID_SCOPES
