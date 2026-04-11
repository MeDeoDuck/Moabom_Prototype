# Comment Filtering Agent 병렬화 전용 변경안 (기존 로직 불변)

## 목적
- 현재 Agent 경로에서 **병렬 처리만 추가**
- 병렬화 외 로직(필터 기준, 라벨 체계, DB 스키마/컬럼, 보고서 연계, API 계약)은 **절대 변경하지 않음**

---

## 변경 범위 (허용)

### 1) 분류 단계 병렬화
- 대상: `comment_filtering_agent/classifiers/optimized_batch_classifier.py`
- 방식:
  - `batch_size` 기준으로 댓글을 분할
  - 배치 단위 호출을 동시 실행 (`asyncio + semaphore`)
  - 결과 merge 후 기존 파이프라인으로 전달

### 2) 동시성 제한
- 과부하 방지용 `max_concurrent` 적용
- 기본값 예: 3~5

### 3) 재시도/백오프는 기존 정책 유지
- 기존 retry/backoff 정책 재사용
- 정책값 변경 없음 (필요 시 환경변수로만 조정)

---

## 비변경 범위 (금지)

아래 항목은 이번 작업에서 **절대 변경하지 않음**:

1. 1차 규칙 필터 로직 (`RuleBasedFilter`)
2. 라벨 정의/의사결정 정책 (`PRODUCT_OPINION`, `VIDEO_REACTION` 등)
3. DB 테이블/컬럼/인덱스 구조
4. API 응답 포맷 (`/products/{id}/sync` 반환 JSON)
5. 보고서 생성 로직 (`comment_report`, `integrated_report`)
6. UI 템플릿 렌더링 흐름
7. 인증/인가/멀티테넌트 설계
8. Few-shot 구성 개수/프롬프트 본문 내용
9. max_tokens 정책값
10. fallback 규칙의 의미적 동작

---

## 병렬화 적용 구조

```mermaid
flowchart LR
    A[rule_passed comments] --> B[batch split]
    B --> C1[batch #1]
    B --> C2[batch #2]
    B --> C3[batch #3]

    C1 --> D[Semaphore(max_concurrent)]
    C2 --> D
    C3 --> D

    D --> E[Groq classify per batch]
    E --> F[merge results in original order]
    F --> G[기존 agent decide/DB save 단계로 전달]
```

핵심: **병렬 실행 단위만 추가**되고, 배치 결과를 원래 순서대로 합쳐서
이후 단계(`agent_decisions`, `comment_sentiments`, `aspect_extractions`)는 기존과 동일하게 처리.

---

## 최소 구현 포인트

1. `classify_batch()` 내부에서 실질적 batch split 적용  
2. 각 batch를 async task로 실행  
3. `Semaphore`로 동시 요청 제한  
4. 결과를 인덱스 기준으로 정렬/복원  
5. 기존 반환 타입(`List[ClassificationResult]`) 그대로 유지

---

## 검증 기준

### 기능 동일성
- 병렬 on/off 비교 시 라벨/점수 분포가 기존 허용 오차 범위 내
- DB write 결과 스키마/개수/컬럼 동일

### 안정성
- 429/timeout 발생 시 기존 재시도/fallback 동작 동일
- 일부 batch 실패해도 전체 sync 중단 없이 계속 진행

### 성능
- 동일 입력 기준 전체 분류 구간 wall-time 감소

---

## 요약

이번 변경은 **“병렬화만”** 적용한다.
그 외 비즈니스 규칙/DB/보고서/UI/API는 그대로 둔다.
