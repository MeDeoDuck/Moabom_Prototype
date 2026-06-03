# Moabom — 유튜브 테크 리뷰 종합 분석 에이전트

다수의 유튜브 테크 제품 리뷰 영상의 **자막·댓글을 자동 수집·분석**하고, 리뷰어와 소비자
의견을 종합해 **제품 단위 7섹션 종합 보고서**를 생성하는 FastAPI 기반 멀티에이전트 서비스.

---

## 무엇을 하나

제품명(예: "갤럭시 S25")을 등록하면:

1. **영상 선정 Agent** — 관련 유튜브 영상을 정량 점수 + LLM 재정렬로 선정 (비교영상 자동 제외)
2. **댓글 필터링 Agent** — 댓글 수천 개에서 노이즈를 걸러 제품 관련 댓글만 LLM 분류·감성 분석
3. **보고서 파이프라인** — 영상별 자막/댓글 보고서를 만들고 제품 단위로 종합
4. **Supervisor 오케스트레이터** — 위 단계를 LangGraph로 지휘하고, 캐시가 있으면 즉시 반환

보고서는 4단계로 누적 생성됩니다:
**① 영상별 자막 기반 → ② 영상별 댓글 기반 → ③ 영상별 자막+댓글 통합 → ④ 제품 단위 7섹션 종합**

---

## 아키텍처

```mermaid
flowchart LR
    User([👤 사용자]) <--> Web["🖥 Jinja2 + JS"] <--> BE["⚙ FastAPI"] <--> DB[("🗄 PostgreSQL")]
    BE -. AI 분석 위임 .-> SV

    subgraph SV ["🧭 Supervisor 오케스트레이터 · LangGraph (규칙 기반 지휘)"]
        direction TB
        FR["🔍 Freshness 검사<br/>캐시 있나? · 신선한가?"]
        FR -. "캐시 적중 → 즉시 반환" .-> Done["✅ 기존 보고서"]
        FR -->|"없음/낡음 → 생성"| Engine

        subgraph Engine ["🤖 AI 분석 엔진"]
            direction TB
            A1["① 영상 선정 Agent<br/>LangGraph 8-step"]
            A2["② 댓글 필터링 Agent<br/>7-step"]
            A3["③ 보고서 생성<br/>4단계"]
            A1 --> A2 --> A3
        end
    end

    SV -. 캐시/신선도 조회 .-> DB
    Engine --> YT["📺 YouTube Data API · yt-dlp"]
    Engine --> LLM["✨ RunYourAI Gateway"]
    A3 --> DB
```

> **Supervisor가 AI 분석 엔진을 감싸**, DB 상태(자막·댓글·보고서 캐시)를 보고 "있으면 즉시
> 반환 / 없으면 보강·생성"을 규칙으로 분기한다. LLM은 각 전문 노드 *내부*에서만 호출되는
> 하이브리드 구조다.

---

## 핵심 컴포넌트

### ① 영상 선정 Agent (`video_selection_agent/`)
LangGraph StateGraph 8-step: `fetch_candidates → enrich_metadata → score_quantitative(6차원
가중합) → diversity_filter → scope_filter(비교영상 제외) → llm_rerank → finalize_selection →
generate_rationale`. 다양성 부족 시 relax 루프.

### ② 댓글 필터링 Agent (`comment_filtering_agent/`)
7-step 파이프라인: `수집(최대 1000) → 전처리(중복·null 제거) → 규칙 필터(욕설·광고 등) →
후보 풀 점수화(상위 300) → 다중기준 선발(상위 20) → LLM 5-class 분류 → Agent 판정 + ABSA
감성 분석`. 영상 단위 `ThreadPoolExecutor` 병렬 처리.

### ③ 보고서 파이프라인 (`scripts/reports/`)
영상별 ①②③ 생성 후 제품 단위 ④ 7섹션 종합 보고서. 환각 방지 4규칙 + 다중 LLM 교차 검증 +
RAG(의미 검색) + 휴리스틱 fallback. ④ 섹션: 한줄 구매판정·핵심요약·6차원 평가·합의 기반
장단점·소비자 여론·전작 대비 변화·추천/비추.

### ④ Supervisor 오케스트레이터 (`orchestrator/`)
LangGraph로 ④ 통합보고서 경로를 지휘. 흩어져 있던 "DB 캐시냐 새로 fetch냐" 판단을 단일
Freshness 정책으로 통합하고, **동일 영상 조합 + 입력 신선 시 기존 ④ 보고서를 즉시 반환**(캐시).
설계 상세는 [docs/ORCHESTRATOR_SUPERVISOR_DESIGN.md](docs/ORCHESTRATOR_SUPERVISOR_DESIGN.md).

```mermaid
flowchart LR
    S([④ 생성 요청]) --> F["inspect_freshness"] --> D1{"캐시 적중?"}
    D1 -->|적중| LC["load_cached"] --> EC([기존 보고서 반환])
    D1 -->|없음| D2{"댓글 분석됨?"}
    D2 -->|미분석| HC["heal_comments"] --> ER["ensure_reports"]
    D2 -->|완료| ER
    ER --> D3{"보고서 ≥ 2?"}
    D3 -->|부족| MI["mark_insufficient"] --> E4([400])
    D3 -->|통과| SY["synthesize<br/>(④ 합성 LLM)"] --> PS["persist"] --> E([통합보고서])
```

---

## 빠른 시작

### 1. 사전 준비
- Python **3.12+**
- Docker Desktop
- API 키:
  - [YouTube Data API v3](https://console.cloud.google.com/apis/credentials)
  - **RunYourAI API 키** — OpenAI/Claude/Gemini를 단일 키로 호출하는 LLM 통합 게이트웨이

### 2. 환경 설정
```powershell
cd Moabom_Prototype
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`.env` 파일에 키 입력 (`DATABASE_URL`은 docker 사용 시 기본값 그대로):
```
YOUTUBE_API_KEY=...
RUNYOURAI_API_KEY=...
RUNYOURAI_BASE_URL=https://api.runyour.ai/v1
RUNYOURAI_MODEL=openai/gpt-4.1-2025-04-14
```

### 3. 실행
```powershell
docker compose up -d postgres   # PostgreSQL 컨테이너 기동
python main.py                  # FastAPI 서버 (기본 :8000, python main.py 8001 로 포트 변경)
```
브라우저에서 http://localhost:8000/products 접속.

### 4. 종료
```powershell
# 서버: Ctrl+C
docker compose stop postgres    # DB 컨테이너 정지 (데이터 유지)
docker compose down -v          # 데이터까지 완전 삭제
```

---

## 프로젝트 구조

```
Moabom_Prototype/
├── main.py                       # FastAPI 진입점 (라우터 등록 + DB 자동 초기화)
├── scripts/                      # 운영 본체
│   ├── config.py                 #   환경변수 로딩 (RunYourAI / Serper / 플래그)
│   ├── api/                      #   FastAPI 라우터 (products / videos / sync / admin)
│   ├── database/                 #   PostgreSQL 연결 / 스키마 자동생성 / 쿼리 헬퍼
│   ├── youtube/                  #   YouTube API + yt-dlp 자막 추출
│   ├── reports/                  #   보고서 ①②③④ 생성 + 검증 + PDF
│   ├── rag/                      #   ④ 입력 RAG (sqlite3 벡터 + 코사인)
│   ├── llm/                      #   get_chat_llm() — RunYourAI 단일 진입점
│   └── utils/                    #   LLM 프롬프트 템플릿
├── orchestrator/                 # ★ Supervisor 오케스트레이터 (LangGraph)
│   ├── freshness.py              #   캐시/fetch 판단 단일 검사 (READ ONLY)
│   ├── runner.py                 #   run_insight_supervisor 진입점
│   └── graph/                    #   state / nodes / builder(+fallback)
├── video_selection_agent/        # 영상 선정 LangGraph Agent (8-step)
├── comment_filtering_agent/      # 댓글 필터링 Agent (7-step)
├── services/fetch_worker/        # 홈서버 워커: 자막 fetch + 비교영상 GPU 분류
├── templates/                    # Jinja2 HTML
├── docs/                         # 설계 문서
├── docker-compose.yml            # PostgreSQL 컨테이너 정의
├── Dockerfile                    # FastAPI 앱 이미지
└── requirements.txt              # Python 의존성
```

---

## 주요 환경변수 (.env)

| 키 | 설명 | 기본값 |
|---|---|---|
| `DATABASE_URL` | PostgreSQL 연결 문자열 | `postgresql://postgres:postgres@localhost:5432/techdb` |
| `YOUTUBE_API_KEY` | YouTube Data API v3 키 | (필수) |
| `RUNYOURAI_API_KEY` | RunYourAI API 키 (LLM 통합 게이트웨이) | (필수) |
| `RUNYOURAI_BASE_URL` | RunYourAI 엔드포인트 | `https://api.runyour.ai/v1` |
| `RUNYOURAI_MODEL` | 기본 LLM 모델 (`provider/model` 형식) | `openai/gpt-4.1-2025-04-14` |
| `REPORT4_INPUT_EXPANSION` | ④ 입력 확장(①②③ 종합) on/off | `1` |
| `REPORT4_RAG` | ④ 생성 RAG on/off | `1` |
| `PORT` | FastAPI 포트 | `8000` |

> 모델·base_url·키 교체 시 `scripts/llm/__init__.py` + `scripts/config.py` 두 곳만 수정하면 된다.

---

## 기술 스택

- **Backend**: FastAPI + uvicorn + Pydantic
- **DB**: PostgreSQL 15 (`psycopg2-binary`) — 기동 시 스키마 자동 생성
- **LLM**: RunYourAI 통합 게이트웨이 (OpenAI/Claude/Gemini 단일 키, 기본 GPT-4.1) — `langchain-openai`(`ChatOpenAI` + `base_url`)로 호출
- **에이전트 프레임워크**: LangGraph (영상 선정 + Supervisor 오케스트레이터)
- **자막**: yt-dlp + requests (json3 / vtt 직접 파싱)
- **RAG**: sqlite3 벡터 저장소 + 순수 파이썬 코사인 (PostgreSQL과 분리)
- **PDF**: ReportLab + 맑은 고딕
- **병렬 처리**: ThreadPoolExecutor (댓글 영상 단위) / asyncio (보고서 self-healing)

---

## 데이터베이스 스키마

서버 시작 시 [scripts/database/schema.py](scripts/database/schema.py)가 자동 생성합니다. 주요 테이블:

| 영역 | 테이블 |
|---|---|
| 제품·영상 | `tech_products`, `videos`, `video_transcripts` |
| 영상 선정 | `video_selection_runs`, `video_selection_scores` |
| 댓글 분석 | `comments`, `rule_filter_results`, `llm_classifications`, `agent_decisions`, `comment_sentiments`, `aspect_extractions`, `aspect_definitions` |
| 보고서 | `video_reports`, `product_integrated_reports` |
| 기타 | `product_meta_cache`, `suggest_cache`, `usage_events` |

---

## 주요 API

| 메서드·경로 | 설명 |
|---|---|
| `POST /products` | 제품 등록 |
| `POST /products/{id}/select-videos` | 영상 선정 Agent 실행 + 선정 영상 댓글 처리 |
| `POST /products/{id}/integrated-insight` | ④ 통합보고서 생성 (Supervisor 지휘, 캐시 적중 시 즉시 반환, `{"force": true}`로 강제 재생성) |
| `GET /products/{id}/integrated-insight/latest` | 최신 ④ 보고서 조회 |
| `POST /products/{id}/sync` | (레거시) 영상+댓글 일괄 재수집 |

---

## 트러블슈팅

| 증상 | 해결 |
|---|---|
| `connection refused` | `docker compose up -d postgres` 실행 |
| `ModuleNotFoundError` | venv 활성화 / `pip install -r requirements.txt` |
| YouTube 403 | API 키 또는 일일 할당량(10,000 units) 확인 |
| RunYourAI 4xx / model 오류 | `.env`의 `RUNYOURAI_API_KEY` 확인, `RUNYOURAI_MODEL`은 `provider/model` 형식(예: `openai/gpt-4.1-2025-04-14`) |
| 자막 429 | 자막은 비공식 `timedtext` 엔드포인트라 IP 레이트리밋. 홈서버 워커(주거용 IP) + 쿠키로 우회 |
| 포트 8000 충돌 | `python main.py 8001` |

---

## 참고 문서

- [docs/ORCHESTRATOR_SUPERVISOR_DESIGN.md](docs/ORCHESTRATOR_SUPERVISOR_DESIGN.md) — Supervisor 오케스트레이터 설계 (구조도 포함)
- [docs/VIDEO_SELECTION_AGENT_DESIGN.md](docs/VIDEO_SELECTION_AGENT_DESIGN.md) — 영상 선정 Agent 설계
- [docs/COMMENT_FILTERING_AGENT_DESIGN.md](docs/COMMENT_FILTERING_AGENT_DESIGN.md) — 댓글 필터링 Agent 설계
