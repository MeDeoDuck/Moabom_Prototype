"""영상 길이 적합성 점수 (0–1).

  duration < 180s       → 0 (Shorts/너무 짧음)
  180s ≤ d < 240s       → 0→1 선형 상승
  240s ≤ d ≤ 1500s      → 1 (4~25분 스윗스팟)
  1500s < d ≤ 3600s     → 1→0 선형 하강
  d > 3600s             → 0 (너무 김)
"""
from __future__ import annotations

from video_selection_agent.core.models import VideoCandidate


def duration_fit_score(video: VideoCandidate) -> float:
    d = video.duration_seconds
    if d <= 180:
        return 0.0
    if d < 240:
        return (d - 180) / 60.0
    if d <= 1500:
        return 1.0
    if d <= 3600:
        return max(0.0, (3600 - d) / (3600 - 1500))
    return 0.0
