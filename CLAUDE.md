# Moabom — Claude 작업 가이드

## 프로젝트 개요
**과제명**: 유튜브 테크 리뷰 종합 분석 에이전트 ("모아봄"). 다수의 유튜브 테크 리뷰 영상의 자막·댓글을 자동 수집·분석해 리뷰어별 성향(엄격/관대) 보정까지 반영한 제품 단위 종합 보고서를 제공하는 B2C 웹 서비스 MVP.

**핵심 파이프라인**: 사용자 입력 → 리뷰 영상 후보 수집 → 텍스트 전처리 → AI 분석 파이프라인 → 분석 결과 제공. 댓글은 3단계 필터(규칙 기반 → LLM Few-shot 분류 → LangChain Agent 분기), 보고서는 4종(①자막 기반 ②댓글 기반 ③자막+댓글 통합 ④제품 단위 RAG 종합).

## 팀 협업 규칙 (중요)
- **3인 1팀**으로 GitHub(branch/PR) 기반 협업 중
- **새 기능을 구현할 땐 반드시 main에서 분기한 새 브랜치에서 작업**할 것. main 직접 커밋 금지. 브랜치 네이밍은 `feature/xxx`(기능), `fix/xxx`(버그), `docs/xxx`·`chore/xxx`(문서·잡일) 등 prefix 사용. 작업 완료 시 PR을 통해 머지.
- 다른 팀원이 작성한 코드는 **최소한으로만 수정**할 것. 인터페이스 변경이 불가피하면 먼저 공유.
- 각자 맡은 기능은 **전용 폴더/파일을 새로 만들어 모듈화**된 형태로 구현. 기존 파일에 로직 섞지 말 것.
- 비기능 요구사항 NR-007/012: 모델·모듈 교체 시 기존 시스템 수정이 최소화되도록 의존성을 얇게 유지.

## 기술 스택 (현 구현 기준)
**스택이 변경될 때마다 이 섹션(및 관련 문서)을 즉시 업데이트할 것.** 명세서 임시안과 현 구현이 갈리는 항목이 많으므로 아래 "현 구현"을 기준으로 작업.

- Frontend: **Jinja2 HTML templates** (`templates/`) — 명세 임시안 React/TypeScript는 미적용
- Backend: FastAPI (Python)
- DB: **PostgreSQL** (`psycopg2-binary`)
- 데이터 수집: YouTube Data API, `youtube-transcript-api`, `yt-dlp`
- LLM: **Azure OpenAI GPT-4.1-mini** (메인) — 댓글 분류·감성 분석, 영상 선택 Agent, 보고서 생성 등 모든 LLM 호출에 사용
  - 환경변수: `AZURE_OPENAI_ENDPOINT/API_KEY/DEPLOYMENT/API_VERSION`
  - 호출 경로: `langchain-core` + `langchain-openai`(`AzureChatOpenAI`)
  - commit `32d6e55`에서 Groq Llama 사용처를 모두 Azure OpenAI로 이관 (Groq은 deprecated, 코드만 잔존)
- 에이전틱 워크플로우: **LangGraph** (`video_selection_agent/graph/`, FR-005 영상 선택 StateGraph)
- MLOps: Airflow 실험 단계 (`dags/youtube_product_sync_dag.py`) — 운영 미연결
- 명세 임시안 중 **미적용/미구현**: Redis, VectorDB, Gemini, Transformers, scikit-learn, vLLM, RAG, ELK

## 저장소 구조
```
main.py                       # FastAPI 진입점
scripts/                      # 운영 본체 (api / database / youtube / analysis / reports / utils)
comment_filtering_agent/      # 댓글 3단계 필터 Agent (filters / classifiers / analyzers / core)
app/  services/  dags/  llm/  # 병렬 리팩터링·실험 모듈 (운영 미연결)
templates/                    # Jinja2 HTML
docs/                         # 과제 기획서, 요구사항명세서, 설계 문서
```

## 참고 문서
- [README.md](README.md) — 실행·환경 설정
- [docs/요구사항명세서_모아봄_v5.pdf](docs/요구사항명세서_모아봄_v5.pdf) — FR-001~025, NR-001~015 전체 명세
- [docs/인공지능종합설계_과제기획서_모아봄.pdf](docs/인공지능종합설계_과제기획서_모아봄.pdf) — 배경·범위·일정·역할 분담
- [docs/COMMENT_FILTERING_AGENT_DESIGN.md](docs/COMMENT_FILTERING_AGENT_DESIGN.md) — 댓글 필터 Agent 설계
