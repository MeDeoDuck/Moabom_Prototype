"""제품명·브랜드·카테고리 토큰 매칭 점수 (0–1).

title(×2) + description(×1) 에서 매칭된 토큰 수 / 기대 최대 매칭수.
difflib 부분 매칭으로 오탈자·조사 흡수.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from video_selection_agent.core.models import ProductContext, VideoCandidate


_TOKEN_RE = re.compile(r"[A-Za-z0-9가-힣]+")


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def _contains_fuzzy(tokens: list[str], target: str, threshold: float = 0.85) -> bool:
    """target이 tokens 안에 (부분 일치 포함) 존재하는지."""
    target_l = target.lower()
    if not target_l:
        return False
    for tok in tokens:
        if target_l in tok or tok in target_l:
            return True
        if SequenceMatcher(None, tok, target_l).ratio() >= threshold:
            return True
    return False


def _expand_terms(product: ProductContext) -> list[str]:
    """매칭 대상 용어: 제품명 토큰들 + 브랜드 + 카테고리 + keywords."""
    terms: list[str] = []
    terms.extend(_tokenize(product.name))
    if product.brand:
        terms.extend(_tokenize(product.brand))
    if product.category:
        terms.extend(_tokenize(product.category))
    for kw in product.keywords:
        terms.extend(_tokenize(kw))
    seen: set[str] = set()
    out: list[str] = []
    for t in terms:
        if len(t) >= 2 and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def relevance_score(video: VideoCandidate, product: ProductContext) -> float:
    """0–1 정규화된 매칭 점수."""
    terms = _expand_terms(product)
    if not terms:
        return 0.0

    title_tokens = _tokenize(video.title)
    desc_tokens = _tokenize(video.description)

    matched_title = sum(1 for t in terms if _contains_fuzzy(title_tokens, t))
    matched_desc = sum(1 for t in terms if _contains_fuzzy(desc_tokens, t))

    # 가중 매칭 / 최대 가능 점수
    weighted = matched_title * 2 + matched_desc
    max_possible = len(terms) * 3
    return min(1.0, weighted / max_possible) if max_possible else 0.0
