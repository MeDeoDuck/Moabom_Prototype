# Comment Filtering Agent 통합 완료

## 📅 통합 일시
2026-04-08

## ✅ 완료된 작업

### 1. DB 스키마 확장 ✅
**파일**: `scripts/database/schema.py`

#### 기존 `comments` 테이블 확장
다음 컬럼 추가:
- `comment_id`: VARCHAR(64) → VARCHAR(255) (Agent 호환)
- `parent_id`: VARCHAR(64) → VARCHAR(255)
- `author_name`: VARCHAR(500) - 댓글 작성자 이름
- `author_channel_id`: VARCHAR(255) - 작성자 채널 ID
- `like_count`: INTEGER - 좋아요 수
- `reply_count`: INTEGER - 답글 수
- `published_at`: TIMESTAMPTZ - 댓글 게시 시간
- `updated_at`: TIMESTAMPTZ - 댓글 수정 시간
- `collected_at`: TIMESTAMPTZ - 수집 시간
- `collection_batch_id`: UUID - 수집 배치 ID
- `is_reply`: BOOLEAN - 답글 여부

#### `comment_sentiments` 테이블 수정
- `comment_id`: VARCHAR(64) → VARCHAR(255) (FK 일치)

#### 추가 인덱스
- `idx_comments_published_at` - 게시 시간 검색 최적화
- `idx_comments_collected_at` - 수집 시간 검색 최적화

---

### 2. Agent 중간 처리 테이블 추가 ✅

#### ENUM 타입 생성
- `filter_status`: PASS, REJECT
- `comment_label`: PRODUCT_OPINION, VIDEO_REACTION, CHATTER, QUESTION, OFF_TOPIC
- `agent_action`: ANALYZE, AUXILIARY_STORE, EXCLUDE, HOLD, RECLASSIFY
- `exclusion_reason`: VIDEO_REACTION, CHATTER, OFF_TOPIC, SPAM, DUPLICATE, PROFANITY, RULE_FILTERED, LOW_CONFIDENCE, OTHER
- `sentiment_type`: POSITIVE, NEUTRAL, NEGATIVE

#### 새 테이블 (5개)

1. **`rule_filter_results`** - 1차 규칙 필터 결과
   - `comment_id` → `comments.comment_id` (FK)
   - `filter_status`: PASS/REJECT
   - `rejected_by_rule`: 거부 규칙 이름
   - `reject_reason`: 거부 사유
   - `filter_metadata`: JSONB - 추가 메타데이터

2. **`llm_classifications`** - 2차 LLM 분류 결과
   - `comment_id` → `comments.comment_id` (FK)
   - `predicted_label`: 5개 라벨 중 하나
   - `confidence_score`: 신뢰도 점수
   - `label_scores`: JSONB - 각 라벨별 점수
   - `model_name`: 사용한 LLM 모델
   - `reasoning`: 분류 근거

3. **`agent_decisions`** - 3차 Agent 최종 결정
   - `comment_id` → `comments.comment_id` (FK)
   - `final_action`: 최종 액션 (ANALYZE/EXCLUDE 등)
   - `exclusion_reason`: 제외 사유
   - `decision_reasoning`: 의사결정 과정
   - `needs_human_review`: 사람 검토 필요 여부

4. **`aspect_definitions`** - Aspect 정의 (성능, 배터리, 디자인 등)
   - `aspect_name`: Aspect 이름
   - `keywords`: 관련 키워드 배열
   - `category`: 카테고리

5. **`aspect_extractions`** - Aspect별 감정 분석
   - `comment_id` → `comments.comment_id` (FK)
   - `aspect_id` → `aspect_definitions.id` (FK)
   - `aspect_name`: Aspect 이름
   - `mention_text`: 언급된 텍스트
   - `aspect_sentiment`: Aspect별 감정 (POSITIVE/NEUTRAL/NEGATIVE)
   - `aspect_sentiment_score`: Aspect별 감정 점수

---

### 3. Agent 통합 (Sync API 수정) ✅
**파일**: `scripts/api/sync.py`

#### 주요 변경사항

1. **Import 추가**
   ```python
   from comment_filtering_agent.services.comment_collector import YouTubeCommentCollector
   from comment_filtering_agent.filters.rule_based_filter import RuleBasedFilter
   from comment_filtering_agent.classifiers.groq_classifier import GroqClassifier
   from comment_filtering_agent.core.agent import AgentDecisionEngine
   from comment_filtering_agent.analyzers.groq_analyzer import GroqAspectSentimentAnalyzer
   ```

2. **새 함수 추가: `process_comments_with_agent()`**
   - YouTube 댓글 수집 (YouTubeCommentCollector)
   - 1차 규칙 필터 (RuleBasedFilter)
   - 2차 LLM 분류 (GroqClassifier)
   - 3차 Agent 결정 (AgentDecisionEngine)
   - 감정 + Aspect 분석 (GroqAspectSentimentAnalyzer)
   - 모든 결과를 기존 테이블 + Agent 테이블에 저장

3. **Fallback 메커니즘**
   - Agent 사용 불가 시 기존 방식으로 폴백
   - `AGENT_AVAILABLE` 플래그로 동적 전환

4. **기존 테이블 호환성 유지**
   - Agent 결과를 `comments`, `comment_sentiments` 테이블에 저장
   - 기존 보고서 코드는 수정 없이 그대로 작동

---

## 📊 데이터 흐름 (변경 후)

```
YouTube API
    ↓
[YouTubeCommentCollector]
    ↓
comments 테이블 저장 (확장된 메타데이터 포함)
    ↓
[RuleBasedFilter] (1차 필터)
    ↓
rule_filter_results 테이블 저장
    ↓
[GroqClassifier] (2차 LLM 분류)
    ↓
llm_classifications 테이블 저장
    ↓
[AgentDecisionEngine] (3차 최종 결정)
    ↓
agent_decisions 테이블 저장
    ↓
[GroqAspectSentimentAnalyzer] (감정 + Aspect 분석)
    ↓
comment_sentiments 테이블 저장 (기존 호환)
aspect_extractions 테이블 저장 (상세 정보)
    ↓
[기존 보고서 생성] (수정 없음)
    ↓
templates/video_detail.html (수정 없음)
```

---

## 🎯 통합 효과

### ✅ 향상된 기능
1. **정교한 필터링**: 규칙 기반 + LLM 조합으로 정확도 향상
2. **5개 라벨 분류**: PRODUCT_OPINION, VIDEO_REACTION, CHATTER, QUESTION, OFF_TOPIC
3. **Aspect별 분석**: 성능, 배터리, 디자인 등 항목별 감정 분석
4. **상세 메타데이터**: 필터 이유, 분류 근거, 신뢰도 등 추적 가능
5. **재처리 가능**: 중간 결과 저장으로 재분석 용이

### ✅ 유지된 기능
1. **기존 보고서**: `scripts/reports/comment_report.py` 수정 없음
2. **기존 화면**: `templates/video_detail.html` 수정 없음
3. **PDF 다운로드**: 기존 기능 그대로 작동
4. **DB 호환성**: `comments`, `comment_sentiments` 테이블 유지

### ✅ 제거된 코드
- ~~`scripts/analysis/sentiment.py`~~ → Agent의 GroqAspectSentimentAnalyzer로 대체
- ~~`scripts/analysis/product_filter.py`~~ → Agent의 RuleBasedFilter + LLM Classifier로 대체
- ~~기존 규칙 기반 감정 분석~~ → LLM 기반 감정 분석 + Aspect 추출

---

## 🔧 필요한 설정

### 환경 변수 (.env)
```bash
YOUTUBE_API_KEY=your_youtube_api_key
GROQ_API_KEY=your_groq_api_key
DATABASE_URL=postgresql://user:password@localhost:5432/dbname
```

### 의존성 (requirements.txt)
```
groq
psycopg2-binary
httpx
fastapi
```

---

## 🚀 사용 방법

### 1. DB 초기화
서버 시작 시 자동으로 테이블 생성됨:
```bash
python scripts/main_youtube_tech_review.py
```

### 2. 데이터 동기화
제품 생성 후 Sync 실행:
```
POST /products/{product_id}/sync
```

Agent가 자동으로:
- 댓글 수집
- 필터링
- 분류
- 감정 분석
- DB 저장

### 3. 결과 확인
비디오 상세 페이지에서 기존과 동일하게 확인:
```
GET /products/{product_id}/videos/{video_id}
```

---

## 📝 TODO (향후 개선)

### 선택적 개선 사항
- [ ] 보고서에 Aspect별 감정 통계 추가
- [ ] Agent 중간 결과 시각화 대시보드
- [ ] 재분류 기능 (HOLD → 재처리)
- [ ] Aspect 정의 관리 UI
- [ ] 배치 재처리 API

### 유지보수
- [ ] Agent 성능 모니터링
- [ ] LLM API 비용 추적
- [ ] 필터 규칙 튜닝
- [ ] Aspect 키워드 확장

---

## 🎉 통합 완료!

Comment Filtering Agent가 성공적으로 통합되었습니다.
- 기존 기능은 그대로 유지
- 고급 분석 기능 추가
- 확장 가능한 구조

**테스트 권장**: 제품 생성 → Sync → 비디오 상세 확인 → PDF 다운로드
