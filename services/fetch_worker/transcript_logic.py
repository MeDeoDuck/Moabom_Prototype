"""YouTube transcript fetch — cookieless on residential IP.

Ported from scripts/youtube/transcript_service.py with two differences:
  - No cookie path. Residential IP avoids the datacenter bot trap that forced
    cookie auth in production. If YouTube ever starts blocking the home IP,
    we can plug a cookie path back in here.
  - `import requests` is included (the original module references
    requests.exceptions.Timeout without importing requests — a latent bug
    that we don't fix here to keep this PR scoped).

Returns dict {transcript_text, language_code, segment_count} or None.
"""
from __future__ import annotations

import json
import time
from typing import Any

import requests
import yt_dlp


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

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False, process=False)
        subtitles_data = info.get("automatic_captions") or info.get("subtitles") or {}
    except Exception:
        return None

    session = requests.Session()
    preferred_formats = ("json3", "vtt")

    for lang in ("ko", "en"):
        items = subtitles_data.get(lang) or []
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
