"""채널 편중 역가중치 (anti-mega) + 티어 분류.

anti_bias = 1 - min(1, log10(max(subs,1))/7)
  1k  → 0.57, 10k → 0.43, 100k → 0.28, 1M → 0.14, 10M+ → 0.
티어:
  mega  > 1,000,000
  large 100,000 ~ 1,000,000
  mid   10,000 ~ 100,000
  small 1,000 ~ 10,000
  micro < 1,000
"""
from __future__ import annotations

import math

from video_selection_agent.core.models import ChannelTier, VideoCandidate


def channel_anti_bias_score(video: VideoCandidate) -> float:
    subs = max(video.channel_subscriber_count, 1)
    return max(0.0, 1.0 - min(1.0, math.log10(subs) / 7.0))


def classify_channel_tier(subscriber_count: int) -> ChannelTier:
    s = max(subscriber_count, 0)
    if s > 1_000_000:
        return "mega"
    if s >= 100_000:
        return "large"
    if s >= 10_000:
        return "mid"
    if s >= 1_000:
        return "small"
    return "micro"
