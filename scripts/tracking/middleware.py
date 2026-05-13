"""
UsageTrackingMiddleware  — session_uuid + utm_source 쿠키 발급, page_view/action 기록
GATagMiddleware          — env GA_MEASUREMENT_ID 있을 때 HTML </head> 직전에 GA4 snippet inject
"""
import re
import uuid as uuidlib
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from scripts.tracking.events import record_event


SESSION_COOKIE = "moabom_sid"
UTM_COOKIE = "moabom_utm"
SESSION_MAX_AGE = 180 * 24 * 3600
UTM_MAX_AGE = 90 * 24 * 3600

VALID_UTM_SOURCES = {"inha", "incom", "swm17", "linkus", "direct"}

_SKIP_PREFIXES = ("/static/", "/admin", "/docs", "/openapi", "/redoc", "/favicon")
_SKIP_SUFFIXES = (".css", ".js", ".png", ".jpg", ".jpeg", ".ico", ".pdf", ".map", ".svg", ".woff", ".woff2")

_RE_PRODUCT_SYNC = re.compile(r"^/products/(\d+)/sync$")
_RE_PRODUCT_INSIGHT = re.compile(r"^/products/(\d+)/integrated-insight$")
_RE_VIDEO_DETAIL = re.compile(r"^/products/(\d+)/videos/([\w-]+)$")
_RE_PRODUCT_DETAIL = re.compile(r"^/products/(\d+)$")


def _is_trackable_get(path: str) -> bool:
    if any(path.startswith(p) for p in _SKIP_PREFIXES):
        return False
    if any(path.endswith(s) for s in _SKIP_SUFFIXES):
        return False
    return True


def _classify_action(method: str, path: str) -> tuple[Optional[str], Optional[int], Optional[str]]:
    """POST 요청을 action 이벤트로 매핑. (event_type, product_id, video_id) 반환."""
    if method != "POST":
        return None, None, None
    if path == "/products":
        return "product_create", None, None
    m = _RE_PRODUCT_SYNC.match(path)
    if m:
        return "video_sync", int(m.group(1)), None
    m = _RE_PRODUCT_INSIGHT.match(path)
    if m:
        return "integrated_insight", int(m.group(1)), None
    return None, None, None


def _extract_page_context(path: str) -> tuple[Optional[int], Optional[str]]:
    m = _RE_VIDEO_DETAIL.match(path)
    if m:
        return int(m.group(1)), m.group(2)
    m = _RE_PRODUCT_DETAIL.match(path)
    if m:
        return int(m.group(1)), None
    return None, None


class UsageTrackingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        sid = request.cookies.get(SESSION_COOKIE)
        sid_existed = bool(sid)
        if not sid:
            sid = str(uuidlib.uuid4())

        utm_query = request.query_params.get("utm_source")
        if utm_query and utm_query not in VALID_UTM_SOURCES:
            utm_query = None

        utm_cookie = request.cookies.get(UTM_COOKIE)
        utm_existed = bool(utm_cookie)

        # First-touch: 쿠키 비어있을 때만 쿼리값을 채택 (이후 들어오는 utm_source는 무시)
        if not utm_cookie and utm_query:
            utm_attribution = utm_query
        else:
            utm_attribution = utm_cookie

        request.state.session_uuid = sid
        request.state.utm_source = utm_attribution

        path = request.url.path
        method = request.method

        # GET HTML → page_view
        if method == "GET" and _is_trackable_get(path):
            pid, vid = _extract_page_context(path)
            record_event(
                session_uuid=sid,
                utm_source=utm_attribution,
                event_type="page_view",
                path=path,
                product_id=pid,
                video_id=vid,
                referrer=request.headers.get("referer"),
                user_agent=(request.headers.get("user-agent") or "")[:500] or None,
            )

        response = await call_next(request)

        # POST success → action 이벤트
        action_type, pid, vid = _classify_action(method, path)
        if action_type and 200 <= response.status_code < 400:
            record_event(
                session_uuid=sid,
                utm_source=utm_attribution,
                event_type=action_type,
                path=path,
                product_id=pid,
                video_id=vid,
            )

        # 쿠키 세팅 (1st visit만)
        if not sid_existed:
            response.set_cookie(
                SESSION_COOKIE,
                sid,
                max_age=SESSION_MAX_AGE,
                httponly=True,
                samesite="lax",
                path="/",
            )
        if not utm_existed and utm_attribution:
            response.set_cookie(
                UTM_COOKIE,
                utm_attribution,
                max_age=UTM_MAX_AGE,
                httponly=False,
                samesite="lax",
                path="/",
            )

        return response


class GATagMiddleware(BaseHTTPMiddleware):
    """GA4 gtag.js를 HTML 응답 </head> 직전에 inject. measurement_id 미설정 시 no-op."""

    def __init__(self, app, measurement_id: Optional[str] = None):
        super().__init__(app)
        self.measurement_id = measurement_id or None
        if self.measurement_id:
            self.snippet = (
                f'<script async src="https://www.googletagmanager.com/gtag/js?id={self.measurement_id}"></script>'
                f"<script>window.dataLayer=window.dataLayer||[];"
                f"function gtag(){{dataLayer.push(arguments);}}"
                f"gtag('js',new Date());"
                f"gtag('config','{self.measurement_id}');</script>"
            )
        else:
            self.snippet = None

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if not self.snippet:
            return response
        ct = response.headers.get("content-type", "")
        if "text/html" not in ct:
            return response

        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        try:
            body_str = body.decode("utf-8")
        except UnicodeDecodeError:
            return Response(content=body, status_code=response.status_code,
                            headers=dict(response.headers), media_type=ct)

        if "</head>" in body_str:
            body_str = body_str.replace("</head>", f"{self.snippet}</head>", 1)
            new_body = body_str.encode("utf-8")
        else:
            new_body = body

        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(
            content=new_body,
            status_code=response.status_code,
            headers=headers,
            media_type=ct,
        )
