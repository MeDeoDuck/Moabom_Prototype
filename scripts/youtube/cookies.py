"""YouTube cookie loading shared by transcript fetcher and diagnostics.

Datacenter IPs (Azure, AWS, ...) are flagged as bots by YouTube; the only
robust workaround is to authenticate as a real Google user via cookies.
This module resolves a Netscape-format cookie file from environment vars
and exposes helpers that wire those cookies into yt-dlp and requests.

Env precedence:
  YT_COOKIES_PATH   — absolute path to a cookie file on disk (local dev)
  YT_COOKIES_B64    — base64-encoded cookie file body (Container Apps secret)

Returns None when neither is set; callers fall back to anonymous fetch.
"""
from __future__ import annotations

import atexit
import base64
import os
import tempfile
from http.cookiejar import MozillaCookieJar
from typing import Any

import requests

_TMP_COOKIE_PATH: str | None = None


def get_cookie_path() -> str | None:
    global _TMP_COOKIE_PATH
    p = os.environ.get("YT_COOKIES_PATH")
    if p and os.path.exists(p):
        return p
    b64 = os.environ.get("YT_COOKIES_B64")
    if not b64:
        return None
    if _TMP_COOKIE_PATH and os.path.exists(_TMP_COOKIE_PATH):
        return _TMP_COOKIE_PATH
    f = tempfile.NamedTemporaryFile(prefix="yt_cookies_", suffix=".txt", delete=False)
    f.write(base64.b64decode(b64))
    f.close()
    _TMP_COOKIE_PATH = f.name
    atexit.register(lambda: os.path.exists(_TMP_COOKIE_PATH or "") and os.unlink(_TMP_COOKIE_PATH))  # type: ignore[arg-type]
    return _TMP_COOKIE_PATH


def make_session() -> requests.Session:
    s = requests.Session()
    p = get_cookie_path()
    if p:
        jar = MozillaCookieJar(p)
        try:
            jar.load(ignore_discard=True, ignore_expires=True)
            s.cookies = jar  # type: ignore[assignment]
        except Exception:
            pass
    return s


def apply_to_ytdlp_opts(opts: dict[str, Any]) -> dict[str, Any]:
    """Mutates opts in place to add cookiefile if a cookie source is configured."""
    p = get_cookie_path()
    if p:
        opts["cookiefile"] = p
    return opts
