"""최신성 점수: exp(-days/180). 0(오래됨) ~ 1(방금)."""
from __future__ import annotations

import math
from datetime import datetime, timezone

from video_selection_agent.core.models import VideoCandidate


def recency_score(video: VideoCandidate, now: datetime | None = None) -> float:
    ref = now or datetime.now(timezone.utc)
    published = video.published_at
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    days = max(0.0, (ref - published).total_seconds() / 86400.0)
    return math.exp(-days / 180.0)
