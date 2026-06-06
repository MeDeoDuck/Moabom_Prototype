"""영상 선정 전략 feature flag (v3 설계 §8).

`SELECTION_STRATEGY` env 로 v1_weighted / v3_cluster 를 전환한다.
PR1 시점에는 v3_cluster 경로가 아직 미구현이므로, v3_cluster 를 요청해도
`resolve_strategy()` 가 v1_weighted 로 강등(downgrade)하고 그 사실을 알린다.
PR4 활성화 시 이 강등 로직만 제거하면 된다.

kill switch: 운영 중 v3 가 문제를 일으키면 `SELECTION_STRATEGY=v1_weighted`
(또는 미설정) 로 즉시 v1 복귀.
"""
from __future__ import annotations

import os

V1_WEIGHTED = "v1_weighted"
V3_CLUSTER = "v3_cluster"

_VALID = {V1_WEIGHTED, V3_CLUSTER}
# PR4: v3_cluster 가 기본 동작. v1_weighted 는 fallback(코드상 유지) + kill switch
# (SELECTION_STRATEGY=v1_weighted 로 즉시 v1 복귀).
_DEFAULT = V3_CLUSTER

# PR4: v3_cluster 실 경로 활성화(coarse+fine+verifier → v1 위 재선택기). 더 이상 강등 X.
# 비상시 SELECTION_STRATEGY 미설정/v1_weighted 로 즉시 v1 복귀(kill switch).
_V3_NOT_YET_IMPLEMENTED = False


def requested_strategy() -> str:
    """env 가 요청한 전략 (검증·강등 전 raw 값). 알 수 없는 값은 default."""
    value = (os.environ.get("SELECTION_STRATEGY") or "").strip().lower()
    return value if value in _VALID else _DEFAULT


def resolve_strategy() -> tuple[str, str | None]:
    """실제 실행할 전략과, 강등이 일어났을 때의 사유를 반환.

    returns: (effective_strategy, downgrade_note)
      - downgrade_note 는 강등이 없으면 None. 있으면 trace/metrics 에 남길 한 줄.
    """
    requested = requested_strategy()
    if requested == V3_CLUSTER and _V3_NOT_YET_IMPLEMENTED:
        return V1_WEIGHTED, (
            "strategy: v3_cluster requested but not yet implemented (PR1) "
            "→ downgraded to v1_weighted"
        )
    return requested, None
