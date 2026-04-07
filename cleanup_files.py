"""
안전하게 삭제 가능한 파일 목록
실행 후 정상 작동 확인했으면 이 파일들을 삭제해도 됩니다.
"""

# ============================================================================
# 🗑️ 안전하게 삭제 가능한 파일들
# ============================================================================

SAFE_TO_DELETE = [
    # 임시 헬퍼 스크립트
    "_create_examples_folder.py",
    "_create_scripts_structure.py",
    "_create_utils_folder.py",
    "_debug_category_insert.py",
    "_finalize_modularization.py",
    
    # 디버그 파일
    "debug_comments.py",
    "debug_groq.py",
    "debug_output.txt",
    "pipeline_output.txt",
    "real_api_output.txt",
    
    # 테스트 파일
    "test_async_classifier.py",
    "test_full_pipeline.py",
    "test_optimized_classifier.py",
    "test_pipeline_simple.py",
    "test_real_api.py",
    "test_report.py",
    
    # 벤치마크 파일
    "benchmark_3way_comparison.py",
    "benchmark_classifier.py",
    "benchmark_real_api.py",
    "benchmark_results_example.py",
    "benchmark_speed_accuracy.py",
    "simple_benchmark.py",
    "run_benchmark_auto.py",
    
    # 유틸리티/임시 스크립트
    "accuracy_explanation_example.py",
    "check_llm_calls.py",
    "clean_templates.py",
    "comment_report_prompt.py",
    "create_agent_structure.py",
    "export_db_to_excel.py",
    "migrate_add_integrated_report.py",
    "pipeline_runner.py",
    "rename_files.py",
    "replace_video_detail.py",
    "run_with_api_key.py",
    "toxlsx.py",
    "verify_airflow_pipeline.py",
    "verify_installation.py",
    "setup_utils.py",  # 이미 실행했으므로
    
    # 중복 파일 (이제 scripts/utils/에 있음)
    "prompt_manager.py",
    
    # 원본 파일들 (모듈화로 완전히 대체됨 - Git에 커밋됨)
    "main_youtube_analysis.py",  # 원본 1778줄 파일
    "main.py",                    # 이전 메인 파일
    
    # 데이터 파일
    "videos.csv",
    "videos.xlsx",
    "db_export_20260406_182916.xlsx",
    "db_export_20260406_182916_csv.zip",
    
    # 배치 스크립트
    "run_server.bat",
    "setup.bat",
    "setup.sh",
    
    # 중복 메인 파일 (이제 루트에 있음)
    "scripts/main_youtube_tech_review.py",
    
    # 불필요한 MD 문서들 (프로젝트 과정 기록)
    "ACCURACY_METRICS_EXPLANATION.md",
    "DELIVERY_SUMMARY.md",
    "DEPLOYMENT_REPORT.md",
    "FINAL_CHECKLIST.md",
    "GROQ_COMPLETE_MIGRATION.md",
    "GROQ_MIGRATION.md",
    "INDEX.md",
    "OPTIMIZED_CLASSIFIER_GUIDE.md",
    "TESTING_GUIDE.md",
    "USAGE_EXAMPLES.md",
    "README_MAIN.md",
    "README_YOUTUBE_SERVICE.md",
    "DOCKER_GUIDE.md",
    "ARCHITECTURE.md",
    "SYSTEM_ARCHITECTURE.md",
    
    # 텍스트 파일
    "START_HERE.txt",
]

# ============================================================================
# ⚠️ 절대 삭제하면 안 되는 것들
# ============================================================================

DO_NOT_DELETE = [
    # 필수 파일
    ".env",
    ".gitignore",
    "requirements.txt",
    "requirements-airflow.txt",
    "docker-compose.yml",
    "Dockerfile",
    
    # 메인 진입점 (루트)
    "main_youtube_tech_review.py",
    
    # 원본 백업 (선택적으로 유지 - 참고용)
    "main_youtube_analysis.py",
    
    # 중요 문서 (핵심만 유지)
    "README.md",                        # 프로젝트 메인 설명
    "MAIN_CODE_ANALYSIS.md",            # 원본 코드 분석
    "MODULARIZATION_COMPLETE.md",       # 최종 모듈화 구조
    "COMMENT_FILTERING_AGENT_DESIGN.md", # Agent 설계
    "CLEANUP_GUIDE.md",                 # 정리 가이드
    
    # 필수 폴더
    "scripts/",
    "templates/",
    "comment_filtering_agent/",
    "services/",
    "dags/",
    "app/",
    "llm/",
    ".git/",
    ".venv_backup/",
    "__pycache__/",
]

# ============================================================================
# 실행
# ============================================================================

if __name__ == "__main__":
    import os
    
    print("=" * 70)
    print("  안전하게 삭제 가능한 파일 목록")
    print("=" * 70)
    print()
    
    existing_files = []
    missing_files = []
    
    for file in SAFE_TO_DELETE:
        if os.path.exists(file):
            existing_files.append(file)
            print(f"✅ {file}")
        else:
            missing_files.append(file)
    
    print()
    print("=" * 70)
    print(f"  총 {len(existing_files)}개 파일 삭제 가능")
    if missing_files:
        print(f"  ({len(missing_files)}개는 이미 없음)")
    print("=" * 70)
    print()
    
    # 삭제 확인
    response = input("위 파일들을 모두 삭제하시겠습니까? (y/n): ")
    
    if response.lower() == 'y':
        deleted_count = 0
        for file in existing_files:
            try:
                os.remove(file)
                print(f"🗑️  삭제됨: {file}")
                deleted_count += 1
            except Exception as e:
                print(f"❌ 삭제 실패: {file} - {e}")
        
        print()
        print("=" * 70)
        print(f"  ✅ {deleted_count}개 파일 삭제 완료!")
        print("=" * 70)
    else:
        print("\n취소됨. 파일이 삭제되지 않았습니다.")
