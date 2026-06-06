"""선정 결과 계측 (v3 설계 §7 측정 지표).

라벨 없이 운영 로그만으로 strategy 별 선정 품질을 비교하기 위한 지표를
`SelectionDecision` + trace + 직전 run 으로부터 계산한다. PR1 은 v1_weighted
baseline 을 이 형식으로 저장해, PR2~3 의 v3 shadow 결과와 같은 축으로 비교한다.

순수 계산 + (overlap 용) 직전 선정 id 만 외부에서 주입 — DB 접근 없음.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from video_selection_agent.core.models import SelectionDecision

# core.models.ChannelTier 와 동일 순서. 누락 tier 도 0 으로 채워 schema 안정화.
_TIERS = ("mega", "large", "mid", "small", "micro")

_FALLBACK_MARKER = "finalize_selection[fallback]"
_RELAX_MARKER = "relax_constraints"


def _tier_distribution(decision: "SelectionDecision") -> dict[str, int]:
    counts = {t: 0 for t in _TIERS}
    for sv in decision.selected:
        tier = getattr(sv, "tier", None)
        if tier in counts:
            counts[tier] += 1
    return counts


def _tier_share(counts: dict[str, int], total: int) -> dict[str, float]:
    if total <= 0:
        return {t: 0.0 for t in _TIERS}
    return {t: round(counts[t] / total, 4) for t in _TIERS}


def _scope_leakage(decision: "SelectionDecision") -> dict[str, int]:
    """선정된 영상 중 scope 분류기가 비교/랭킹(label=1) 으로 본 수.

    scope_filter 노드가 ScoreBreakdown.extras 에 남긴 scope_label 사용.
    목표는 leaked_selected == 0 (설계 §7).
    """
    scores = getattr(decision, "all_scores", {}) or {}
    selected_ids = {sv.video_id for sv in decision.selected}
    leaked_selected = 0
    flagged_pool = 0
    for vid, sb in scores.items():
        label = (getattr(sb, "extras", {}) or {}).get("scope_label")
        if label == 1:
            flagged_pool += 1
            if vid in selected_ids:
                leaked_selected += 1
    return {"leaked_selected": leaked_selected, "flagged_in_pool": flagged_pool}


def _jaccard(a: set[str], b: set[str]) -> float | None:
    if not a and not b:
        return None
    union = a | b
    if not union:
        return None
    return round(len(a & b) / len(union), 4)


def compute_selection_metrics(
    decision: "SelectionDecision",
    *,
    strategy: str,
    latency_ms: int,
    prev_selected_ids: list[str] | None = None,
    downgrade_note: str | None = None,
) -> dict:
    """SelectionDecision → 측정 지표 dict (metrics_json 저장용).

    prev_selected_ids: 같은 제품 직전 run 의 선정 video_id (overlap/Jaccard 용).
      없으면 overlap 은 null.
    """
    selected_ids = [sv.video_id for sv in decision.selected]
    tier_counts = _tier_distribution(decision)
    trace = list(getattr(decision, "trace", []) or [])
    fallback_used = any(_FALLBACK_MARKER in line for line in trace)
    relaxed = any(_RELAX_MARKER in line for line in trace)

    overlap = None
    if prev_selected_ids is not None:
        overlap = _jaccard(set(selected_ids), set(prev_selected_ids))

    return {
        "strategy": strategy,
        "latency_ms": latency_ms,
        "k_selected": len(selected_ids),
        "candidate_count": decision.candidate_count,
        "tier_counts": tier_counts,
        "tier_share": _tier_share(tier_counts, len(selected_ids)),
        "scope_leakage": _scope_leakage(decision),
        "fallback_used": fallback_used,
        "relaxed": relaxed,
        "prev_overlap_jaccard": overlap,
        # v3 fine 단계(PR3)에서 자막 fetch 가 붙으면 채워진다. v1 은 자막 fetch 없음.
        "transcript_fetch": {"attempted": 0, "succeeded": 0, "failed": 0},
        "downgrade_note": downgrade_note,
    }
