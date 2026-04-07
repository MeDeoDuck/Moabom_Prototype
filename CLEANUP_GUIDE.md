# 파일 정리 가이드 - 안전하게 삭제 가능한 파일

## ⚠️ 반드시 유지해야 하는 것들

### 📁 필수 폴더
```
✅ scripts/              # 모든 기능 코드 (절대 삭제 금지!)
✅ templates/            # FastAPI Jinja2 템플릿 (절대 삭제 금지!)
✅ comment_filtering_agent/  # 댓글 필터링 Agent 시스템
✅ services/             # Airflow 관련 서비스
✅ dags/                 # Airflow DAG 정의
✅ app/                  # 앱 관련 코드 (확인 필요)
✅ llm/                  # LLM 프로바이더
✅ .git/                 # Git 저장소
✅ .venv_backup/         # 백업 가상환경
```

### 📄 필수 파일
```
✅ .env                  # 환경변수 (API keys, DB 정보)
✅ .gitignore            # Git 무시 파일 목록
✅ requirements.txt      # Python 패키지 의존성 (절대 삭제 금지!)
✅ requirements-airflow.txt  # Airflow 의존성
✅ README.md             # 프로젝트 설명
✅ docker-compose.yml    # Docker 설정
✅ Dockerfile            # Docker 이미지 빌드
```

### 📚 문서 파일 (유지 권장)
```
✅ MAIN_CODE_ANALYSIS.md           # 원본 코드 분석
✅ MODULARIZATION_COMPLETE.md      # 모듈화 완료 문서
✅ COMMENT_FILTERING_AGENT_DESIGN.md
✅ ARCHITECTURE.md
✅ SYSTEM_ARCHITECTURE.md
✅ README_*.md (여러 개)
```

---

## 🗑️ 삭제 가능한 파일들

### 임시 헬퍼 스크립트 (안전하게 삭제 가능)
```bash
❌ _create_examples_folder.py
❌ _create_scripts_structure.py
❌ _create_utils_folder.py
❌ _debug_category_insert.py
❌ _finalize_modularization.py
```

### 디버그 파일
```bash
❌ debug_comments.py
❌ debug_groq.py
❌ debug_output.txt
❌ pipeline_output.txt
❌ real_api_output.txt
```

### 테스트 파일
```bash
❌ test_async_classifier.py
❌ test_full_pipeline.py
❌ test_optimized_classifier.py
❌ test_pipeline_simple.py
❌ test_real_api.py
❌ test_report.py
```

### 벤치마크 파일
```bash
❌ benchmark_3way_comparison.py
❌ benchmark_classifier.py
❌ benchmark_real_api.py
❌ benchmark_results_example.py
❌ benchmark_speed_accuracy.py
❌ simple_benchmark.py
❌ run_benchmark_auto.py
```

### 유틸리티/임시 스크립트
```bash
❌ accuracy_explanation_example.py
❌ check_llm_calls.py
❌ clean_templates.py
❌ comment_report_prompt.py
❌ create_agent_structure.py
❌ export_db_to_excel.py
❌ migrate_add_integrated_report.py
❌ pipeline_runner.py
❌ rename_files.py
❌ replace_video_detail.py
❌ run_with_api_key.py
❌ toxlsx.py
❌ verify_airflow_pipeline.py
❌ verify_installation.py
```

### 중복/이동된 파일
```bash
❌ prompt_manager.py         # scripts/utils/로 이동됨
```

### 백업용으로 남겨둘지 고려해야 할 파일
```bash
⚠️  main_youtube_analysis.py   # 원본 1778줄 (백업용으로 일단 유지)
⚠️  main.py                    # 다른 엔트리포인트? (확인 필요)
```

### 데이터 파일
```bash
❌ videos.csv
❌ videos.xlsx
❌ db_export_20260406_182916.xlsx
❌ db_export_20260406_182916_csv.zip
```

### 배치 스크립트
```bash
❌ run_server.bat
❌ setup.bat
❌ setup.sh
```

### 캐시 폴더
```bash
❌ __pycache__/
```

---

## 🔍 삭제 전 확인 사항

### 1. 먼저 테스트 실행
```bash
python scripts/main_youtube_tech_review.py
```
- 서버가 정상 실행되는지 확인
- 제품 생성, 동기화, 비디오 상세 페이지 모두 테스트

### 2. 백업 생성 (권장)
```bash
# 삭제 전 전체 프로젝트 백업
cp -r Moabom_Prototype Moabom_Prototype_backup_20260407
```

### 3. Git 커밋
```bash
# 현재 상태를 Git에 커밋
git add .
git commit -m "Modularization complete - before cleanup"
```

---

## 📋 안전한 삭제 명령어

### PowerShell (Windows)
```powershell
# 임시 헬퍼 파일
Remove-Item _*.py

# 디버그 파일
Remove-Item debug_*.py, *_output.txt

# 테스트 파일
Remove-Item test_*.py

# 벤치마크 파일
Remove-Item benchmark_*.py, simple_benchmark.py, run_benchmark_auto.py

# 유틸리티 스크립트
Remove-Item accuracy_explanation_example.py, check_llm_calls.py, clean_templates.py
Remove-Item comment_report_prompt.py, create_agent_structure.py, export_db_to_excel.py
Remove-Item migrate_add_integrated_report.py, pipeline_runner.py
Remove-Item rename_files.py, replace_video_detail.py, run_with_api_key.py
Remove-Item toxlsx.py, verify_*.py

# 중복 파일
Remove-Item prompt_manager.py

# 데이터 파일
Remove-Item videos.csv, videos.xlsx, *.xlsx, *.zip

# 배치 스크립트
Remove-Item *.bat, *.sh

# 캐시
Remove-Item -Recurse __pycache__
```

---

## ✅ 삭제 후 최종 구조

```
Moabom_Prototype/
├── .env                          ✅ 환경변수
├── .gitignore                    ✅ Git 설정
├── requirements.txt              ✅ 의존성
├── requirements-airflow.txt      ✅ Airflow 의존성
├── README.md                     ✅ 프로젝트 설명
├── docker-compose.yml            ✅ Docker 설정
├── Dockerfile                    ✅ Docker 이미지
│
├── *.md                          ✅ 문서들 (유지)
│
├── scripts/                      ✅ 모든 기능 코드
├── templates/                    ✅ HTML 템플릿
├── comment_filtering_agent/      ✅ Agent 시스템
├── services/                     ✅ Airflow 서비스
├── dags/                         ✅ Airflow DAG
├── app/                          ✅ 앱 코드
├── llm/                          ✅ LLM 프로바이더
│
└── main_youtube_analysis.py      ⚠️  원본 백업 (선택)
```

---

## 🎯 결론

**삭제해도 되는 것**: 루트의 .py 파일 중 90% (임시/테스트/벤치마크)  
**절대 삭제 금지**: scripts/, templates/, .env, requirements.txt  
**권장**: 삭제 전 Git 커밋 + 전체 백업

안전하게 정리하시려면 제가 정리 스크립트를 만들어드릴까요? 🗂️
