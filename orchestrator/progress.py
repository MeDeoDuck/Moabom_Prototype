"""종합 인사이트(④) 생성 진행상태 emit — pirOverlay 로딩바 실연동용.

`video_selection_agent/api/routes.py:_progress_update` 와 동일한 DB(insight_progress)
UPSERT 패턴. orchestrator 노드가 단계 진입 시 phase 를 기록하고, 라우트의 폴링
엔드포인트가 이를 읽는다. 진행 표시는 best-effort — 실패해도 ④ 생성 본류에 영향 없음.
"""
from __future__ import annotations

import json
from typing import Any

from scripts.database.queries import execute_update, query_one


def emit_insight_progress(product_id: int, *, fresh: bool = False, **fields: Any) -> None:
    """insight_progress payload 를 UPSERT.

    fresh=True 면 기존 payload 를 무시하고 새로 시작(라우트 진입 시), False 면 기존
    payload 에 fields 를 merge 한다(노드 단계 전환 시).
    """
    try:
        payload: dict = {}
        if not fresh:
            row = query_one(
                "SELECT payload FROM insight_progress WHERE product_id = %s",
                (product_id,),
            )
            if row and row.get("payload"):
                payload = dict(row["payload"])
        payload.update(fields)
        execute_update(
            """INSERT INTO insight_progress (product_id, payload, updated_at)
               VALUES (%s, %s, NOW())
               ON CONFLICT (product_id) DO UPDATE SET
                   payload = EXCLUDED.payload, updated_at = NOW()""",
            (product_id, json.dumps(payload, ensure_ascii=False)),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[insight_progress] update failed (ignored): {exc}")
