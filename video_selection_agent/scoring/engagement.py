"""(like/view + comment/view) → 풀 내 z-score → sigmoid 정규화.

절대값이 아닌 상대값이라 대형 채널의 total view 편중을 자연스럽게 완화.
"""
from __future__ import annotations

import math
import statistics

from video_selection_agent.core.models import VideoCandidate


def _rate(num: int, denom: int) -> float:
    if denom <= 0:
        return 0.0
    return num / denom


def _sigmoid(x: float) -> float:
    if x > 15:
        return 1.0
    if x < -15:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


def engagement_scores(candidates: list[VideoCandidate]) -> dict[str, float]:
    """풀 전체를 기준으로 z-score를 매긴 뒤 sigmoid로 0–1 압축."""
    if not candidates:
        return {}

    raw: dict[str, float] = {}
    for c in candidates:
        like_rate = _rate(c.like_count, c.view_count)
        comment_rate = _rate(c.comment_count, c.view_count)
        raw[c.video_id] = like_rate + comment_rate

    values = list(raw.values())
    mean = statistics.mean(values) if values else 0.0
    stdev = statistics.pstdev(values) if len(values) > 1 else 0.0

    if stdev == 0:
        return {vid: 0.5 for vid in raw}

    return {vid: _sigmoid((val - mean) / stdev) for vid, val in raw.items()}
