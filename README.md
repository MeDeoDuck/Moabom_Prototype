# 모아봄 (Moabom)

> **유튜브 테크 리뷰 종합 분석 에이전트** — 한 제품에 대한 여러 리뷰 영상의 자막과 댓글을 자동으로 수집·분석해, 리뷰어 합의 의견과 소비자 여론을 함께 보여주는 **제품 단위 7섹션 종합 보고서**를 생성하는 B2C 웹 서비스 MVP.

인하대학교 인공지능공학과 캡스톤디자인 프로젝트 (2026, 3인 팀).

---

## 왜 만들었나

테크 제품을 살 때 유튜브 리뷰 N개를 일일이 보는 시간을 줄이는 것이 출발점. **여러 리뷰어가 공통으로 지적하는 장단점**(합의 빈도 N/N)과 **실사용자 댓글 여론**을 한 화면에서 비교할 수 있도록, 두 흐름을 별도 파이프라인으로 모아 한 보고서로 합친다.

## 핵심 기능

| | 설명 |
|---|---|
| **영상 선정 Agent** | 제품 키워드 → YouTube 후보 수집 → 6차원 정량 점수 + 다양성 필터 + **비교영상 자동 제외(scope filter)** + LLM Re-rank → 최종 영상 N개 선정 (LangGraph 8-step) |
| **댓글 필터링 Agent** | 영상별 댓글 수집 → 12종 룰 기반 노이즈 제거 → Top 300 후보 가공 → 6기준 Multi-Criteria 선정 → LLM 5-class 분류 → ABSA 감성 분석 (7-step, ThreadPool 병렬) |
| **보고서 파이프라인** | 4단계 누적 생성: ① 영상별 자막 보고서 → ② 영상별 댓글 보고서 → ③ 영상별 통합 → ④ **제품 단위 7섹션 종합** (구매 판정 · 핵심 요약 · 6차원 평가표 · 합의 기반 장단점 · 소비자 여론 · 전작 대비 변화 · 추천/비추) |
| **Supervisor 오케스트레이터** (부분) | **보고서 ④ 생성 경로**를 **LangGraph로 지휘**(전 과정 아님 — 영상 선정은 독립). 흩어져 있던 "DB 캐시냐 새로 fetch냐" 판단을 단일 Freshness 정책으로 통합 → 동일 영상 조합·입력 신선 시 기존 ④ **즉시 반환(캐시)**, 없으면 자동 보강·생성 (`force`로 강제 재생성). 기존 에이전트·YouTube API 무수정 래핑 |
| **Self-Healing** | 보고서 ④ 생성 시 자막·댓글 누락 영상을 감지해 자동 재수집 (`asyncio.gather` 병렬). 일부 영상 실패는 격리되어 전체 생성에 영향 없음 |
| **DB 캐시 (FR-020)** | 동일 제품 재요청은 2초 이내 DB 캐시 응답. 자막은 `video_transcripts`에 영구 캐시 |

## 시스템 아키텍처

**부분 Supervisor 구조를 포함한 멀티 에이전트 워크플로우** — 영상 선정 · 댓글 필터링 · 보고서 에이전트가 순차 협업하고, 그중 **보고서 ④ 생성 경로**를 LangGraph Supervisor가 오케스트레이션한다 (영상 선정은 독립 라우트로 동작 — 전 과정을 한 Supervisor가 조율하지는 않음).

```
사용자 입력 (제품명)
      ↓
[영상 선정 Agent — LangGraph]
  fetch → enrich → score(6차원) → diversity → scope_filter → LLM Re-rank → finalize → rationale
      ↓
[자막 수집] yt-dlp / youtube-transcript-api  ←─ 자취방 데스크탑 fetch worker (datacenter IP 우회)
[댓글 수집] YouTube Data API v3
      ↓
[댓글 필터링 Agent — 7-step]
  collect → preprocess → rule filter → Top 300 → multi-criteria → LLM 5-class → ABSA
      ↓
┌─[Supervisor 오케스트레이터 — LangGraph]──────────────────────────────────┐
│  Freshness 검사 (DB 캐시/신선도 단일 판단)                                │
│    캐시 적중? ──예──▶ 기존 ④ 보고서 즉시 반환                             │
│    └─아니오─▶ 자막·댓글 self-heal → 보고서 생성 → 저장                    │
│                                                                          │
│  [보고서 파이프라인 v2]                                                   │
│    ① 자막 보고서 → ② 댓글 보고서 → ③ 영상 통합 → ④ 제품 7섹션 종합        │
│      ├─ Phase 1: 4종 보고서 다중 LLM 교차 검증 (환각 최소화)              │
│      ├─ Phase 2-b: RAG 의미 검색·재정렬 (sqlite3 + RunYourAI 임베딩)      │
│      └─ Phase 3: Serper Google Images + 비전 LLM 제품 이미지 검증         │
└──────────────────────────────────────────────────────────────────────────┘
      ↓
PostgreSQL (17 tables, Schema Auto-init)  →  Jinja2 화면
```

## 기술적 포인트

- **LangGraph StateGraph로 영상 선정 에이전트화** — 8단계 노드를 그래프로 분리해 노드별 교체·관측 용이. 6차원 정량 점수(조회수·좋아요·최신성·구독자·길이·관련도)와 LLM Re-rank 결합.
- **LangGraph 부분 Supervisor 오케스트레이터** — 전 과정이 아니라 **보고서 ④ 생성 경로**(댓글 self-heal + 보고서 생성)만 라우트에서 그래프로 분리해 지휘(`orchestrator/`). 영상 선정 Agent는 독립 라우트로 동작. 함수마다 흩어져 있던 "DB 캐시냐 fetch냐" 판단을 **단일 Freshness 정책(READ ONLY)** 으로 통합하고, 동일 영상 조합·입력 신선 시 기존 ④를 **즉시 반환(캐시)**. 분기는 LLM이 아닌 규칙 기반(빠르고 결정론적), LLM은 각 전문 노드 내부에서만 호출. 기존 에이전트 내부·YouTube API 무수정 블랙박스 래핑, langgraph 미설치 시 fallback (NR-007/012).
- **비교영상 자동 제외(scope filter)** — 자취방 데스크탑 GPU 워커(`klue/roberta-large` 파인튜닝, test acc 89.94%)를 HTTP로 호출해 "여러 제품 비교/랭킹 영상"을 후보에서 제외. `SCOPE_FILTER_ENABLED=0` 킬 스위치, 워커 부재 시 pass-through.
- **하이브리드 자막 fetch worker** — Azure datacenter IP의 YouTube 봇 차단을 우회하기 위해 자취방 데스크탑(`services/fetch_worker`)에 자막 수집과 scope 분류를 위임. 메인 앱은 워커 미응답 시 안전 퇴화.
- **환각 방지 4규칙 + 다중 LLM 교차 검증** — 보고서 ④는 ① 근거 명시 ② 합의도 정량화(N/N) ③ 등장 제품만 비교 ④ 데이터 부족 명시. 4종 보고서 모두 별도 LLM으로 교차 검증 후 적재. 검증 실패 시 Heuristic Fallback("데이터 부족" 모드) 자동 전환.
- **RAG (sqlite3 + RunYourAI 임베딩)** — pgvector 의도적 미선택. 보고서 ④ 입력 절삭을 의미 검색·재정렬로 대체해 토큰 예산 안에서 더 관련성 높은 청크 유지. 실패 시 절삭으로 안전 퇴화.
- **단일 LLM 게이트웨이** — 모든 LLM 호출이 `scripts/llm/__init__.py:get_chat_llm()` 한 점을 통과(RunYourAI / OpenAI 호환 endpoint). 모델 교체·실험·비용 추적이 한 줄에서 끝남. (이전엔 Azure OpenAI / Groq Llama 등 산재 → PR #15에서 통합)
- **댓글 LLM → on-prem distillation PoC** — RunYourAI GPT-4.1 댓글 분류를 `klue/roberta-large`로 증류해 일치율 86.5% · 22× speedup · 비용 99% 절감 검증 완료(50제품 N=994 벤치). 운영 통합 대기.
- **운영 인프라** — Azure Container Apps (FastAPI, min=2/max=5 replicas) + Azure PostgreSQL Flexible Server + Azure Container Registry + Log Analytics. v1 사용자 설문 배포로 검증 완료.

## 기술 스택

| 영역 | 사용 기술 |
|---|---|
| Backend | FastAPI · Uvicorn · Pydantic |
| Frontend | Jinja2 HTML templates · Vanilla JS · Markdown 렌더링 |
| DB | PostgreSQL 15 (psycopg2-binary) · 17 tables · Schema Auto-init |
| LLM | **RunYourAI 통합 게이트웨이** (`openai/gpt-4.1-2025-04-14`) · langchain-openai · LangGraph |
| 오케스트레이션 | LangGraph (영상 선정 Agent · 보고서 ④ Supervisor) |
| 데이터 수집 | YouTube Data API v3 · youtube-transcript-api · yt-dlp |
| ML 보조 | klue/roberta-large (scope-classifier, 별 repo) · 텍스트 임베딩 (text-embedding-3-small) |
| 검색 | Serper Google Images / Web Search (제품 이미지·검색 후보 제안) |
| 인프라 | Azure Container Apps · Azure PG Flexible Server · ACR · Log Analytics · Docker / docker-compose |
| 회귀 안전망 | pytest + Phase 0 contract/golden 테스트 (`regression/`) |

## 프로젝트 구조

```
Moabom_Prototype/
├── main.py                       # FastAPI 진입점
├── scripts/                      # 운영 본체
│   ├── config.py                 #   환경변수 단일 진입점
│   ├── api/                      #   라우터 (products / videos / sync / suggest 등)
│   ├── database/                 #   PG 연결·스키마(자동 init)·쿼리 헬퍼
│   ├── youtube/                  #   YouTube API + yt-dlp 자막 (+ worker 클라이언트)
│   ├── analysis/                 #   감성·제품 관련도 보조
│   ├── llm/                      #   LLM 단일 진입점 (get_chat_llm)
│   ├── reports/                  #   4단계 보고서 생성 + 다중 LLM 검증
│   ├── rag/                      #   Phase 2-b RAG (sqlite3 벡터)
│   ├── product_image/            #   Phase 3 제품 이미지 검색·비전 검증
│   ├── popup/  tracking/         #   팝업 메타 / 사용량 추적
│   └── utils/                    #   프롬프트·공용 유틸
├── orchestrator/                 # 보고서 ④ Supervisor 오케스트레이터 (LangGraph)
│   ├── freshness.py              #   캐시/fetch 단일 판단 (READ ONLY)
│   ├── graph/                    #   state · nodes · builder(+ langgraph 미설치 fallback)
│   └── runner.py                 #   run_insight_supervisor 진입점
├── video_selection_agent/        # 영상 선정 LangGraph Agent
│   ├── graph/ scoring/ youtube/ llm/ persistence/ api/ scope_filter/
├── comment_filtering_agent/      # 댓글 7-step 필터 Agent
│   ├── filters/ classifiers/ analyzers/ core/ prompts/ services/
├── services/fetch_worker/        # 홈서버 워커: /transcript + /scope-classify
├── regression/                   # Phase 0 회귀 안전망 (pytest)
├── templates/                    # Jinja2 HTML
├── seeds/                        # 제품 시드 데이터·검색 캐시
├── data/                         # 댓글 distillation 라벨 데이터 등
├── docs/                         # 기획서·요구사항명세서·설계 문서·중간보고서
├── app/  dags/  llm/  infra/     # 병렬 리팩터링·Airflow 실험 (운영 미연결)
├── docker-compose.yml            # 로컬 PG + 앱 컨테이너
├── Dockerfile                    # FastAPI 앱 이미지
├── requirements.txt              # 운영 의존성
└── requirements-dev.txt          # 회귀 테스트용 dev 의존성
```

## 빠른 시작

### 사전 준비

- Python 3.12+
- Docker (PostgreSQL 컨테이너용)
- API 키
  - [YouTube Data API v3](https://console.cloud.google.com/apis/credentials) (필수)
  - [RunYourAI](https://runyour.ai) API 키 (필수)
  - [Serper](https://serper.dev) API 키 (선택, 제품 이미지 검색)

### 설치 & 실행 (Linux / macOS / WSL)

```bash
git clone https://github.com/moabom-official/Moabom_Prototype.git
cd Moabom_Prototype

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# .env 편집: YOUTUBE_API_KEY, RUNYOURAI_API_KEY 입력

docker compose up -d postgres   # PG 컨테이너 기동 (포트 5432)
python main.py                  # FastAPI 기동 (기본 :8000)
```

브라우저에서 http://localhost:8000 접속.

### Windows PowerShell

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# .env 편집 후
docker compose up -d postgres
python main.py
```

### 전체 컨테이너 실행 (앱 + DB)

```bash
docker compose up -d            # app + postgres
docker compose logs -f app
```

### 종료

```bash
docker compose stop postgres    # 데이터 유지
docker compose down -v          # 데이터까지 삭제
```

## 환경변수

`.env.example`에 전체 목록과 기본값이 정리되어 있다. 핵심만 발췌:

| 키 | 필수 | 설명 |
|---|---|---|
| `DATABASE_URL` | ✓ | PostgreSQL 연결 문자열 |
| `YOUTUBE_API_KEY` | ✓ | YouTube Data API v3 |
| `RUNYOURAI_API_KEY` | ✓ | 모든 LLM 호출 단일 키 |
| `RUNYOURAI_MODEL` | | 기본 `openai/gpt-4.1-2025-04-14` (provider/model 형식) |
| `SERPER_API_KEY` | | Phase 3 제품 이미지. 미설정 시 이미지 없이 안전 퇴화 |
| `REPORT_VERIFICATION_ENABLED` | | 보고서 다중 LLM 검증 on/off |
| `REPORT4_INPUT_EXPANSION` | | 보고서 ④ 입력 확장(영상별 ①②③ 종합) on/off |
| `REPORT4_RAG` | | 보고서 ④ RAG on/off (off 시 절삭 fallback) |
| `PRODUCT_IMAGE_ENABLED` | | 제품 이미지 수집 on/off |
| `SCOPE_FILTER_ENABLED` | | 영상 선정 비교영상 제외 on/off |
| `YOUTUBE_FETCH_WORKER_URL`<br>`YOUTUBE_FETCH_WORKER_TOKEN` | | 홈서버 자막 worker 연동 (선택) |

## 데이터베이스

서버 기동 시 `scripts/database/schema.py`가 17개 테이블을 자동 생성한다.

| 카테고리 | 테이블 |
|---|---|
| 제품·영상 | `tech_products` · `videos` · `video_transcripts` · `video_reports` |
| 영상 선정 | `video_selection_runs` · `video_selection_scores` |
| 댓글 필터 | `comments` · `comment_sentiments` · `rule_filter_results` · `llm_classifications` · `agent_decisions` |
| ABSA | `aspect_definitions` · `aspect_extractions` |
| 보고서 | `product_integrated_reports` (INSERT 누적, UPSERT 아님) |
| 운영 | `usage_events` · `product_meta_cache` · `suggest_cache` |

## 팀 & 역할

| 멤버 | 역할 |
|---|---|
| **김유현** (팀장) | 프로젝트 설계 · UI/UX · 영상 선정 Agent · scope-classifier |
| **김재현** | 백엔드 아키텍처 · DB 설계 · 댓글 필터링 Agent |
| **한상민** | 보고서 생성 파이프라인 · Self-Healing · 검증 로직 |

### 협업 규칙
- **반드시 main에서 분기한 새 브랜치에서 작업** (`feature/*`, `fix/*`, `docs/*`, `chore/*`). main 직접 커밋 금지.
- 다른 팀원 코드는 **최소한으로만** 수정. 인터페이스 변경 전 공유.
- 각자 담당 기능은 **전용 폴더/파일로 모듈화** (NR-007/012: 모델·모듈 교체 시 영향 최소화).

## 트러블슈팅

| 증상 | 해결 |
|---|---|
| `connection refused` | `docker compose up -d postgres` 실행 후 재시도 |
| `ModuleNotFoundError` | venv 활성화 / `pip install -r requirements.txt` |
| YouTube 403 / 할당량 초과 | API 키 또는 일일 할당량(10,000 units) 확인 |
| RunYourAI 400 `model should be in provider/model format` | `RUNYOURAI_MODEL`을 `openai/...`, `claude/...`, `gemini/...` 형식으로 |
| 자막 fetch 차단 | `.env`에 `YT_COOKIES_PATH` 또는 `YT_COOKIES_B64` 설정, 혹은 fetch worker 연동 |
| 포트 8000 충돌 | `PORT=8001 python main.py` |
| 보고서 ④에 "데이터 부족" 다수 | 영상 선정 N 확인 / scope filter 과제외 여부 확인 (`SCOPE_FILTER_ENABLED=0`로 테스트) |

## 참고 문서

- [docs/중간보고서_모아봄_최종.pdf](docs/중간보고서_모아봄_최종.pdf) — **현 시점 가장 최신**. 시스템 아키텍처·시퀀스·UI 와이어프레임·진행 현황·기여도
- [docs/중간발표_모아봄.pdf](docs/중간발표_모아봄.pdf) — 발표 자료 (Appendix에 댓글 필터 Step 02~07 상세)
- [docs/요구사항명세서_모아봄_v5.pdf](docs/요구사항명세서_모아봄_v5.pdf) — FR-001~025, NR-001~015 전체 명세
- [docs/인공지능종합설계_과제기획서_모아봄.pdf](docs/인공지능종합설계_과제기획서_모아봄.pdf) — 배경·범위·일정·역할 분담
- [docs/ORCHESTRATOR_SUPERVISOR_DESIGN.md](docs/ORCHESTRATOR_SUPERVISOR_DESIGN.md) — 보고서 ④ Supervisor 오케스트레이터 설계 (구조도 포함)
- [docs/COMMENT_FILTERING_AGENT_DESIGN.md](docs/COMMENT_FILTERING_AGENT_DESIGN.md) — 댓글 필터 Agent 설계
- [docs/VIDEO_SELECTION_AGENT_DESIGN.md](docs/VIDEO_SELECTION_AGENT_DESIGN.md) — 영상 선정 Agent 설계 (`docs/assets/video_selection_agent_flowchart.png` 다이어그램)
