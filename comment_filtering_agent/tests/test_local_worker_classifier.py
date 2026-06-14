"""LocalWorkerClassifier 어댑터 유닛테스트.

핵심 검증 (통합의 마지막 1마일):
  - 워커 raw 응답 → models.ClassificationResult 변환
  - label 이 CommentLabel **enum** (str 아님) → label.value 동작
  - agent.decide 가 크래시 없이 통과 (재현 str-label 은 여기서 깨졌음)
  - VR + features>=2 → ANALYZE 승격
  - 워커 실패/개수불일치 → api 폴백
  - legacy/unknown 라벨 → VR 흡수

pytest 또는 `python test_local_worker_classifier.py` 양쪽으로 실행 가능.
requests 외 외부 의존 없음 (api_fallback 은 스텁 주입).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from unittest.mock import patch

from comment_filtering_agent.classifiers import local_worker_classifier as lwc
from comment_filtering_agent.classifiers.local_worker_classifier import (
    LocalWorkerClassifier,
)
from comment_filtering_agent.classifiers.models import (
    ClassificationResult,
    CommentLabel,
)
from comment_filtering_agent.core.agent import AgentDecisionEngine
from comment_filtering_agent.core.models import AgentAction
from comment_filtering_agent.filters.models import FilterResult


def _filter_pass() -> FilterResult:
    return FilterResult(
        index=0,
        original_text="x",
        cleaned_text="x",
        is_passed=True,
        reject_reason_codes=[],
        matched_rules=[],
        metadata={},
    )


def _mock_worker(results):
    """_post_classify 를 고정 results 반환으로 패치."""
    return patch.object(lwc, "_post_classify", lambda comments, **kw: results)


class _FakeApi:
    """api_fallback 스텁 — 호출되면 인자를 기록하고 VR 결과 반환."""

    def __init__(self):
        self.called_with = None

    def classify_batch(self, comments, start_index=0):
        self.called_with = (list(comments), start_index)
        return [
            ClassificationResult(
                index=start_index + i,
                original_comment=c,
                label=CommentLabel.VIDEO_REACTION,
                confidence=0.5,
                rationale_short="fake api",
                needs_recheck=True,
                mentioned_product_features=[],
                is_product_related=False,
            )
            for i, c in enumerate(comments)
        ]


def test_enum_conversion_and_label_value():
    """워커 str label → CommentLabel enum + label.value 동작."""
    clf = LocalWorkerClassifier(api_fallback=_FakeApi())
    with _mock_worker([{"label": "PRODUCT_OPINION", "confidence": 0.97}]):
        results = clf.classify_batch(["발열 심하네요"])
    r = results[0]
    assert isinstance(r, ClassificationResult)
    assert r.label is CommentLabel.PRODUCT_OPINION  # enum, not str
    assert r.label.value == "PRODUCT_OPINION"       # 재현 str-label 은 여기서 크래시
    assert r.is_product_related is True
    print("✓ enum 변환 + label.value")


def test_agent_decide_passes_without_crash():
    """변환 결과가 agent.decide 를 크래시 없이 통과."""
    clf = LocalWorkerClassifier(api_fallback=_FakeApi())
    agent = AgentDecisionEngine()
    with _mock_worker([{"label": "PRODUCT_OPINION", "confidence": 0.95}]):
        results = clf.classify_batch(["배터리 오래가요"])
    decision = agent.decide(
        comment="배터리 오래가요",
        filter_result=_filter_pass(),
        classification_result=results[0],
        index=0,
    )
    assert decision.final_action == AgentAction.ANALYZE
    print("✓ agent.decide PO → ANALYZE")


def test_vr_promotion_with_features():
    """VR + 제품 키워드>=2 → agent ANALYZE 승격."""
    clf = LocalWorkerClassifier(api_fallback=_FakeApi())
    agent = AgentDecisionEngine()
    text = "발열도 심하고 배터리도 별로네요"  # 발열, 배터리 → 2개
    with _mock_worker([{"label": "VIDEO_REACTION", "confidence": 0.9}]):
        results = clf.classify_batch([text])
    r = results[0]
    assert r.label is CommentLabel.VIDEO_REACTION
    assert len(r.mentioned_product_features) >= 2
    decision = agent.decide(
        comment=text,
        filter_result=_filter_pass(),
        classification_result=r,
        index=0,
    )
    assert decision.final_action == AgentAction.ANALYZE
    print(f"✓ VR features={r.mentioned_product_features} → ANALYZE 승격")


def test_vr_no_features_excluded():
    """VR + 키워드 0 → EXCLUDE."""
    clf = LocalWorkerClassifier(api_fallback=_FakeApi())
    agent = AgentDecisionEngine()
    text = "ㅋㅋㅋ 영상 잘 봤어요"
    with _mock_worker([{"label": "VIDEO_REACTION", "confidence": 0.9}]):
        results = clf.classify_batch([text])
    r = results[0]
    assert r.mentioned_product_features == []
    decision = agent.decide(
        comment=text,
        filter_result=_filter_pass(),
        classification_result=r,
        index=0,
    )
    assert decision.final_action == AgentAction.EXCLUDE
    print("✓ VR no-features → EXCLUDE")


def test_legacy_label_remap():
    """워커가 (혹시) CHATTER/OFF_TOPIC/unknown 반환해도 VR 로 흡수."""
    clf = LocalWorkerClassifier(api_fallback=_FakeApi())
    with _mock_worker(
        [
            {"label": "CHATTER", "confidence": 0.9},
            {"label": "OFF_TOPIC", "confidence": 0.8},
            {"label": "어쩌구", "confidence": 0.7},  # 알 수 없는 라벨도 VR
        ]
    ):
        results = clf.classify_batch(["a", "b", "c"])
    assert all(r.label is CommentLabel.VIDEO_REACTION for r in results)
    print("✓ legacy/unknown 라벨 → VR 흡수")


def test_needs_recheck_threshold():
    """conf < 0.85 → needs_recheck True."""
    clf = LocalWorkerClassifier(api_fallback=_FakeApi())
    with _mock_worker(
        [
            {"label": "QUESTION", "confidence": 0.99},
            {"label": "QUESTION", "confidence": 0.70},
        ]
    ):
        results = clf.classify_batch(["살 만한가요?", "이거 좋나요?"])
    assert results[0].needs_recheck is False
    assert results[1].needs_recheck is True
    print("✓ needs_recheck 임계 0.85")


def test_fallback_on_worker_none():
    """워커 None(미설정/실패) → api 폴백 호출 + start_index 전달."""
    fake = _FakeApi()
    clf = LocalWorkerClassifier(api_fallback=fake)
    with _mock_worker(None):
        results = clf.classify_batch(["x", "y"], start_index=3)
    assert fake.called_with == (["x", "y"], 3)
    assert len(results) == 2
    assert clf.stats["fallback_calls"] == 1
    print("✓ 워커 None → api 폴백")


def test_fallback_on_size_mismatch():
    """워커 결과 개수 불일치 → api 폴백."""
    fake = _FakeApi()
    clf = LocalWorkerClassifier(api_fallback=fake)
    with _mock_worker([{"label": "PRODUCT_OPINION", "confidence": 0.9}]):  # 1 != 2
        clf.classify_batch(["x", "y"])
    assert fake.called_with is not None
    assert clf.stats["fallback_calls"] == 1
    print("✓ 개수 불일치 → api 폴백")


def test_no_fallback_raises():
    """폴백 없는데 워커 실패 → RuntimeError."""
    clf = LocalWorkerClassifier(api_fallback=None)
    raised = False
    with _mock_worker(None):
        try:
            clf.classify_batch(["x"])
        except RuntimeError:
            raised = True
    assert raised
    print("✓ 폴백 없음 + 워커 실패 → RuntimeError")


def test_index_offset():
    """start_index 가 결과 index 에 반영."""
    clf = LocalWorkerClassifier(api_fallback=_FakeApi())
    with _mock_worker(
        [
            {"label": "PRODUCT_OPINION", "confidence": 0.9},
            {"label": "QUESTION", "confidence": 0.9},
        ]
    ):
        results = clf.classify_batch(["a", "b"], start_index=10)
    assert results[0].index == 10
    assert results[1].index == 11
    print("✓ start_index offset")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"\n{len(tests)}개 테스트 모두 통과")
