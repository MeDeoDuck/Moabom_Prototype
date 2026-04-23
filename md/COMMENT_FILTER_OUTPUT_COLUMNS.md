# 댓글 필터링 결과 컬럼 정의

> 기준일: 2026-04-23  
> 파이프라인 진입점: `POST /products/{product_id}/sync`

---

## 테이블 관계 (JOIN 키)

```
comments (comment_id)
    ├── rule_filter_results  (comment_id)
    ├── llm_classifications  (comment_id)
    ├── agent_decisions      (comment_id)
    ├── comment_sentiments   (comment_id)
    └── aspect_extractions   (comment_id)  ← 1:N
```

---

## 1. `comments` — 원본 댓글

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `comment_id` | VARCHAR(255) PK | YouTube 댓글 ID |
| `video_id` | VARCHAR(64) FK | 소속 영상 ID |
| `parent_id` | VARCHAR(255) | 답글인 경우 부모 댓글 ID |
| `text_raw` | TEXT | 정제된 댓글 원문 |
| `author_name` | VARCHAR(500) | 작성자 이름 |
| `author_channel_id` | VARCHAR(255) | 작성자 채널 ID |
| `like_count` | INTEGER | 좋아요 수 |
| `reply_count` | INTEGER | 답글 수 |
| `published_at` | TIMESTAMPTZ | 원본 게시 시각 |
| `collected_at` | TIMESTAMPTZ | 수집 시각 |
| `collection_batch_id` | UUID | 수집 배치 ID |
| `is_reply` | BOOLEAN | 답글 여부 |
| `is_product_related` | BOOLEAN | 제품 관련 여부 (fallback 수집 시만 사용) |

---

## 2. `rule_filter_results` — 1차 규칙 필터 결과

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `comment_id` | VARCHAR(255) FK | 댓글 ID |
| `filter_status` | ENUM | **`PASS`** / **`REJECT`** |
| `rejected_by_rule` | VARCHAR(100) | 적용된 규칙명 (REJECT 시) |
| `reject_reason` | TEXT | 제외 사유 상세 |
| `filtered_at` | TIMESTAMPTZ | 필터 처리 시각 |

**`filter_status` 값:**

| 값 | 의미 |
|----|------|
| `PASS` | 규칙 필터 통과 → LLM 분류 후보 |
| `REJECT` | 규칙 필터 탈락 → 이후 단계 없음 |

**`rejected_by_rule` 값 (활성 규칙):**

| 규칙명 | 탈락 기준 |
|--------|----------|
| `TOO_SHORT` | 길이 < 5자 |
| `SPECIAL_CHARS_ONLY` | 특수문자만 |
| `EMOJI_HEAVY` | 이모지 비율 > 70% |
| `LOW_INFORMATION` | 반복문자 비율 > 70% |
| `GREETING_ONLY` | 인사말만 |
| `REACTION_ONLY` | ㅋㅋ, 와, 대박 등 반응어만 |
| `CREATOR_PRAISE_ONLY` | 유튜버 칭찬/구독 유도만 |
| `PROMOTIONAL` | 광고·홍보성 |
| `ABUSIVE` | 욕설 |

---

## 3. `llm_classifications` — 2차 LLM 분류 결과

> `rule_filter_results.filter_status = 'PASS'`이고 다중 기준 선발(상위 20개)에 든 댓글만 존재

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `comment_id` | VARCHAR(255) FK | 댓글 ID |
| `predicted_label` | ENUM | 분류 라벨 (아래 참고) |
| `confidence_score` | NUMERIC(5,4) | 확신도 (0.0 ~ 1.0) |
| `model_name` | VARCHAR(100) | 사용된 LLM 모델명 |
| `reasoning` | TEXT | 분류 근거 (한 줄 요약) |
| `classified_at` | TIMESTAMPTZ | 분류 시각 |

**`predicted_label` 값:**

| 값 | 의미 |
|----|------|
| `PRODUCT_OPINION` | 제품 평가 의견 → 감성 분석 진행 |
| `QUESTION` | 제품/영상 관련 질문 |
| `VIDEO_REACTION` | 영상·리뷰어 반응 |
| `CHATTER` | 잡담·무의미 |
| `OFF_TOPIC` | 제품 무관 |

---

## 4. `agent_decisions` — 3차 Agent 최종 판정

> `llm_classifications`가 존재하는 댓글에만 생성

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `comment_id` | VARCHAR(255) FK | 댓글 ID |
| `final_action` | ENUM | Agent 최종 액션 (아래 참고) |
| `exclusion_reason` | ENUM | 제외 사유 (EXCLUDE 시) |
| `exclusion_details` | TEXT | 제외 사유 상세 |
| `decision_reasoning` | TEXT | 의사결정 상세 근거 |
| `needs_human_review` | BOOLEAN | 수동 검토 필요 여부 |
| `agent_version` | VARCHAR(50) | Agent 버전 |
| `decided_at` | TIMESTAMPTZ | 판정 시각 |

**`final_action` 값:**

| 값 | 조건 | 다음 단계 |
|----|------|----------|
| `ANALYZE` | `PRODUCT_OPINION` 또는 제품 특성 다수 언급 `VIDEO_REACTION` | 감성 분석 실행 |
| `AUXILIARY_STORE` | 제품 관련 `QUESTION` | 질문 저장 |
| `EXCLUDE` | `CHATTER` / `OFF_TOPIC` / 제품 무관 질문 | 제외 로그만 |
| `HOLD` | LLM 분류 실패 | 수동 검토 대기 |
| `RECLASSIFY` | `CHATTER` + 낮은 확신도 | 재분류 큐 |

**`exclusion_reason` 값:**

| 값 | 의미 |
|----|------|
| `VIDEO_REACTION` | 영상 반응 댓글 |
| `CHATTER` | 잡담·무의미 |
| `OFF_TOPIC` | 제품 무관 |
| `SPAM` | 스팸 |
| `DUPLICATE` | 중복 |
| `PROFANITY` | 욕설 |
| `RULE_FILTERED` | 1차 규칙 필터 탈락 |
| `LOW_CONFIDENCE` | 낮은 확신도 |
| `OTHER` | 기타 |

---

## 5. `comment_sentiments` — 감성 레이블/점수

> `agent_decisions.final_action = 'ANALYZE'`인 댓글만 존재

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `comment_id` | VARCHAR(255) FK | 댓글 ID |
| `sentiment_label` | VARCHAR(16) | **`positive`** / **`neutral`** / **`negative`** |
| `sentiment_score` | NUMERIC(4,3) | 감성 점수 (-1.000 ~ +1.000) |
| `analysis_weight` | NUMERIC(4,3) | 분석 신뢰 가중치 (0.0 ~ 1.0, 저확신 시 0.5) |
| `created_at` | TIMESTAMP | 저장 시각 |

**`sentiment_score` 해석:**

| 범위 | 의미 |
|------|------|
| +0.6 ~ +1.0 | 강한 긍정 |
| +0.1 ~ +0.6 | 약한 긍정 |
| -0.1 ~ +0.1 | 중립 |
| -0.6 ~ -0.1 | 약한 부정 |
| -1.0 ~ -0.6 | 강한 부정 |

---

## 6. `aspect_extractions` — 항목별 감성 (ABSA)

> `comment_sentiments`가 존재하는 댓글에 0개 이상 생성 (1:N)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `comment_id` | VARCHAR(255) FK | 댓글 ID |
| `aspect_name` | VARCHAR(100) | 항목명 (예: "발열", "배터리") |
| `mention_text` | TEXT | 댓글 내 실제 언급 텍스트 |
| `aspect_sentiment` | ENUM | **`POSITIVE`** / **`NEUTRAL`** / **`NEGATIVE`** |
| `aspect_sentiment_score` | NUMERIC(5,4) | 항목 감성 점수 (-1.0 ~ +1.0) |
| `extraction_confidence` | NUMERIC(5,4) | 추출 확신도 |
| `extracted_at` | TIMESTAMPTZ | 추출 시각 |

**`aspect_name` 기본 항목:**

| 항목 | 카테고리 |
|------|---------|
| 발열, 성능, 배터리 | 성능 |
| 소음, 디자인, 내구성 | 품질 |
| 휴대성, 편의성 | 사용성 |
| 화면, 디스플레이, 카메라 | 디스플레이 |
| 가격 | 가격 |
| 기능 | 기능 |

---

## 7. 파이프라인 단계별 데이터 유무 요약

| 단계 | 테이블 | 데이터 존재 조건 |
|------|--------|----------------|
| 수집 | `comments` | 모든 수집 댓글 |
| 1차 필터 | `rule_filter_results` | 모든 수집 댓글 |
| 2차 분류 | `llm_classifications` | 규칙 PASS + 상위 20개 선발 댓글만 |
| 3차 판정 | `agent_decisions` | LLM 분류된 댓글만 |
| 감성 분석 | `comment_sentiments` | Agent `ANALYZE` 판정 댓글만 |
| 항목 추출 | `aspect_extractions` | 감성 분석 완료 + aspect 언급 있는 댓글만 |
