"""PR4 v3 활성화 — apply_v3_selection 단위 테스트 (FastAPI 없이)."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from video_selection_agent.activation import apply_v3_selection, shadow_candidates
from video_selection_agent.core.models import (
    DiversityReport,
    ScoreBreakdown,
    SelectedVideo,
    SelectionDecision,
    VideoCandidate,
)


def _cand(vid):
    return VideoCandidate(
        video_id=vid, title=f"t-{vid}", description="d", channel_id=f"ch-{vid}",
        channel_name=f"c-{vid}", published_at=datetime.now(timezone.utc),
        duration_seconds=600, view_count=100, like_count=10, comment_count=5,
        channel_subscriber_count=1000, thumbnail_url="", source_query="q",
    )


def _score(vid, tier="mid", scope=0):
    sb = ScoreBreakdown(video_id=vid, final_score=0.5, dimensions={"relevance": 0.5},
                        weighted_contributions={}, rank=1, tier=tier)
    if scope:
        sb.extras["scope_label"] = scope
    return sb


def _decision(ids, v1_selected):
    cands = [_cand(v) for v in ids]
    scores = {v: _score(v) for v in ids}
    selected = [SelectedVideo(video_id=v, title=f"t-{v}", channel_name=f"c-{v}", tier="mid",
                              rank=i + 1, final_score=0.5, dimensions={}, weighted_contributions={},
                              rationale_short="v1", rationale_full="v1", selection_reasons=[])
                for i, v in enumerate(v1_selected)]
    return SelectionDecision(
        run_id=uuid4(), product_id=1, mode="auto", selected=selected,
        candidates_preview=cands, diversity_report=DiversityReport(0, {}, 0),
        candidate_count=len(cands), model_used="t", policy_version="t",
        trace=[], all_scores=scores,
    )


def _shadow(detail_ids, *, ok=True, fallback=False, error=False):
    fs = {"fallback": fallback, "detail": [
        {"video_id": v, "reason": f"r-{v}", "cluster_id": i, "score": 1.0}
        for i, v in enumerate(detail_ids)]}
    if error:
        fs = {"error": "boom"}
    return {"ok": ok, "final_select": fs}


def test_apply_replaces_selection():
    d = _decision(["a", "b", "c", "d", "e"], v1_selected=["a", "b", "c"])
    ok = apply_v3_selection(d, _shadow(["c", "d", "e"]))
    assert ok is True
    assert [v.video_id for v in d.selected] == ["c", "d", "e"]  # v3 순서/구성으로 교체
    assert d.selected[0].rationale_short == "r-c"               # v3 이유 반영
    assert d.all_scores["c"].rank == 1                          # score 객체도 갱신


def test_apply_rejects_fallback():
    d = _decision(["a", "b", "c"], v1_selected=["a", "b", "c"])
    assert apply_v3_selection(d, _shadow(["a", "b", "c"], fallback=True)) is False
    assert [v.video_id for v in d.selected] == ["a", "b", "c"]  # v1 유지


def test_apply_rejects_not_ok_or_error():
    d = _decision(["a", "b", "c"], v1_selected=["a", "b"])
    assert apply_v3_selection(d, _shadow(["a", "b", "c"], ok=False)) is False
    assert apply_v3_selection(d, _shadow(["a", "b", "c"], error=True)) is False


def test_apply_rejects_under_kmin():
    d = _decision(["a", "b", "c"], v1_selected=["a", "b"])
    assert apply_v3_selection(d, _shadow(["a", "b"])) is False  # detail 2 < k_min 3


def test_apply_rejects_unknown_video():
    d = _decision(["a", "b", "c"], v1_selected=["a", "b"])
    # detail 에 후보에 없는 id 포함 → 데이터 불일치 → v1 유지
    assert apply_v3_selection(d, _shadow(["a", "b", "ZZZ"])) is False
    assert [v.video_id for v in d.selected] == ["a", "b"]


def test_shadow_candidates_carries_tier_and_scope():
    cands = [_cand("a"), _cand("b")]
    scores = {"a": _score("a", tier="mega"), "b": _score("b", tier="small", scope=1)}
    d = SelectionDecision(run_id=uuid4(), product_id=1, mode="auto", selected=[],
                          candidates_preview=cands, diversity_report=DiversityReport(0, {}, 0),
                          candidate_count=2, model_used="t", policy_version="t",
                          trace=[], all_scores=scores)
    out = {c["video_id"]: c for c in shadow_candidates(d)}
    assert out["a"]["tier"] == "mega" and out["a"]["scope_label"] == 0
    assert out["b"]["tier"] == "small" and out["b"]["scope_label"] == 1
