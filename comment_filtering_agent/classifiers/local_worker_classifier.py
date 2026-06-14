"""Worker-backed 댓글 분류기 어댑터 (klue-roberta-large 3-class, GPU 워커).

데스크탑 GPU 워커의 `POST /classify` 를 호출하고, raw `{label, confidence}`
응답을 `comment_filtering_agent.classifiers.models.ClassificationResult` 로
변환한다. 이때 `label` 은 반드시 **CommentLabel enum** 이어야 한다 —
`core.agent.AgentDecisionEngine.decide` 가 `classification.label.value` 를
호출하고 `label == CommentLabel.X` 로 비교하기 때문.

⚠️ 이 enum 변환이 어댑터의 존재 이유다. 재현(testLocalvsAPI) 의
`LocalRobertaClassifier` / `CascadeRouter` 는 **str** label(
classifier_interface.ClassificationResult)을 반환 → agent.decide 에서
`str.value` AttributeError 로 크래시한다. 벤치마크는 agent.decide 를 거치지
않아 이 버그가 드러난 적이 없다.

`OptimizedBatchClassifier` 의 drop-in 대체: 동일한
`classify_batch(comments, start_index=0) -> List[ClassificationResult]`
시그니처. 워커가 미설정/타임아웃/4xx/5xx 등으로 실패하면 api 분류기로
폴백해 운영이 hard-fail 하지 않는다.
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from typing import List, Optional

import requests

from comment_filtering_agent.classifiers.aspect_keywords import (
    extract_mentioned_features,
)
from comment_filtering_agent.classifiers.models import (
    ClassificationResult,
    ClassifierType,
    CommentLabel,
)

# 워커는 3-class 만 반환하지만, 안전망으로 legacy 라벨도 VR 로 흡수 매핑.
# (재현 local_classifier/config.py:LEGACY_LABEL_REMAP 와 동일.)
_LEGACY_REMAP = {
    "CHATTER": "VIDEO_REACTION",
    "OFF_TOPIC": "VIDEO_REACTION",
    "NOISE": "VIDEO_REACTION",
}

# 워커 confidence < tau → needs_recheck (재현 config.ROUTER_TAU_HIGH=0.85).
ROUTER_TAU_HIGH = 0.85


def _post_classify(
    comments: List[str], *, timeout_seconds: int = 30
) -> Optional[list]:
    """POST {comments:[...]} → 워커 /classify.

    `video_selection_agent/scope_filter/client.py` 패턴: requests + Bearer,
    3-attempt exponential backoff. 성공 시 results 리스트, 실패 시 None 반환
    (호출자가 api 폴백으로 넘어갈 수 있도록).

    env: CLASSIFY_WORKER_URL/TOKEN (없으면 SCOPE_WORKER_URL/TOKEN 폴백 —
    같은 워커·같은 토큰을 공유하므로). 둘 다 없으면 None → api 폴백.
    """
    if not comments:
        return []

    base_url = os.environ.get("CLASSIFY_WORKER_URL") or os.environ.get("SCOPE_WORKER_URL")
    token = os.environ.get("CLASSIFY_WORKER_TOKEN") or os.environ.get("SCOPE_WORKER_TOKEN")
    if not base_url or not token:
        return None

    url = base_url.rstrip("/") + "/classify"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"comments": list(comments)}

    last_status: Optional[int] = None
    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout_seconds)
            last_status = resp.status_code
            if resp.status_code == 200:
                return resp.json().get("results", [])
            if 500 <= resp.status_code < 600:
                print(
                    f"[CLASSIFY] worker 5xx ({resp.status_code}), retry {attempt + 1}/3",
                    flush=True,
                )
                time.sleep(2 ** attempt)
                continue
            # 4xx → config/auth error; don't retry
            print(
                f"[CLASSIFY] worker client error {resp.status_code}: {resp.text[:200]}",
                flush=True,
            )
            return None
        except requests.exceptions.RequestException as exc:
            print(
                f"[CLASSIFY] worker request error attempt {attempt + 1}/3: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            time.sleep(2 ** attempt)
            continue

    print(f"[CLASSIFY] worker exhausted retries (last_status={last_status})", flush=True)
    return None


class LocalWorkerClassifier:
    """워커 기반 3-class 분류기 + api 폴백.

    Args:
        api_fallback: `classify_batch(comments, start_index)` 를 갖는 분류기
            (즉 OptimizedBatchClassifier). 워커 미가용/응답 이상 시 사용.
        timeout_seconds: 워커 HTTP 타임아웃.
    """

    def __init__(self, api_fallback=None, timeout_seconds: int = 30):
        self.api_fallback = api_fallback
        self.timeout_seconds = timeout_seconds
        self.stats = {"worker_calls": 0, "fallback_calls": 0}

    def classify_batch(
        self, comments: List[str], start_index: int = 0
    ) -> List[ClassificationResult]:
        if not comments:
            return []

        raw = _post_classify(comments, timeout_seconds=self.timeout_seconds)

        # 워커 실패 또는 개수 불일치 → api 폴백 (운영 hard-fail 방지).
        if raw is None or len(raw) != len(comments):
            if raw is not None and len(raw) != len(comments):
                print(
                    f"[CLASSIFY] worker result size mismatch "
                    f"{len(raw)}!={len(comments)} → api fallback",
                    flush=True,
                )
            if self.api_fallback is None:
                raise RuntimeError(
                    "Worker /classify unavailable and no api_fallback configured"
                )
            self.stats["fallback_calls"] += 1
            return self.api_fallback.classify_batch(comments, start_index=start_index)

        self.stats["worker_calls"] += 1
        results: List[ClassificationResult] = []
        for i, (text, item) in enumerate(zip(comments, raw)):
            raw_label = item.get("label", "VIDEO_REACTION")
            label_str = _LEGACY_REMAP.get(raw_label, raw_label)
            try:
                label = CommentLabel(label_str)
            except ValueError:
                # 알 수 없는 라벨 → VR 로 안전 흡수
                label = CommentLabel.VIDEO_REACTION
            confidence = float(item.get("confidence", 0.0))

            # VR 로 분류된 댓글만 키워드 후처리 → agent._handle_video_reaction
            # 가 features>=2 면 ANALYZE 승격 (재현 classifier._to_result 미러).
            # PO/Q 는 이미 ANALYZE/AUXILIARY_STORE 라 매칭 불필요.
            if label == CommentLabel.VIDEO_REACTION and text:
                mentioned = extract_mentioned_features(text)
            else:
                mentioned = []

            results.append(
                ClassificationResult(
                    index=start_index + i,
                    original_comment=text,
                    label=label,
                    confidence=confidence,
                    rationale_short=f"worker roberta-large 3class (conf {confidence:.2f})",
                    needs_recheck=(confidence < ROUTER_TAU_HIGH),
                    mentioned_product_features=mentioned,
                    is_product_related=label
                    in {CommentLabel.PRODUCT_OPINION, CommentLabel.QUESTION},
                    classifier_type=ClassifierType.FINE_TUNED,
                    model_name="klue-roberta-large-3class",
                    prompt_version="worker_v1",
                    llm_provider="desktop_worker",
                    classified_at=datetime.now(),
                    raw_response=item,
                )
            )
        return results

    def get_stats(self) -> dict:
        return dict(self.stats)
