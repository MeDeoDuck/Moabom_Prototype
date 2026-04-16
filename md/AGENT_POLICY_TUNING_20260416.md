# Agent 정책 튜닝 내역 (2026-04-16)

## 목적
- `selected_pre_llm`는 있는데 `analyzed=0`으로 떨어지는 문제 완화
- 낮은 확신도라도 제품 평가(`PRODUCT_OPINION`)는 분석 대상으로 유지
- 제외(Exclude)와 품질 경고(Review)를 분리

## 적용한 코드 변경

### 1) PRODUCT_OPINION 정책 완화
**파일:** `comment_filtering_agent\core\agent.py`

기존:
- `needs_recheck=True`면 `RECLASSIFY`
- 낮은 확신도(LOW/VERY_LOW)면 `HOLD` 또는 `RECLASSIFY`
- 결과적으로 `PRODUCT_OPINION`인데도 `ANALYZE`로 못 들어가는 경우 다수 발생

변경:
- `PRODUCT_OPINION`이면 확신도와 관계없이 기본 `ANALYZE`
- `needs_recheck` 또는 낮은 확신도는 제외 사유가 아니라 플래그로 처리
  - `needs_human_review=True`
  - `is_low_confidence=True`
- `decision_reasoning`/`decision_metadata`에 저확신/재확인 정보 기록

효과:
- 분석 대상 누락 감소
- 품질 리스크는 보존(후속 검토 가능)

---

### 2) VIDEO_REACTION 예외 분석 조건 완화
**파일:** `comment_filtering_agent\core\models.py`

변경 전:
- `allow_video_reaction_with_features = False`
- `min_product_features_for_analysis = 3`

변경 후:
- `allow_video_reaction_with_features = True`
- `min_product_features_for_analysis = 2`

의미:
- 영상 반응 라벨이어도 제품 특성 언급이 2개 이상이면 분석 허용
- 실제 사용자 반응 데이터의 분석 포함률 증가

## 현재 정책 요약

1. `PRODUCT_OPINION`
   - 기본 `ANALYZE` (저확신/재확인 필요 시 review 플래그만 추가)

2. `VIDEO_REACTION`
   - 제품 특성 언급 2개 이상이면 `ANALYZE`
   - 아니면 기본 `EXCLUDE`

3. `QUESTION`
   - 제품 관련: `AUXILIARY_STORE`
   - 무관: `EXCLUDE`

4. `CHATTER`
   - 기본 `EXCLUDE` (일부 저확신 재확인 케이스 `RECLASSIFY`)

5. `OFF_TOPIC`
   - 기본 `EXCLUDE`

## 관찰 포인트 (운영 로그)
- `selected_pre_llm` 대비 `analyzed` 비율
- `needs_human_review=True` 건수
- `VIDEO_REACTION`에서 실제 `ANALYZE`로 승격된 건수
- `excluded`/`reclassify`/`hold` 분리 로그 (추가 개선 권장)

## 다음 권장 개선
1. `excluded` 단일 카운트를 `exclude/hold/reclassify/auxiliary`로 분리
2. `selected_post_llm`를 `analyzed`와 분리해 의미 명확화
3. 저확신 ANALYZE 결과에 신뢰도 가중치(리포트/랭킹 반영) 추가
