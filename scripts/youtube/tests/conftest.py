"""scripts.youtube 단위 테스트용 — 저장소 루트를 sys.path 에 추가.

오프라인 전용 — DB·LLM·네트워크 없음.
"""
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
