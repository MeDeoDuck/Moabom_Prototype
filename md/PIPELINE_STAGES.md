# 댓글 필터링 Agent 파이프라인 — 단계별 분기

영상 1개를 처리하는 단위 함수 `process_comments_with_agent(video_id, product_name)` 기준으로
스텝별 입력/출력/분기 조건을 정리한 문서.

- 진입점 (영상 선정 후 호출): [video_selection_agent/api/routes.py](../video_selection_agent/api/routes.py)
- 본체 (Agent 파이프라인): [scripts/api/sync.py](../scripts/api/sync.py)

---

## 호출 그래프

```
POST /products/{id}/select-videos
  └─ _process_comments_for_videos(product_name, video_ids)
       ├─ AGENT_AVAILABLE == True  → ThreadPoolExecutor(workers=PARALLEL_WORKERS)
       │     └─ process_comments_with_agent(vid, product_name)   ← 본 문서가 다루는 함수
       │          └─ (영상별로 실패 시) _fallback_collect_comments(vid)
       └─ AGENT_AVAILABLE == False → _fallback_collect_comments(vid)  per video
```

`AGENT_AVAILABLE` 은 [scripts/api/sync.py:25-36](../scripts/api/sync.py#L25-L36)의 `comment_filtering_agent.*`
import 성공 여부로 결정된다. 부팅 로그에 `[WARN] Comment filtering agent not available: ...`
가 떴다면 이 단계에서 막힌 것이다.

---

## 주요 상수

| 상수 | 값 | 의미 |
|---|---|---|
| `RAW_COMMENT_FETCH_LIMIT` | 1000 | YouTube에서 가져올 raw 댓글 상한 |
| `PREPROCESS_CANDIDATE_MIN` | 250 | Step 4 후보 풀 권장 하한 (미달 시 WARN) |
| `PREPROCESS_CANDIDATE_MAX` | 300 | Step 4 후보 풀 상한 (cut) |
| `TOP_PER_SOURCE` | 30 | Step 5 source별 top-K |
| `MAX_COMMENT_CHARS` | 140 | LLM 투입 댓글 길이 cap |
| `CLASSIFICATION_BATCH_SIZE` | 8 | LLM 배치 크기 |
| `TOKEN_BUDGET_PER_VIDEO` | 2000 | Step 5.5 영상당 토큰 예산 |
| `PARALLEL_WORKERS` | 3 | 영상 병렬 처리 수 (Groq 무료 12K TPM 기준) |

---

## Step 0 — Pre-flight check

[sync.py:335-361](../scripts/api/sync.py#L335-L361)

- `AGENT_AVAILABLE` False → 즉시 `raise` (caller가 fallback으로 분기)
- `AZURE_OPENAI_API_KEY` 또는 `YOUTUBE_API_KEY` 비어 있음 → `raise`
- 통과하면 `batch_id = uuid4()` 발급 후 컴포넌트 초기화:
  - `YouTubeCommentCollector`
  - `RuleBasedFilter` (URL 체크 OFF, 중복 체크 OFF, 반복문자 임계 0.7)
  - `OptimizedBatchClassifier` (batch=8, threshold=0.75)
  - `AgentDecisionEngine`
  - `GroqAspectSentimentAnalyzer`

---

## Step 1 — 댓글 수집

[sync.py:382-388](../scripts/api/sync.py#L382-L388)

- `collector.collect_comments(video_id, max_results=1000)`
- **분기**:
  - 결과 0건 → 즉시 `stats` 반환 종료
  - 그 외 → Step 2 로 진행
- 출력: `raw_comments` (List[YouTubeComment])
- 카운터: `stats["collected"]`

---

## Step 2 — 전처리 (Spark-style)

[sync.py:391-400](../scripts/api/sync.py#L391-L400) → `_preprocess_comments`

- null/공백 제거
- `(video_id, author, text)` exact dedup
- 길이/URL/반복문자 등 spark_flags 부착 (드롭하지 않음, 다운스트림 점수 참조용)
- 출력: `spark_rows`
- 카운터: `deduped_count`

---

## Step 3 — 영구 저장 + 룰 필터 (Soft filtering)

[sync.py:403-486](../scripts/api/sync.py#L403-L486)

- 각 row 를 `comments` 테이블에 INSERT/UPSERT (이후 FK 무결성 보장용 raw 보관)
- `RuleBasedFilter.filter_single(comment_text)` → PASS / REJECT 결과를 `rule_filter_results` 에 기록
- **분기**:
  - PASS → `candidate_comments` 풀에 진입 (`stats["rule_passed"]++`)
  - REJECT → DB 기록만 하고 후속 단계에서 제외 (`stats["rule_rejected"]++`)
- 룰 필터 정책 (의도적으로 느슨하게):
  - URL 포함 댓글도 LLM 판단에 위임
  - 반복문자 임계 0.7 — `ㅋㅋㅋ` 혼합 댓글 살림

---

## Step 4 — 후보 풀 사전 가공

[sync.py:489-507](../scripts/api/sync.py#L489-L507) → `_preprocess_candidate_pool`

- 점수 = `keyword_score × 4 + length_score × 2 + normalized_engagement × 1`
- 정렬 후 상위 `PREPROCESS_CANDIDATE_MAX=300` 컷
- 출력: `preprocessed_candidates`
- 카운터: `preprocessed_count`
- **WARN 조건**: `output_count < PREPROCESS_CANDIDATE_MIN(250)` 이면 풀이 너무 얕다는 로그

---

## Step 5 — 멀티 크리테리아 선정

[sync.py:509-522](../scripts/api/sync.py#L509-L522) → `_select_comments_multicriteria`

- 4개 source(키워드 hit / 길이 / 좋아요 / 답글) 각각 top-`TOP_PER_SOURCE=30` 추출
- 댓글별 hit_count 계산:
  - **2개 이상 source 에 잡힘** → primary_pool
  - **1개에만 잡힘** → secondary_pool
- **분기**: primary 우선 선택, 부족하면 secondary 보충
- 출력: `selected_items`, `selected_meta` (rank/sources/secondary_score 포함)
- 카운터: `selected_before_budget_count`

---

## Step 5.5 — 토큰 예산 트리밍

[sync.py:523-555](../scripts/api/sync.py#L523-L555)

- 각 댓글의 추정 토큰 = `max(10, len(text) // 3)`
- 합산이 `TOKEN_BUDGET_PER_VIDEO=2000` 초과 시:
  1. `(hit_count, secondary_score, likes, replies)` 역순 정렬
  2. 합계 ≤ 2000 될 때까지 뒤에서 pop
- **분기**:
  - 결과 0건 → `return stats` (LLM 호출 없이 종료)
  - 그 외 → Step 6 진행
- 카운터: `selected_after_budget_count`

---

## Step 6 — LLM 배치 분류

[sync.py:561-588](../scripts/api/sync.py#L561-L588)

- `OptimizedBatchClassifier.classify_batch(texts, start_index=0)`
- 결과 개수 ≠ 입력 개수 → `raise` (정합성 보호)
- 출력: 라벨 (예: `PRODUCT_RELATED` / `OPINION` / `QUESTION` / `SPAM` / `OFF_TOPIC`) + confidence + rationale
- DB: `llm_classifications` 테이블에 UPSERT
- 카운터: `classified_count`, `stats["selected_pre_llm"]`

---

## Step 7 — Agent 결정 + 감정/Aspect 분석

[sync.py:591-720](../scripts/api/sync.py#L591-L720)

- 댓글마다 `AgentDecisionEngine.decide(comment, filter_result, classification_result, index)`
- `agent_decisions` 테이블 저장: `final_action`, `exclusion_reason`, `decision_reasoning`, `needs_human_review`
- **분기 (`final_action` 기준)**:
  - `ANALYZE`
    → `GroqAspectSentimentAnalyzer.analyze_single(text)`
    → `comment_sentiments` (overall) + `aspect_extractions` (per aspect) 저장
    → `stats["analyzed"]++`
    → `is_low_confidence` 면 `analysis_weight` 가중치 낮춤 + `low_confidence_analyzed_count++`
  - `EXCLUDE` / `AUXILIARY` / `HOLD` / `RECLASSIFY`
    → `stats["excluded"]++`
- 개별 댓글 처리 실패는 `conn.rollback()` 후 다음 댓글로 (`stats["errors"]++`)

---

## Step 8 — 마무리 / 진단 로그

[sync.py:714-739](../scripts/api/sync.py#L714-L739)

- `low_confidence_analyzed_count / analyzed > LOW_CONFIDENCE_WARNING_THRESHOLD` → `[WARN]` 로그
- `FINAL FUNNEL SUMMARY` 라인 출력 (한 줄 깔때기)
- `conn.commit()` / `conn.close()` 후 `stats` 반환

---

## 깔때기 한 눈에

```
collected (≤1000)
  → deduped              [Step 2]
  → rule_pass            [Step 3 — soft filter]
  → preprocessed (≤300)  [Step 4]
  → selected_before_budget [Step 5]
  → selected_after_budget (≤2000 tok) [Step 5.5]
  → classified           [Step 6 — LLM]
  → analyzed / excluded / errors [Step 7]
```

---

## Fallback 경로 (Agent 우회)

[video_selection_agent/api/routes.py:49-113](../video_selection_agent/api/routes.py#L49-L113)
의 `_fallback_collect_comments(video_id)` 가 실행된다.

1. `fetch_video_comments(video_id, max_pages=2)` 로 단순 수집
2. `comments` 테이블에 raw 저장
3. 사전 정의된 한/영 키워드 목록(`_FALLBACK_POSITIVE_KEYWORDS`,
   `_FALLBACK_NEGATIVE_KEYWORDS`) 으로 pos/neg 카운트
4. `comment_sentiments` 에 `positive(0.7)` / `negative(0.3)` / `neutral(0.5)` 저장

→ Agent 파이프라인의 룰 필터 / 후보 풀 / 멀티 크리테리아 / LLM 분류 / Agent 결정 /
Aspect 추출 단계가 **모두 스킵**되며, 보고서가 빈 채로 남는 것을 막기 위한 graceful
degrade 용도일 뿐 분석 품질은 크게 떨어진다.

콘솔에 `[SELECT] Comment processing start (fallback)` 또는
`Fallback collected=N` 로그가 보인다면 Agent 파이프라인이 한 번도 호출되지 않은
상태이므로, 아래 진단 단계를 따라가야 한다.

---

## Fallback 트리거 진단 체크리스트

1. 부팅 시점 콘솔에서 다음 메시지 검색:
   - `[WARN] Comment filtering agent not available: <에러>` → `comment_filtering_agent.*` import 실패
   - `[SELECT] Comment agent module unavailable: <에러>` → `scripts.api.sync` 자체 import 실패
2. import는 성공했지만 호출 시 실패하는 경우:
   - `Missing API keys (YOUTUBE_API_KEY or AZURE_OPENAI_API_KEY)` → 환경변수 누락
   - `[SYNC] [vid] Agent failed: ..., falling back to simple collection` → 런타임 예외 (스택 트레이스 확인)
3. 영상별 결과는 정상이지만 일부만 fallback 으로 빠지는 경우:
   - `[SELECT] [vid] Agent failed: <에러>; falling back to simple collection` (routes.py 분기)
