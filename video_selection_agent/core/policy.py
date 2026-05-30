"""선정 정책 설정.

k 상한/하한, 채널 상한, 티어 쿼터, 스코어링 가중치를 한곳에 모음.
실험 시 이 파일만 교체해 다른 프로필로 실행 가능.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


POLICY_VERSION = "v1.1.0-observability"


@dataclass
class ScoringWeights:
    """정량 스코어 가중치 (합은 1.0)."""
    relevance: float = 0.30
    engagement: float = 0.15
    recency: float = 0.10
    channel_anti_bias: float = 0.20
    duration_fit: float = 0.10
    llm_topical_fit: float = 0.15

    def as_dict(self) -> dict[str, float]:
        return {
            "relevance": self.relevance,
            "engagement": self.engagement,
            "recency": self.recency,
            "channel_anti_bias": self.channel_anti_bias,
            "duration_fit": self.duration_fit,
            "llm_topical_fit": self.llm_topical_fit,
        }


@dataclass(frozen=True)
class FloorThresholds:
    """후보 품질 하한 (관찰용. PR #1에서는 미적용 — 통과 여부만 기록)."""
    relevance: float = 0.25
    duration_seconds: int = 120


@dataclass
class SelectionPolicyConfig:
    """FR-005/FR-022 정책 상수 묶음."""
    k_min: int = 3
    k_max: int = 10
    candidate_pool_size: int = 30
    max_per_channel: int = 3
    mega_tier_ratio_cap: float = 0.40
    small_or_below_min_ratio: float = 0.20
    weights: ScoringWeights = field(default_factory=ScoringWeights)
    floors: FloorThresholds = field(default_factory=FloorThresholds)
    policy_version: str = POLICY_VERSION

    def clamp_k(self, k: int) -> int:
        return max(self.k_min, min(self.k_max, k))
