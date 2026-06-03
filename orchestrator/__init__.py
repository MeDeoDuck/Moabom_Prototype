"""제품 단위 통합보고서(④) 오케스트레이션 모듈.

LangGraph 기반 Supervisor 가 ④ integrated-insight 경로의 self-healing 함수들을
명시적 DAG 로 지휘한다. 기존 에이전트(영상선정 / 댓글필터 / 보고서) 내부 구조와
YouTube API 호출은 일절 수정하지 않고 블랙박스 함수로만 감싼다.

진입점:
  - run_insight_supervisor: ④ 라우트가 호출하는 단일 오케스트레이션 엔트리.
  - inspect_freshness: 흩어져 있던 "DB 캐시냐 fetch냐" 판단을 한 곳에 모은 READ ONLY 검사.
"""
from orchestrator.freshness import FreshnessReport, inspect_freshness
from orchestrator.runner import run_insight_supervisor

__all__ = ["run_insight_supervisor", "inspect_freshness", "FreshnessReport"]
