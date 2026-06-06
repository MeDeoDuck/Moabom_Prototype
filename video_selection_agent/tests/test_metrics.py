"""metrics / strategy 단위 테스트 (v3 설계 PR1).

DB·네트워크 없이 순수 계산만 검증.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from video_selection_agent.core.models import (
    DiversityReport,
    ScoreBreakdown,
    SelectedVideo,
    SelectionDecision,
)
from video_selection_agent.metrics import compute_selection_metrics
from video_selection_agent import strategy as strat


def _selected(video_id: str, tier: str) -> SelectedVideo:
    return SelectedVideo(
        video_id=video_id,
        title=f"t-{video_id}",
        channel_name=f"c-{video_id}",
        tier=tier,
        rank=1,
        final_score=0.5,
        dimensions={},
        weighted_contributions={},
        rationale_short="",
        rationale_full="",
        selection_reasons=[],
    )


def _score(video_id: str, *, scope_label: int | None = None) -> ScoreBreakdown:
    sb = ScoreBreakdown(
        video_id=video_id,
        final_score=0.5,
        dimensions={},
        weighted_contributions={},
    )
    if scope_label is not None:
        sb.extras["scope_label"] = scope_label
    return sb


def _decision(selected, all_scores, trace=None) -> SelectionDecision:
    return SelectionDecision(
        run_id=uuid4(),
        product_id=1,
        mode="auto",
        selected=selected,
        candidates_preview=[],
        diversity_report=DiversityReport(0, {}, 0),
        candidate_count=len(all_scores),
        model_used="test",
        policy_version="test",
        trace=trace or [],
        all_scores=all_scores,
    )


def test_tier_share_sums_to_one():
    selected = [_selected("a", "mega"), _selected("b", "small"), _selected("c", "small")]
    scores = {v.video_id: _score(v.video_id) for v in selected}
    m = compute_selection_metrics(
        _decision(selected, scores), strategy="v1_weighted", latency_ms=10
    )
    assert m["k_selected"] == 3
    assert m["tier_counts"] == {"mega": 1, "large": 0, "mid": 0, "small": 2, "micro": 0}
    assert m["tier_share"]["small"] == pytest.approx(2 / 3, abs=1e-3)
    assert sum(m["tier_share"].values()) == pytest.approx(1.0, abs=1e-3)


def test_scope_leakage_counts_selected_label1():
    selected = [_selected("a", "mid"), _selected("b", "mid")]
    scores = {
        "a": _score("a", scope_label=1),  # 선정됐는데 비교영상 → leak
        "b": _score("b", scope_label=0),
        "c": _score("c", scope_label=1),  # 풀엔 있지만 미선정 → leak 아님
    }
    m = compute_selection_metrics(
        _decision(selected, scores), strategy="v1_weighted", latency_ms=5
    )
    assert m["scope_leakage"] == {"leaked_selected": 1, "flagged_in_pool": 2}


def test_fallback_and_relax_flags_from_trace():
    selected = [_selected("a", "mid")]
    scores = {"a": _score("a")}
    trace = [
        "relax_constraints: max_per_channel=4",
        "finalize_selection[fallback]: padded 2 rank=0 leftovers → total 3",
    ]
    m = compute_selection_metrics(
        _decision(selected, scores, trace), strategy="v1_weighted", latency_ms=1
    )
    assert m["fallback_used"] is True
    assert m["relaxed"] is True


def test_overlap_jaccard():
    selected = [_selected("a", "mid"), _selected("b", "mid")]
    scores = {v.video_id: _score(v.video_id) for v in selected}
    # 직전 {a, c} vs 이번 {a, b} → 교집합 1 / 합집합 3
    m = compute_selection_metrics(
        _decision(selected, scores),
        strategy="v1_weighted",
        latency_ms=1,
        prev_selected_ids=["a", "c"],
    )
    assert m["prev_overlap_jaccard"] == pytest.approx(1 / 3, abs=1e-3)


def test_overlap_none_when_no_prev():
    selected = [_selected("a", "mid")]
    scores = {"a": _score("a")}
    m = compute_selection_metrics(
        _decision(selected, scores), strategy="v1_weighted", latency_ms=1
    )
    assert m["prev_overlap_jaccard"] is None


def test_strategy_default_is_v1(monkeypatch):
    monkeypatch.delenv("SELECTION_STRATEGY", raising=False)
    eff, note = strat.resolve_strategy()
    assert eff == strat.V1_WEIGHTED
    assert note is None


def test_strategy_v3_active_after_pr4(monkeypatch):
    # PR4: v3_cluster 가 더 이상 강등되지 않고 그대로 해석됨
    monkeypatch.setenv("SELECTION_STRATEGY", "v3_cluster")
    eff, note = strat.resolve_strategy()
    assert eff == strat.V3_CLUSTER
    assert note is None


def test_strategy_unknown_falls_back(monkeypatch):
    monkeypatch.setenv("SELECTION_STRATEGY", "bogus")
    assert strat.requested_strategy() == strat.V1_WEIGHTED
