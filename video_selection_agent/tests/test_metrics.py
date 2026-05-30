"""evaluation.metrics 단위 테스트. 네트워크/DB 없이 결정적으로 통과."""
from __future__ import annotations

from video_selection_agent.evaluation.metrics import (
    KEY_FLOOR_DURATION,
    KEY_FLOOR_RELEVANCE,
    KEY_REVIEW_SCOPE,
    KEY_REVIEW_SCOPE_CONF,
    aggregate_metrics,
    compute_selection_metrics,
)


def _row(
    *,
    video_id: str,
    selected: bool,
    scope: str,
    rel_pass: bool = True,
    dur_pass: bool = True,
    relevance: float = 0.7,
    anti_bias: float = 0.5,
    rank: int = 1,
    tier: str = "large",
    channel_id: str = "ch_a",
) -> dict:
    return {
        "video_id": video_id,
        "selected": selected,
        "rank": rank,
        "final_score": 0.5,
        "tier": tier,
        "channel_id": channel_id,
        "dimensions_json": {
            "relevance": relevance,
            "engagement": 0.3,
            "recency": 0.2,
            "channel_anti_bias": anti_bias,
            "duration_fit": 1.0,
            "llm_topical_fit": 0.7,
            KEY_FLOOR_RELEVANCE: rel_pass,
            KEY_FLOOR_DURATION: dur_pass,
            KEY_REVIEW_SCOPE: scope,
            KEY_REVIEW_SCOPE_CONF: 0.8,
        },
    }


def test_empty_rows() -> None:
    m = compute_selection_metrics([])
    assert m["candidate_count"] == 0
    assert m["selected_count"] == 0
    assert m["single_product_ratio_at_k"] == 0.0
    assert m["floor_pass_rate"] == {"relevance": 0.0, "duration": 0.0}


def test_single_product_ratio_at_k() -> None:
    rows = [
        _row(video_id="a", selected=True, scope="single"),
        _row(video_id="b", selected=True, scope="single"),
        _row(video_id="c", selected=True, scope="comparison"),
        _row(video_id="d", selected=True, scope="unknown"),
        _row(video_id="e", selected=False, scope="single"),
    ]
    m = compute_selection_metrics(rows)
    assert m["selected_count"] == 4
    assert m["single_product_ratio_at_k"] == 0.5  # 4개 중 2개가 single
    assert m["selected_scope_distribution"]["single"] == 2
    assert m["selected_scope_distribution"]["comparison"] == 1
    assert m["selected_scope_distribution"]["unknown"] == 1


def test_floor_pass_rate() -> None:
    rows = [
        _row(video_id="a", selected=True, scope="single", rel_pass=True, dur_pass=True),
        _row(video_id="b", selected=True, scope="single", rel_pass=True, dur_pass=False),
        _row(video_id="c", selected=False, scope="comparison", rel_pass=False, dur_pass=True),
        _row(video_id="d", selected=False, scope="unknown", rel_pass=False, dur_pass=False),
    ]
    m = compute_selection_metrics(rows)
    assert m["floor_pass_rate"]["relevance"] == 0.5  # 4개 중 2개 pass
    assert m["floor_pass_rate"]["duration"] == 0.5


def test_candidate_scope_distribution() -> None:
    rows = [
        _row(video_id=f"v{i}", selected=False, scope="comparison") for i in range(3)
    ] + [
        _row(video_id=f"s{i}", selected=True, scope="single") for i in range(2)
    ]
    m = compute_selection_metrics(rows)
    assert m["candidate_scope_distribution"]["comparison"] == 3
    assert m["candidate_scope_distribution"]["single"] == 2


def test_channel_diversity() -> None:
    rows = [
        _row(video_id="a", selected=True, scope="single", channel_id="ch_a"),
        _row(video_id="b", selected=True, scope="single", channel_id="ch_a"),
        _row(video_id="c", selected=True, scope="single", channel_id="ch_b"),
        _row(video_id="d", selected=False, scope="single", channel_id="ch_c"),
    ]
    m = compute_selection_metrics(rows)
    assert m["channel_diversity"]["unique_channels"] == 2  # selected만
    assert m["channel_diversity"]["max_per_channel"] == 2


def test_bias_audit_separates_selected_rejected() -> None:
    rows = [
        _row(video_id="a", selected=True, scope="single", anti_bias=0.2),
        _row(video_id="b", selected=True, scope="single", anti_bias=0.4),
        _row(video_id="c", selected=False, scope="single", anti_bias=0.8),
    ]
    m = compute_selection_metrics(rows)
    assert abs(m["bias_audit"]["selected_anti_bias_avg"] - 0.3) < 1e-9
    assert m["bias_audit"]["rejected_anti_bias_avg"] == 0.8


def test_score_distribution_real_dimensions_only() -> None:
    """underscore-prefix 키는 score_distribution 계산에서 제외되어야 함."""
    rows = [
        _row(video_id="a", selected=True, scope="single", relevance=0.9),
        _row(video_id="b", selected=False, scope="single", relevance=0.1),
    ]
    m = compute_selection_metrics(rows)
    sel_avg = m["score_distribution"]["selected_avg_dimensions"]
    rej_avg = m["score_distribution"]["rejected_avg_dimensions"]
    assert sel_avg["relevance"] == 0.9
    assert rej_avg["relevance"] == 0.1
    # underscore 키가 평균에 새지 않았는지
    assert "_floor_pass_relevance" not in sel_avg
    assert "_review_scope" not in sel_avg


def test_aggregate_metrics_averages() -> None:
    run_a = [
        _row(video_id="a", selected=True, scope="single"),
        _row(video_id="b", selected=True, scope="comparison"),
    ]
    run_b = [
        _row(video_id="c", selected=True, scope="single"),
        _row(video_id="d", selected=True, scope="single"),
    ]
    agg = aggregate_metrics([run_a, run_b])
    assert agg["runs"] == 2
    # run_a single ratio = 0.5, run_b = 1.0 → avg 0.75
    assert abs(agg["avg_single_product_ratio_at_k"] - 0.75) < 1e-9


def test_aggregate_empty() -> None:
    assert aggregate_metrics([]) == {"runs": 0}
    assert aggregate_metrics([[]]) == {"runs": 0}
