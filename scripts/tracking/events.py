"""
usage_events 기록 — 추적 실패는 silent (운영을 깨지 않음).
"""
import json
from typing import Optional

from scripts.database.queries import execute_insert


def record_event(
    session_uuid: str,
    event_type: str,
    utm_source: Optional[str] = None,
    path: Optional[str] = None,
    product_id: Optional[int] = None,
    video_id: Optional[str] = None,
    referrer: Optional[str] = None,
    user_agent: Optional[str] = None,
    extra: Optional[dict] = None,
) -> None:
    extra_json = json.dumps(extra, ensure_ascii=False) if extra else None
    try:
        execute_insert(
            """INSERT INTO usage_events
               (session_uuid, utm_source, event_type, path, product_id, video_id,
                referrer, user_agent, extra)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
               RETURNING id""",
            (
                session_uuid,
                utm_source,
                event_type,
                path,
                product_id,
                video_id,
                referrer,
                user_agent,
                extra_json,
            ),
        )
    except Exception as e:
        print(f"[TRACKING] record_event failed event_type={event_type} err={e}")
