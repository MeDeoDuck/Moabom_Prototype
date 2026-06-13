"""fetch_worker 단위 테스트용 — 워커 디렉터리를 sys.path 에 추가.

워커는 standalone 모듈이라 `import transcript_logic` 로 직접 임포트한다. 오프라인 전용.
"""
import os
import sys

_WORKER = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _WORKER not in sys.path:
    sys.path.insert(0, _WORKER)
