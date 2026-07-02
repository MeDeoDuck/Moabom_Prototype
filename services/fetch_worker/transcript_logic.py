"""YouTube transcript fetch — residential IP with cookie auth.

Originally planned cookieless on residential IP, but observed timedtext
endpoint rate-limits (HTTP 429) even from the home IP under modest traffic.
Plugging in the production cookie file resolves the rate-limit by fetching
as a logged-in user. Cookie source resolution (in order):
  1. YT_COOKIES_PATH env var (when set and the file exists)
  2. <repo>/.secrets/yt_cookies.txt (default colocated with the runtime)

`automatic_captions` is a dict listing every translatable language and is
always truthy — earlier code dropped manual subs because of `or` short-circuit.
Order is now manual first, then auto.

Returns dict {transcript_text, language_code, segment_count} or None.
"""
from __future__ import annotations

import json
import os
import threading
import time
from http.cookiejar import MozillaCookieJar
from typing import Any

import requests
import yt_dlp


_DEFAULT_COOKIES_PATH = "/home/rtx4060ti/projects/Moabom_Prototype/.secrets/yt_cookies.txt"


def _resolve_cookies_path() -> str | None:
    p = os.environ.get("YT_COOKIES_PATH")
    if p and os.path.exists(p):
        return p
    if os.path.exists(_DEFAULT_COOKIES_PATH):
        return _DEFAULT_COOKIES_PATH
    return None


# ── 쿠키 풀 (P1): YT_COOKIES_LIST(`;` 경로들) round-robin + rate-limit 시 다음 쿠키 ──
# 서로 다른 Google 계정 쿠키를 돌려 timedtext 429/봇차단을 분산·회피한다. 미설정 시
# 기존 단일 쿠키와 100% 동일(리스트 길이 1).
_cookie_lock = threading.Lock()
_cookie_idx = 0

_RATE_MARKERS = (
    "sign in to confirm", "not a bot", "429", "too many requests",
    "rate limit", "blocked", "consent",
)


def _cookie_paths() -> list[str]:
    """YT_COOKIES_LIST(존재하는 경로들) → 리스트. 없으면 단일 경로 1개짜리(기존 동작)."""
    raw = os.environ.get("YT_COOKIES_LIST", "")
    paths = [p.strip() for p in raw.split(";") if p.strip() and os.path.exists(p.strip())]
    if paths:
        return paths
    single = _resolve_cookies_path()
    return [single] if single else []


def _next_start(n: int) -> int:
    """요청마다 시작 쿠키를 round-robin 으로 옮겨 부하를 계정에 분산."""
    global _cookie_idx
    if n <= 0:
        return 0
    with _cookie_lock:
        i = _cookie_idx % n
        _cookie_idx = (i + 1) % n
        return i


def _looks_rate_limited(text: str) -> bool:
    t = (text or "").lower()
    return any(m in t for m in _RATE_MARKERS)


def _build_session(cookie_path: str | None) -> requests.Session:
    s = requests.Session()
    p = cookie_path
    if p:
        jar = MozillaCookieJar(p)
        try:
            jar.load(ignore_discard=True, ignore_expires=True)
            s.cookies = jar  # type: ignore[assignment]
        except Exception:
            pass
    return s


def _parse_json3(content: str) -> str | None:
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None
    parts: list[str] = []
    for event in data.get("events", []) or []:
        for seg in event.get("segs", []) or []:
            if "utf8" in seg:
                parts.append(seg["utf8"])
    text = " ".join(parts).strip()
    return text or None


def _parse_vtt(content: str) -> str | None:
    parts: list[str] = []
    for line in content.split("\n"):
        line = line.strip()
        if line and not line.startswith("WEBVTT") and "-->" not in line:
            parts.append(line)
    text = " ".join(parts).strip()
    return text or None


def _fetch_with_backoff(
    session: requests.Session, url: str, max_retries: int = 3
) -> tuple[str | None, bool]:
    """반환 (content|None, rate_limited). rate_limited 면 다른 쿠키로 재시도 가치 있음."""
    for attempt in range(max_retries):
        try:
            response = session.get(url, timeout=30)
            if response.status_code == 429:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return None, True
            response.raise_for_status()
            return response.text, False
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return None, False
        except requests.exceptions.RequestException:
            return None, False
    return None, False


def _fetch_transcript_once(
    video_id: str, cookie_path: str | None
) -> tuple[dict[str, Any] | None, bool]:
    """단일 쿠키로 1회 시도. 반환 (result|None, rate_limited).

    rate_limited=True 면 봇차단/429 신호라 다른 쿠키로 재시도할 가치가 있다. extract_info
    가 정상인데 자막이 없으면 (None, False) — 진짜 자막 없음이라 쿠키 회전은 무의미.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"

    # process=False keeps yt-dlp on the metadata path and avoids the format /
    # n-challenge pipeline that throws "No video formats found" — same reason
    # as the production fetcher.
    ydl_opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    if cookie_path:
        ydl_opts["cookiefile"] = cookie_path

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False, process=False)
    except Exception as e:
        # 봇차단/429 면 다른 쿠키로 재시도 가치, 그 외(비공개·삭제 등)는 회전 무의미.
        return None, _looks_rate_limited(str(e))

    # Manual subtitles first, then automatic captions. Older code did
    #   info.get('automatic_captions') or info.get('subtitles')
    # which silently dropped manual subs because automatic_captions is a dict
    # listing every translatable language, so it is always truthy even when it
    # has no real content for the language we want.
    manual_subs = info.get("subtitles") or {}
    auto_subs = info.get("automatic_captions") or {}

    session = _build_session(cookie_path)
    preferred_formats = ("json3", "vtt")
    saw_rate_limit = False

    for lang in ("ko", "en"):
        items = (manual_subs.get(lang) or []) + (auto_subs.get(lang) or [])
        for item in items:
            if not isinstance(item, dict) or "url" not in item:
                continue
            ext = item.get("ext", "")
            if ext not in preferred_formats:
                continue
            content, rate_limited = _fetch_with_backoff(session, item["url"])
            saw_rate_limit = saw_rate_limit or rate_limited
            if not content:
                continue
            text = _parse_json3(content) if ext == "json3" else _parse_vtt(content)
            if text:
                return {
                    "transcript_text": text,
                    "language_code": lang,
                    "segment_count": len(text.split()),
                }, False

    return None, saw_rate_limit


def fetch_transcript_status(video_id: str) -> tuple[dict[str, Any] | None, bool]:
    """쿠키 풀 round-robin + rate-limit 시 다음 쿠키 재시도 (P1 쿠키 풀).

    rate-limit(=재시도 가치 있음)과 '진짜 자막 없음'을 구분해 (result, rate_limited)
    로 반환한다 — 라우트가 200/429/404 로 매핑한다. YT_COOKIES_LIST 미설정 시 단일
    쿠키 1회 시도와 동일(리스트 길이 1).
    """
    paths = _cookie_paths()
    if not paths:
        result, rate_limited = _fetch_transcript_once(video_id, None)   # 익명 폴백
        return result, (rate_limited if result is None else False)

    n = len(paths)
    start = _next_start(n)
    any_rate_limited = False
    for off in range(n):
        cookie_path = paths[(start + off) % n]
        result, rate_limited = _fetch_transcript_once(video_id, cookie_path)
        if result:
            return result, False
        if not rate_limited:
            return None, False   # 진짜 자막 없음/영구 실패 → 회전 무의미
        any_rate_limited = True
        if off + 1 < n:
            print(f"[transcript] rate-limited, rotating cookie ({off + 2}/{n})", flush=True)
    return None, any_rate_limited   # 전 쿠키 rate-limited → 신호 유지


def fetch_transcript(video_id: str) -> dict[str, Any] | None:
    """(하위호환) dict|None 만 반환하는 얇은 래퍼.

    rate-limit 여부까지 필요하면 fetch_transcript_status 를 쓴다.
    """
    result, _ = fetch_transcript_status(video_id)
    return result
