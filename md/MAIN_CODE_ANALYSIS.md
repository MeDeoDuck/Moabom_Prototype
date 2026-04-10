# main_youtube_analysis.py - 기능 분석 및 역할별 정리

> **목적**: YouTube 테크 제품 리뷰 분석 웹 서비스  
> **프레임워크**: FastAPI + PostgreSQL + YouTube Data API v3  
> **주요 기능**: 제품별 영상 수집 → 댓글 감정 분석 → 자막 분석 → 통합 보고서 생성

---

## 📁 전체 아키텍처

```
┌─────────────────────────────────────────────────┐
│                   FastAPI 웹 서버                 │
└─────────────────────────────────────────────────┘
                       │
    ┌──────────────────┼──────────────────┐
    │                  │                  │
┌───▼───┐         ┌───▼───┐         ┌───▼───┐
│ 제품   │         │ 영상   │         │ 댓글   │
│ 관리   │         │ 수집   │         │ 분석   │
└───┬───┘         └───┬───┘         └───┬───┘
    │                  │                  │
    └──────────────────┴──────────────────┘
                       │
            ┌──────────▼──────────┐
            │   PostgreSQL DB     │
            │   - products        │
            │   - videos          │
            │   - comments        │
            │   - sentiments      │
            │   - transcripts     │
            │   - reports         │
            └─────────────────────┘
```

---

## 🗂️ 모듈별 기능 분류

### **1. DATABASE LAYER** (Line 38-199)
> 데이터베이스 연결, 초기화, CRUD 작업

#### 1.1 **연결 관리**
- `get_connection()` (Line 42-47)
  - PostgreSQL 연결 생성
  - UTF-8 인코딩 설정

#### 1.2 **스키마 초기화**
- `init_db()` (Line 50-152)
  - 테이블 생성:
    - `tech_products`: 제품 정보
    - `videos`: 영상 메타데이터 (조회수, 좋아요 등)
    - `comments`: 댓글 원문
    - `comment_sentiments`: 댓글 감정 분석 결과
    - `video_transcripts`: 자막 텍스트
    - `video_reports`: 분석 보고서 (자막 분석, 댓글 분석, 통합 분석)
  - 인덱스 생성
  - 마이그레이션 (integrated_report 컬럼 추가)

#### 1.3 **쿼리 헬퍼 함수**
- `query_one()` (Line 156-164)
  - 단일 행 조회
- `query_all()` (Line 167-175)
  - 다중 행 조회
- `execute_insert()` (Line 178-187)
  - INSERT 실행 및 ID 반환
- `execute_update()` (Line 190-199)
  - UPDATE/DELETE 실행 및 영향 행 수 반환

---

### **2. YOUTUBE API LAYER** (Line 202-501)
> YouTube Data API 호출 및 데이터 수집

#### 2.1 **영상 검색 및 통계 수집**
- `fetch_product_videos()` (Line 206-266)
  - 제품명으로 YouTube 검색
  - 영상 통계 가져오기 (조회수, 좋아요, 댓글 수)
  - 반환: `[{video_id, title, description, published_at, thumbnail_url, view_count, like_count, comment_count}]`

#### 2.2 **댓글 수집**
- `fetch_video_comments()` (Line 269-318)
  - 특정 영상의 top-level 댓글 수집
  - 페이지네이션 지원 (max_pages)
  - 반환: `[{comment_id, text_raw}]`

#### 2.3 **자막 수집 (고급)**
- `fetch_video_transcript()` (Line 321-475)
  - **yt-dlp**로 caption URL 추출 (동영상 다운로드 없음)
  - **JSON3 / VTT** 형식 파싱
  - **429 에러 자동 재시도** (exponential backoff)
  - 언어 우선순위: 한국어 → 영어
  - 반환: `{transcript_text, language_code, segment_count}`

#### 2.4 **인코딩 수정**
- `fix_encoding()` (Line 478-500)
  - 한글 깨짐 문자 수정
  - mojibake 처리

---

### **3. REPORT GENERATION LAYER** (Line 503-1023)
> 분석 보고서 생성 (자막 분석, 댓글 분석, 통합 분석)

#### 3.1 **자막 기반 제품 분석 보고서**
- `build_transcript_report_heuristic()` (Line 503-691)
  - **Rule-based 분석** (LLM 없이도 동작)
  - 추출 항목:
    1. 📋 제품 설명 (기능, 사양 언급)
    2. 👍 긍정 평가
    3. ⚠️ 우려사항 / 비판
    4. 🔄 대안 / 업그레이드 정보
    5. 🔑 주요 키워드
  - 키워드 매칭 기반
  - 문장 분류 알고리즘

- `build_transcript_report()` (Line 694-730)
  - **Groq Llama 우선 사용** (API 키 있을 때)
  - Fallback: heuristic 분석
  - 프롬프트: `build_transcript_report_prompt()` (외부 모듈)
  - 토큰 절약: 자막 2000자로 제한

#### 3.2 **댓글 감정 분석 보고서**
- `build_comment_sentiment_report()` (Line 733-915)
  - **DB에 저장된 감정 분석 결과 활용** (실시간 분석 X)
  - Groq Llama로 감정 그룹별 요약:
    - 긍정 댓글 주요 의견
    - 부정 댓글 주요 불만
    - 중립 댓글 특징
    - 전체 시장 반응 평가
  - Fallback: rule-based 요약
  - 샘플 댓글 표시 (상위 5개)
  - 감정 비율 계산

#### 3.3 **통합 분석 보고서**
- `build_integrated_analysis_report()` (Line 918-1023)
  - **리뷰어(자막) vs 소비자(댓글) 비교**
  - Groq Llama 분석:
    1. 리뷰어 평가 요약
    2. 사람들의 반응 요약
    3. **의견 유사도** (%) 계산
       - 제품 강점 일치도
       - 제품 약점 일치도
       - 전체 평가 방향 일치도
    4. 일치점 vs 불일치점
    5. 시장 인사이트
  - Fallback: 간단한 요약

#### 3.4 **보고서 생성 및 저장**
- `generate_and_save_all_reports()` (Line 1026-1095)
  - 3가지 보고서 한 번에 생성
  - 캐싱: force_rewrite=False 시 DB 캐시 사용
  - 자동 저장: `upsert_video_report()`

- `upsert_video_report()` (Line 1098-1110)
  - video_reports 테이블에 저장
  - 기존 보고서 완전 교체

#### 3.5 **PDF 다운로드**
- `render_report_pdf()` (Line 1113-1198)
  - ReportLab 사용
  - 한글 폰트 지원 (malgun.ttf)
  - 자동 페이지 나누기

---

### **4. SENTIMENT & PRODUCT ANALYSIS** (Line 1201-1252)
> 댓글 필터링 및 감정 분석

#### 4.1 **제품 관련성 판단**
- `is_product_related()` (Line 1205-1226)
  - Rule-based 필터링
  - 제품명 포함 여부
  - 테크 키워드 매칭 (price, spec, battery, performance 등)

#### 4.2 **감정 분석**
- `analyze_sentiment()` (Line 1229-1252)
  - Rule-based 감정 분류
  - 긍정/부정 키워드 카운트
  - 반환: `(sentiment_label, sentiment_score)`
  - 라벨: "positive" / "neutral" / "negative"

---

### **5. FASTAPI WEB APPLICATION** (Line 1255-1760)
> 웹 인터페이스 및 REST API

#### 5.1 **앱 초기화**
- `app = FastAPI()` (Line 1261)
- `UTF8CharsetMiddleware` (Line 1264-1271)
  - HTML 응답에 UTF-8 charset 자동 추가
- `templates = Jinja2Templates()` (Line 1279)
  - Jinja2 템플릿 엔진
- `startup_event()` (Line 1282-1285)
  - DB 초기화

#### 5.2 **라우트 (Routes)**

##### **홈페이지**
- `GET /` (Line 1288-1291)
  - `/products`로 리다이렉트

##### **제품 관리**
- `GET /products` (Line 1294-1301)
  - 전체 제품 목록
  - Template: `products.html`

- `POST /products` (Line 1304-1320)
  - 새 제품 생성
  - Body: `{name, brand, category}`

- `GET /products/{product_id}` (Line 1323-1340)
  - 제품 상세 페이지
  - 해당 제품의 영상 목록 표시
  - Template: `product_detail.html`

##### **데이터 동기화**
- `POST /products/{product_id}/sync` (Line 1343-1502)
  - **핵심 기능**: YouTube 데이터 수집 및 저장
  - 프로세스:
    1. 기존 데이터 전체 삭제 (clean slate)
    2. YouTube에서 영상 검색 (`fetch_product_videos`)
    3. 영상별로:
       - 영상 정보 저장
       - 댓글 수집 (`fetch_video_comments`)
       - **댓글 감정 분석 즉시 수행** (keyword matching)
       - 감정 결과 DB 저장
    4. 자막은 on-demand로 수집 (Rate Limit 방지)
  - 반환: `{status, videos_count, comments_count, transcripts_count}`

##### **영상 상세**
- `GET /products/{product_id}/videos/{video_id}` (Line 1505-1635)
  - **핵심 화면**: 영상 분석 결과 표시
  - 기능:
    - 댓글 페이지네이션 (10개씩)
    - **감정 필터링** (positive/neutral/negative)
    - 감정 분포 통계
    - 자막 자동 복구 (없으면 fetch)
    - **3가지 보고서 로드** (캐시 사용):
      - 자막 분석 보고서
      - 댓글 감정 보고서
      - 통합 분석 보고서
  - Template: `video_detail.html`

##### **AI 분석 상태**
- `GET /api/ai-analysis-status` (Line 1638-1661)
  - Airflow 통합용 엔드포인트
  - 현재는 static response

##### **PDF 다운로드**
- `GET /products/{product_id}/videos/{video_id}/transcript-report.pdf` (Line 1664-1691)
  - 자막 분석 보고서 PDF

- `GET /products/{product_id}/videos/{video_id}/comment-report.pdf` (Line 1694-1725)
  - 댓글 분석 보고서 PDF

- `GET /products/{product_id}/videos/{video_id}/integrated-analysis.pdf` (Line 1728-1759)
  - 통합 분석 보고서 PDF

#### 5.3 **서버 실행**
- `if __name__ == "__main__"` (Line 1766-1777)
  - Uvicorn 서버 시작
  - 기본 포트: 8000
  - CLI 오버라이드 가능: `python main.py 8001`

---

## 🔄 데이터 흐름 (End-to-End)

```
1. 사용자가 제품 생성
   POST /products {name: "iPhone 16 Pro"}
   → tech_products 테이블에 저장

2. 데이터 동기화 트리거
   POST /products/1/sync
   → YouTube API: 영상 검색 (5개)
   → 각 영상마다:
      ├─ videos 테이블 저장
      ├─ 댓글 수집 (최대 200개)
      ├─ comments 테이블 저장
      └─ 감정 분석 수행 → comment_sentiments 테이블 저장

3. 사용자가 영상 상세 페이지 접근
   GET /products/1/videos/abc123
   → 자막이 없으면 자동 수집
      ├─ yt-dlp로 caption URL 추출
      ├─ JSON3/VTT 파싱
      └─ video_transcripts 테이블 저장
   
   → 보고서가 없으면 자동 생성
      ├─ 자막 분석 (Groq Llama)
      ├─ 댓글 감정 요약 (Groq Llama)
      ├─ 통합 분석 (Groq Llama)
      └─ video_reports 테이블 저장
   
   → HTML 페이지 렌더링
      ├─ 댓글 목록 (페이지네이션)
      ├─ 감정 통계 (차트)
      ├─ 자막 분석 보고서
      ├─ 댓글 감정 보고서
      └─ 통합 분석 보고서

4. 보고서 PDF 다운로드
   GET /products/1/videos/abc123/integrated-analysis.pdf
   → DB에서 보고서 로드
   → ReportLab으로 PDF 생성
   → 브라우저 다운로드
```

---

## 🎯 모듈화 추천 구조

### **현재 문제점**
- 모든 기능이 단일 파일 (1778 lines)
- 역할 분리 불명확
- 테스트 어려움
- 확장성 낮음

### **추천 디렉토리 구조**

```
youtube_analysis/
├── main.py                       # FastAPI 앱 진입점만
├── config.py                     # 환경 변수, 설정
├── database/
│   ├── __init__.py
│   ├── connection.py             # get_connection()
│   ├── schema.py                 # init_db()
│   └── queries.py                # query_one(), query_all() 등
├── youtube/
│   ├── __init__.py
│   ├── video_service.py          # fetch_product_videos()
│   ├── comment_service.py        # fetch_video_comments()
│   └── transcript_service.py     # fetch_video_transcript()
├── analysis/
│   ├── __init__.py
│   ├── sentiment.py              # analyze_sentiment()
│   ├── product_filter.py         # is_product_related()
│   └── transcript_analyzer.py    # build_transcript_report()
├── reports/
│   ├── __init__.py
│   ├── transcript_report.py      # 자막 분석 보고서
│   ├── comment_report.py         # 댓글 감정 보고서
│   ├── integrated_report.py      # 통합 분석 보고서
│   └── pdf_generator.py          # render_report_pdf()
├── api/
│   ├── __init__.py
│   ├── products.py               # 제품 관련 라우트
│   ├── videos.py                 # 영상 관련 라우트
│   └── sync.py                   # 동기화 라우트
├── models/
│   ├── __init__.py
│   ├── product.py                # Product, Video 모델
│   └── comment.py                # Comment, Sentiment 모델
├── templates/
│   ├── products.html
│   ├── product_detail.html
│   └── video_detail.html
└── tests/
    ├── test_youtube_service.py
    ├── test_sentiment.py
    └── test_reports.py
```

### **모듈별 책임**

| 모듈 | 책임 | 주요 함수 |
|-----|-----|---------|
| **database** | DB 연결, 스키마, CRUD | `get_connection()`, `init_db()`, `query_*()` |
| **youtube** | YouTube API 호출 | `fetch_product_videos()`, `fetch_video_comments()`, `fetch_video_transcript()` |
| **analysis** | 데이터 분석 (감정, 필터링) | `analyze_sentiment()`, `is_product_related()` |
| **reports** | 보고서 생성 (자막, 댓글, 통합) | `build_*_report()`, `render_report_pdf()` |
| **api** | FastAPI 라우트 | `GET /products`, `POST /sync`, etc. |
| **models** | 데이터 모델 | Product, Video, Comment, Sentiment |

---

## 🚀 모듈화 이점

1. **유지보수성**: 기능별로 파일 분리 → 변경 영향 범위 최소화
2. **테스트 가능성**: 각 모듈 독립 테스트 가능
3. **재사용성**: 다른 프로젝트에서도 모듈 재사용
4. **확장성**: 새 기능 추가 시 해당 모듈만 수정
5. **협업**: 팀원별로 다른 모듈 작업 가능

---

## 📊 주요 통계

- **총 라인 수**: 1,778
- **함수 개수**: 30+
- **API 엔드포인트**: 12개
- **DB 테이블**: 6개
- **외부 API**: 3개 (YouTube Data API, YouTube Transcript API, Groq Llama)

---

## 🔧 기술 스택

| 카테고리 | 기술 |
|---------|-----|
| **웹 프레임워크** | FastAPI + Uvicorn |
| **데이터베이스** | PostgreSQL + psycopg2 |
| **템플릿 엔진** | Jinja2 |
| **YouTube API** | httpx (REST), yt-dlp (자막) |
| **LLM** | Groq Llama (OpenAI 호환 API) |
| **PDF 생성** | ReportLab |
| **환경 변수** | python-dotenv |

---

## 💡 개선 제안

### **1. 댓글 필터링 Agent 통합**
현재: Rule-based 감정 분석 (키워드 매칭)  
개선: `comment_filtering_agent` 모듈 통합
- LLM 기반 분류 (PRODUCT_OPINION, QUESTION, VIDEO_REACTION, CHATTER, OFF_TOPIC)
- Batch processing으로 비용 절감
- 더 정확한 감정 분석

### **2. 비동기 처리**
현재: 동기 코드 (sync 시 오래 걸림)  
개선: `asyncio` + `httpx` async 사용
- 영상 병렬 수집
- 댓글 batch 처리
- 보고서 생성 background task

### **3. 캐싱 레이어**
현재: DB 캐싱만 (video_reports)  
개선: Redis 캐싱
- API 응답 캐싱 (YouTube API 절약)
- 보고서 캐싱 (LLM 비용 절약)
- 세션 관리

### **4. 에러 처리 강화**
현재: 일부 try-except만  
개선:
- 429 Rate Limit 전역 처리
- Retry with exponential backoff
- Sentry 연동

### **5. 테스트 코드**
현재: 없음  
개선:
- Unit tests (pytest)
- Integration tests
- API tests (TestClient)

---

## 📝 요약

`main_youtube_analysis.py`는 **YouTube 테크 제품 리뷰 분석 웹 서비스**의 **단일 파일 구현**입니다.

**핵심 기능:**
1. ✅ 제품 관리 (CRUD)
2. ✅ YouTube 영상/댓글 자동 수집
3. ✅ 댓글 감정 분석 (rule-based)
4. ✅ 자막 기반 제품 분석 (Groq Llama)
5. ✅ 통합 분석 보고서 (리뷰어 vs 소비자)
6. ✅ PDF 다운로드
7. ✅ 웹 UI (Jinja2 템플릿)

**모듈화가 필요한 이유:**
- 1778 라인의 단일 파일
- 역할 분리 불명확
- 테스트 불가능
- 확장 어려움

**다음 단계:**
앞으로 모듈화 작업 시 위의 디렉토리 구조를 참고하여 점진적으로 리팩토링하세요.
