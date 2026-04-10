# 모듈화 완료 구조 - YouTube Tech Review System

## 📁 최종 폴더 구조

```
Moabom_Prototype/
├── .env                              # 환경변수 (DB, API keys)
├── templates/                        # Jinja2 HTML 템플릿
│   ├── products.html
│   ├── product_detail.html
│   └── video_detail.html
│
└── scripts/                          # 🎯 모든 기능 모듈화 완료
    ├── config.py                     # 환경변수 설정
    │
    ├── database/                     # 데이터베이스 계층
    │   ├── __init__.py
    │   ├── connection.py             # PostgreSQL 연결 (UTF-8)
    │   ├── schema.py                 # init_db(), 테이블 생성
    │   └── queries.py                # query_one(), query_all(), execute_*()
    │
    ├── youtube/                      # YouTube API 계층
    │   ├── __init__.py
    │   ├── video_service.py          # fetch_product_videos()
    │   ├── comment_service.py        # fetch_video_comments()
    │   └── transcript_service.py     # fetch_video_transcript()
    │
    ├── analysis/                     # 분석 계층
    │   ├── __init__.py
    │   ├── sentiment.py              # analyze_sentiment() - 규칙 기반
    │   └── product_filter.py         # is_product_related()
    │
    ├── reports/                      # 보고서 생성 계층
    │   ├── __init__.py
    │   ├── transcript_report.py      # build_transcript_report() - Groq Llama
    │   ├── comment_report.py         # build_comment_sentiment_report()
    │   ├── integrated_report.py      # build_integrated_analysis_report()
    │   │                             # generate_and_save_all_reports()
    │   └── pdf_generator.py          # render_report_pdf() - ReportLab
    │
    ├── utils/                        # 유틸리티
    │   ├── __init__.py
    │   └── prompt_manager.py         # LLM 프롬프트 템플릿
    │
    ├── api/                          # FastAPI 라우트 (모듈화)
    │   ├── __init__.py
    │   ├── products.py               # 제품 관련 라우트
    │   ├── videos.py                 # 비디오 상세 + PDF 다운로드
    │   └── sync.py                   # YouTube 데이터 동기화
    │
    └── main_youtube_tech_review.py  # 🚀 메인 진입점
```

## ✅ 완료된 모듈화 작업

### 1. Database Layer (database/)
- ✅ `connection.py`: PostgreSQL 연결 관리, UTF-8 인코딩
- ✅ `schema.py`: 6개 테이블 생성, 마이그레이션 로직
- ✅ `queries.py`: 쿼리 헬퍼 함수 (query_one, query_all, execute_insert, execute_update)

### 2. YouTube API Layer (youtube/)
- ✅ `video_service.py`: YouTube 비디오 검색
- ✅ `comment_service.py`: 댓글 수집 (페이지네이션)
- ✅ `transcript_service.py`: 자막 수집 (yt-dlp + exponential backoff)

### 3. Analysis Layer (analysis/)
- ✅ `sentiment.py`: 규칙 기반 감정 분석 (positive/neutral/negative)
- ✅ `product_filter.py`: 제품 관련 댓글 필터링

### 4. Reports Layer (reports/)
- ✅ `transcript_report.py`: 자막 기반 리뷰어 분석 (Groq Llama + heuristic fallback)
- ✅ `comment_report.py`: 댓글 감정 분석 보고서
- ✅ `integrated_report.py`: 리뷰어 vs 소비자 통합 분석 (유사도 계산)
- ✅ `pdf_generator.py`: PDF 다운로드 생성 (ReportLab + Korean font)

### 5. Utils Layer (utils/)
- ✅ `prompt_manager.py`: LLM 프롬프트 템플릿 (중앙집중식 관리)

### 6. API Layer (api/)
- ✅ `products.py`: 제품 목록, 생성, 상세 페이지 라우트
- ✅ `videos.py`: 비디오 상세 페이지, PDF 다운로드 3개 (transcript/comment/integrated)
- ✅ `sync.py`: YouTube 데이터 동기화 (비디오 + 댓글 + 감정분석)

### 7. Main Entry Point
- ✅ `main_youtube_tech_review.py`: FastAPI 앱 초기화, 라우트 등록, 서버 실행

## 🔧 핵심 기술 결정

### Import 구조
- **모든 import는 scripts.* 형식으로 통일**
- 예: `from scripts.database.queries import query_one`
- 예: `from scripts.reports.integrated_report import generate_and_save_all_reports`

### 외부 의존성
- **제거**: 루트의 `prompt_manager.py` → `scripts/utils/prompt_manager.py`로 이동
- **유지**: 루트의 `templates/` 폴더 (FastAPI Jinja2Templates가 사용)
- **유지**: 루트의 `.env` (환경변수)

### 데이터 흐름
```
사용자 요청
    ↓
FastAPI (main_youtube_tech_review.py)
    ↓
API Routes (api/*.py)
    ↓
Service Layer (youtube/*.py, reports/*.py)
    ↓
Database Layer (database/*.py)
    ↓
PostgreSQL
```

## 🚀 실행 방법

### 기본 실행 (포트 8000)
```bash
python scripts/main_youtube_tech_review.py
```

### 커스텀 포트
```bash
python scripts/main_youtube_tech_review.py 8001
```

### 실행 시 출력
```
======================================================================
  YouTube Tech Product Review Analysis Service
  Modularized version - All code in scripts/ folder
======================================================================
  🚀 Starting server on http://0.0.0.0:8000
  📁 Project root: C:\Users\seank\OneDrive\Desktop\Moabom_Prototype
  📋 Templates: templates
======================================================================

[STARTUP] Initializing database...
[STARTUP] Database ready
[STARTUP] Registering API routes...
[STARTUP] All routes registered
```

## 📊 데이터베이스 스키마

### 6개 테이블
1. **tech_products**: 제품 정보
2. **videos**: YouTube 비디오 메타데이터
3. **comments**: 댓글 원본
4. **comment_sentiments**: 댓글 감정 분석 결과 (캐시)
5. **video_transcripts**: 자막 데이터
6. **video_reports**: 생성된 보고서 (transcript_report, comment_report, integrated_report)

## 🔄 주요 워크플로우

### 1. 제품 생성
1. 사용자가 제품명 입력 → POST /products
2. DB에 tech_products 레코드 생성

### 2. 데이터 동기화 (Sync)
1. POST /products/{id}/sync
2. YouTube API로 비디오 검색 (youtube/video_service.py)
3. 각 비디오의 댓글 수집 (youtube/comment_service.py)
4. 댓글 감정 분석 (analysis/sentiment.py) → DB 저장
5. 자막은 on-demand로 수집 (비디오 상세 페이지 접근 시)

### 3. 비디오 상세 페이지
1. GET /products/{id}/videos/{video_id}
2. 자막 미존재 시 자동 수집 (youtube/transcript_service.py)
3. 보고서 3개 생성/캐시 (reports/integrated_report.py)
   - transcript_report (자막 기반 리뷰어 분석)
   - comment_report (댓글 감정 분석)
   - integrated_report (리뷰어 vs 소비자 비교)
4. UI 렌더링 (templates/video_detail.html)

### 4. PDF 다운로드
1. GET /products/{id}/videos/{video_id}/transcript-report.pdf
2. DB에서 캐시된 보고서 조회 (video_reports 테이블)
3. PDF 생성 (reports/pdf_generator.py)
4. 파일 다운로드 응답

## 🎯 모듈화 이점

### 1. 유지보수성
- 각 기능이 독립된 파일로 분리
- 책임 명확: database/, youtube/, reports/ 등
- 수정 시 영향 범위 최소화

### 2. 테스트 용이성
- 각 모듈을 독립적으로 테스트 가능
- Mock 객체 주입 쉬움

### 3. 확장성
- 새로운 기능 추가 시 해당 폴더에 파일 추가
- 기존 코드 수정 최소화

### 4. 협업 효율
- 폴더별로 담당자 분리 가능
- Merge conflict 최소화

## 🔍 다음 정리 단계

### 루트 폴더 정리 (향후 작업)
```bash
# 삭제 가능한 파일들 (scripts/로 이동 완료)
- main_youtube_analysis.py (원본 파일)
- prompt_manager.py (scripts/utils/로 이동)
- _create_scripts_structure.py (임시 헬퍼)
- _finalize_modularization.py (임시 헬퍼)
- debug_*.py (디버그 파일들)
- test_*.py (테스트 파일들)
- benchmark_*.py (벤치마크 파일들)

# 유지할 파일들
- .env
- requirements.txt
- README.md
- templates/ (FastAPI 의존)
- comment_filtering_agent/ (별도 agent 시스템)
- services/ (Airflow 관련)
- dags/ (Airflow DAG)
```

## 📝 현재 상태

✅ **완료**: scripts/ 폴더에 모든 기능 모듈화 완료
✅ **완료**: main_youtube_tech_review.py 메인 파일 생성
✅ **완료**: 모든 import scripts.* 형식으로 통일
⏳ **다음**: 테스트 실행 및 검증
⏳ **다음**: 루트 폴더 임시 파일 정리

---

**문서 작성일**: 2026-04-07  
**작성자**: GitHub Copilot CLI  
**버전**: v1.0 (Modularized)
