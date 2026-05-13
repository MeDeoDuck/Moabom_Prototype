"""
/admin 추적 대시보드 — 채널별 DAU·funnel·일자별 추이.
ADMIN_TOKEN env var와 일치하는 ?token=... 또는 X-Admin-Token 헤더 필요.
"""
import os
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from scripts.database.queries import query_all

templates = Jinja2Templates(directory="templates")


def _check_token(request: Request) -> None:
    expected = os.getenv("ADMIN_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="ADMIN_TOKEN 미설정 — 운영자에게 문의")
    provided = (
        request.query_params.get("token")
        or request.headers.get("X-Admin-Token")
        or request.cookies.get("moabom_admin_token")
        or ""
    ).strip()
    if provided != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _channels_summary() -> list[dict]:
    """채널별 unique session + page_view + 핵심 action count."""
    rows = query_all(
        """
        SELECT
          COALESCE(utm_source, 'direct')                                AS channel,
          COUNT(DISTINCT session_uuid)                                  AS sessions,
          COUNT(*) FILTER (WHERE event_type = 'page_view')              AS page_views,
          COUNT(DISTINCT session_uuid) FILTER (WHERE event_type = 'page_view' AND path LIKE '/products/%%') AS sessions_viewed_product,
          COUNT(DISTINCT session_uuid) FILTER (WHERE event_type = 'product_create')      AS sessions_created_product,
          COUNT(DISTINCT session_uuid) FILTER (WHERE event_type = 'video_sync')          AS sessions_synced,
          COUNT(DISTINCT session_uuid) FILTER (WHERE event_type = 'integrated_insight')  AS sessions_insighted
        FROM usage_events
        GROUP BY COALESCE(utm_source, 'direct')
        ORDER BY sessions DESC
        """
    )
    return rows


def _daily_trend(days: int = 14) -> list[dict]:
    rows = query_all(
        """
        SELECT
          DATE(ts)                                          AS day,
          COUNT(DISTINCT session_uuid)                      AS sessions,
          COUNT(*) FILTER (WHERE event_type = 'page_view')  AS page_views,
          COUNT(*) FILTER (WHERE event_type IN ('product_create','video_sync','integrated_insight')) AS actions
        FROM usage_events
        WHERE ts > NOW() - (%s * INTERVAL '1 day')
        GROUP BY DATE(ts)
        ORDER BY day
        """,
        (days,),
    )
    return rows


def _recent_events(limit: int = 100) -> list[dict]:
    rows = query_all(
        """
        SELECT id, session_uuid, utm_source, event_type, path, product_id, video_id, ts
        FROM usage_events
        ORDER BY ts DESC
        LIMIT %s
        """,
        (limit,),
    )
    return rows


def _totals() -> dict:
    rows = query_all(
        """
        SELECT
          COUNT(DISTINCT session_uuid) AS total_sessions,
          COUNT(*)                     AS total_events,
          COUNT(*) FILTER (WHERE event_type = 'page_view')             AS page_views,
          COUNT(*) FILTER (WHERE event_type = 'product_create')        AS product_creates,
          COUNT(*) FILTER (WHERE event_type = 'video_sync')            AS video_syncs,
          COUNT(*) FILTER (WHERE event_type = 'integrated_insight')    AS insights,
          MIN(ts) AS first_event_at,
          MAX(ts) AS last_event_at
        FROM usage_events
        """
    )
    return rows[0] if rows else {}


def register_admin_routes(app):
    @app.get("/admin", response_class=HTMLResponse)
    async def admin_dashboard(request: Request):
        _check_token(request)
        return templates.TemplateResponse(
            "admin.html",
            {
                "request": request,
                "channels": _channels_summary(),
                "daily": _daily_trend(),
                "recent": _recent_events(),
                "totals": _totals(),
            },
        )

    @app.get("/admin/api/events.json")
    async def admin_events_json(request: Request, limit: int = 200):
        _check_token(request)
        limit = max(1, min(limit, 1000))
        rows = _recent_events(limit=limit)
        for r in rows:
            if r.get("ts"):
                r["ts"] = r["ts"].isoformat()
            if r.get("session_uuid"):
                r["session_uuid"] = str(r["session_uuid"])
        return JSONResponse({"events": rows})
