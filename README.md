feature/insight-supervisor
# Moabom Prototype

유튜브 테크 제품 리뷰 영상을 수집해 자막과 댓글을 분석하고, 리뷰어와 소비자 의견을 비교한 통합 보고서를 생성하는 FastAPI 서비스.

## 동작 흐름

```
제품 등록 → YouTube 영상/댓글 수집 → 자막 추출 → LLM 보고서 3종 생성
                                                ├─ 자막 기반 리뷰어 분석
                                                ├─ 댓글 기반 소비자 반응
                                                └─ 통합 분석 (의견 일치도 %)
```

## 빠른 시작

### 1. 사전 준비

- Python 3.12+
- Docker Desktop
- API 키 2개:
  - [YouTube Data API v3](https://console.cloud.google.com/apis/credentials)
  - [Groq Console](https://console.groq.com/keys)

### 2. 환경 설정

```powershell
cd Moabom_Prototype

python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`.env` 파일에 API 키를 입력합니다 (DATABASE_URL은 docker 사용 시 기본값 그대로 두면 됩니다):

```
YOUTUBE_API_KEY=...
GROQ_API_KEY=...
```

### 3. 실행

```powershell
docker compose up -d postgres   # PostgreSQL 컨테이너 기동
python main.py                  # FastAPI 서버 (기본 :8000)
```

브라우저에서 http://localhost:8000/products 접속.

### 4. 종료

```powershell
# 서버: Ctrl+C
docker compose stop postgres   # DB 컨테이너 정지 (데이터 유지)
docker compose down -v         # 데이터까지 완전 삭제
```

## 프로젝트 구조

```
Moabom_Prototype/
├── main.py                       # FastAPI 진입점
├── scripts/                      # 운영 본체
│   ├── config.py                 #   환경변수 로딩
│   ├── api/                      #   FastAPI 라우터 (products / videos / sync)
│   ├── database/                 #   PostgreSQL 연결 / 스키마 / 쿼리 헬퍼
│   ├── youtube/                  #   YouTube API + yt-dlp 자막 추출
│   ├── analysis/                 #   감정분석 / 제품 관련도 필터
│   ├── reports/                  #   Groq Llama 보고서 생성 + PDF 출력
│   └── utils/                    #   LLM 프롬프트 템플릿
├── templates/                    # Jinja2 HTML
├── comment_filtering_agent/      # 차세대 댓글 필터 Agent (개발 중, 운영 미연결)
├── app/  services/  dags/  llm/  # 병렬 리팩터링/실험 모듈 (운영 미연결)
├── docs/                         # 설계 문서, 분석 보고서, 과제 기획서
├── docker-compose.yml            # PostgreSQL 컨테이너 정의
├── Dockerfile                    # FastAPI 앱 이미지
└── requirements.txt              # Python 의존성
```

## 주요 환경변수 (.env)

| 키 | 설명 | 기본값 |
|---|---|---|
| `DATABASE_URL` | PostgreSQL 연결 문자열 | `postgresql://postgres:postgres@localhost:5432/techdb` |
| `YOUTUBE_API_KEY` | YouTube Data API v3 키 | (필수) |
| `GROQ_API_KEY` | Groq API 키 | (필수) |
| `GROQ_MODEL` | Llama 모델명 | `llama-3.3-70b-versatile` |
| `PORT` | FastAPI 포트 | `8000` |

## 기술 스택

- **Backend**: FastAPI, uvicorn
- **DB**: PostgreSQL 15 (psycopg2)
- **외부 API**: YouTube Data API v3, Groq (Llama 3.3 70B)
- **자막**: yt-dlp + requests (json3 / vtt 직접 파싱)
- **PDF**: ReportLab + 맑은 고딕

## 데이터베이스 스키마

서버 시작 시 [scripts/database/schema.py](scripts/database/schema.py)가 자동 생성합니다.

- `tech_products` — 등록한 제품
- `videos` — 제품별 수집된 영상
- `comments` / `comment_sentiments` — 댓글 + 감정 라벨
- `video_transcripts` — 자막 캐시
- `video_reports` — LLM 생성 보고서 3종 캐시

## 트러블슈팅

| 증상 | 해결 |
|---|---|
| `connection refused` | `docker compose up -d postgres` 실행 |
| `ModuleNotFoundError` | venv 활성화 / `pip install -r requirements.txt` |
| YouTube 403 | API 키 또는 일일 할당량(10,000 units) 확인 |
| Groq `model_not_found` | `.env`의 `GROQ_MODEL`을 [최신 지원 모델](https://console.groq.com/docs/models)로 변경 |
| 포트 8000 충돌 | `python main.py 8001` |

## 참고 문서

- [docs/COMMENT_FILTERING_AGENT_DESIGN.md](docs/COMMENT_FILTERING_AGENT_DESIGN.md) — 차세대 댓글 필터 Agent 설계
=======
# Moabom — YouTube 제품 리뷰 댓글 분석 서비스

YouTube에 올라온 테크 제품 리뷰 영상의 댓글을 수집하고, 3단계 AI 파이프라인으로 필터링·분류·감성 분석하는 백엔드 서비스입니다.

---

## 무엇을 하는 서비스인가요?

제품명(예: "갤럭시 S25")을 등록하면 자동으로:

1. 관련 YouTube 영상을 선정
2. 댓글 수천 개를 수집해 노이즈(욕설, 광고, 인사말 등)를 걸러냄
3. AI가 제품 관련 댓글만 추려 긍정/부정/중립으로 분류
4. 배터리, 발열, 성능 등 항목별 세부 감성까지 분석
5. 결과를 DB에 저장 → 보고서 생성

---

## 아키텍처

```
사용자 요청 (POST /products/{id}/sync)
        │
        ▼
┌───────────────────┐
│  영상 선정 Agent   │  제품명으로 YouTube 영상 검색·선정
└───────────────────┘
        │ video_id 목록
        ▼
┌───────────────────┐
│ 댓글 필터링 Agent  │  3단계 파이프라인 (아래 상세)
└───────────────────┘
        │ DB 저장 완료
        ▼
┌───────────────────┐
│ 보고서 작성 Agent  │  분석 결과 → 보고서 생성
└───────────────────┘
```

### 댓글 필터링 파이프라인 (7단계)

```
① YouTube 댓글 수집 (최대 1,000개)
        ↓
② 전처리 (null 제거, 중복 제거, 플래그 부착)
        ↓
③ 규칙 기반 필터 — 욕설·광고·이모지 과다·인사말 등 REJECT
        ↓
④ 후보 풀 점수화 — 키워드·길이·참여도 기준으로 상위 300개 선발
        ↓
⑤ 다중기준 선발 — 좋아요·답글·최신·무작위 교차 비교로 상위 20개
        ↓
⑥ LLM 분류 (Groq) — PRODUCT_OPINION / QUESTION / VIDEO_REACTION / CHATTER 등
        ↓
⑦ 감성 분석 + 항목별 분석 (ABSA) — positive / neutral / negative + 배터리·발열 등
```

---

## 기술 스택

| 영역 | 기술 |
|------|------|
| 웹 프레임워크 | FastAPI |
| 데이터베이스 | PostgreSQL 15 |
| LLM | Groq API (llama-3.3-70b-versatile) |
| LLM 연동 | LangChain |
| YouTube 수집 | YouTube Data API v3 |
| 병렬 처리 | ThreadPoolExecutor |
| 컨테이너 | Docker / Docker Compose |

---

## 프로젝트 구조

```
Moabom_Prototype/
├── main_youtube_tech_review.py     # 서버 진입점
├── docker-compose.yml              # DB + App 컨테이너 설정
├── .env                            # API 키 (Git 제외)
│
├── scripts/
│   ├── api/
│   │   ├── sync.py                 # 핵심: 전체 파이프라인 실행
│   │   ├── products.py             # 제품 CRUD API
│   │   └── videos.py              # 영상 조회 API
│   ├── database/
│   │   ├── schema.py               # DB 테이블 정의
│   │   └── connection.py           # DB 연결
│   ├── youtube/
│   │   ├── video_service.py        # 영상 검색
│   │   └── comment_service.py      # 댓글 수집
│   └── config.py                   # 환경변수 로드
│
├── comment_filtering_agent/        # 댓글 필터링 Agent 패키지
│   ├── filters/                    # 규칙 기반 필터
│   ├── classifiers/                # LLM 분류기
│   ├── analyzers/                  # 감성 분석기 (Groq)
│   ├── core/                       # Agent 의사결정 엔진
│   └── services/                   # 댓글 수집·파이프라인 조율
│
└── md/                             # 팀 문서
    ├── COMMENT_FILTER_OUTPUT_COLUMNS.md  # DB 컬럼 명세
    └── AGENT_INTEGRATION_GUIDE.md        # Agent 연동 가이드
```

---

## 시작하기

### 사전 요구사항

- Python 3.11+
- Docker Desktop
- YouTube Data API v3 키
- Groq API 키 ([groq.com](https://groq.com) 무료 발급 가능)

### 1. 저장소 클론

```bash
git clone https://github.com/MeDeoDuck/Moabom_Prototype.git
cd Moabom_Prototype
```

### 2. 환경변수 설정

`.env` 파일을 프로젝트 루트에 생성:

```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/techdb
YOUTUBE_API_KEY=여기에_유튜브_API_키
GROQ_API_KEY=여기에_Groq_API_키
GROQ_MODEL=llama-3.3-70b-versatile
```

### 3. 데이터베이스 실행 (Docker)

```bash
docker-compose up -d postgres
```

### 4. Python 가상환경 및 패키지 설치

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Mac/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 5. 서버 실행

```bash
python main_youtube_tech_review.py
```

서버가 뜨면 `http://localhost:8000` 에서 확인 가능합니다.

---

## API 사용법

### 제품 등록

```bash
POST /products
Content-Type: application/json

{
  "name": "갤럭시 S25",
  "brand": "Samsung"
}
```

### 데이터 수집 및 분석 시작

```bash
POST /products/{product_id}/sync
Content-Type: application/json

{
  "max_results": 5
}
```

이 요청 하나로 영상 검색 → 댓글 수집 → 필터링 → 감성 분석이 자동으로 실행됩니다.

### 응답 예시

```json
{
  "status": "success",
  "videos_count": 5,
  "comments_count": 3200,
  "llm_selected_pre_count": 92,
  "llm_selected_post_count": 47
}
```

---

## DB 결과 구조

분석 완료 후 아래 테이블에 결과가 저장됩니다:

| 테이블 | 내용 |
|--------|------|
| `comments` | 수집된 원본 댓글 |
| `rule_filter_results` | 규칙 필터 PASS/REJECT 결과 |
| `llm_classifications` | LLM 분류 라벨 및 확신도 |
| `agent_decisions` | Agent 최종 판정 (ANALYZE/EXCLUDE 등) |
| `comment_sentiments` | **최종 감성 결과** (positive/neutral/negative) |
| `aspect_extractions` | 항목별 감성 (배터리, 발열, 성능 등) |

최종 분석된 댓글만 가져오는 쿼리:

```sql
SELECT c.text_raw, cs.sentiment_label, cs.sentiment_score
FROM comments c
JOIN comment_sentiments cs ON c.comment_id = cs.comment_id
JOIN videos v ON c.video_id = v.video_id
WHERE v.product_id = 1;
```

---

## 환경변수 목록

| 변수명 | 설명 | 필수 |
|--------|------|------|
| `DATABASE_URL` | PostgreSQL 연결 URL | ✅ |
| `YOUTUBE_API_KEY` | YouTube Data API v3 키 | ✅ |
| `GROQ_API_KEY` | Groq LLM API 키 | ✅ |
| `GROQ_MODEL` | 사용할 Groq 모델명 | 선택 (기본값: llama-3.1-70b-versatile) |

---

## 팀 구성

| 역할 | 담당 |
|------|------|
| 댓글 필터링 Agent | MeDeoDuck |
| 영상 선정 Agent | 팀원 A |
| 보고서 작성 Agent | 팀원 B |

Agent 연동 방법은 [md/AGENT_INTEGRATION_GUIDE.md](md/AGENT_INTEGRATION_GUIDE.md) 참고.
main
