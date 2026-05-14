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


def _build_session() -> requests.Session:
    s = requests.Session()
    p = _resolve_cookies_path()
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
) -> str | None:
    for attempt in range(max_retries):
        try:
            response = session.get(url, timeout=30)
            if response.status_code == 429:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return None
            response.raise_for_status()
            return response.text
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return None
        except requests.exceptions.RequestException:
            return None
    return None


def fetch_transcript(video_id: str) -> dict[str, Any] | None:
    url = f"https://www.youtube.com/watch?v={video_id}"

    # process=False keeps yt-dlp on the metadata path and avoids the format /
    # n-challenge pipeline that throws "No video formats found" — same reason
    # as the production fetcher.
    ydl_opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    cookie_path = _resolve_cookies_path()
    if cookie_path:
        ydl_opts["cookiefile"] = cookie_path

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False, process=False)
    except Exception:
        return None

    # Manual subtitles first, then automatic captions. Older code did
    #   info.get('automatic_captions') or info.get('subtitles')
    # which silently dropped manual subs because automatic_captions is a dict
    # listing every translatable language, so it is always truthy even when it
    # has no real content for the language we want.
    manual_subs = info.get("subtitles") or {}
    auto_subs = info.get("automatic_captions") or {}

    session = _build_session()
    preferred_formats = ("json3", "vtt")

    for lang in ("ko", "en"):
        items = (manual_subs.get(lang) or []) + (auto_subs.get(lang) or [])
        for item in items:
            if not isinstance(item, dict) or "url" not in item:
                continue
            ext = item.get("ext", "")
            if ext not in preferred_formats:
                continue
            content = _fetch_with_backoff(session, item["url"])
            if not content:
                continue
            text = _parse_json3(content) if ext == "json3" else _parse_vtt(content)
            if text:
                return {
                    "transcript_text": text,
                    "language_code": lang,
                    "segment_count": len(text.split()),
                }

    return None
