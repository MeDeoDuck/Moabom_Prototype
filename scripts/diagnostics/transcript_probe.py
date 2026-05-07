"""
Transcript fetch diagnostic probe.

Isolates the 4 stages where YouTube can block a datacenter IP:
  [0] outbound IP / geo                  (where am I calling from?)
  [1] watch page HTML                    (consent gate / 429 / captcha)
  [2] yt-dlp extract_info                (caption URL listing)
  [3] caption URL fetch                  (json3 / vtt body)

Run locally and on Azure (Cloud Shell or container) with the SAME video ids,
then diff the outputs to pinpoint exactly which stage diverges.

Usage:
    python -m scripts.diagnostics.transcript_probe
    python -m scripts.diagnostics.transcript_probe VIDEO_ID [VIDEO_ID ...]
    python -m scripts.diagnostics.transcript_probe --json > probe.json
"""
from __future__ import annotations

import argparse
import atexit
import base64
import json
import os
import platform
import socket
import sys
import tempfile
import time
from http.cookiejar import MozillaCookieJar
from typing import Any

import requests
import yt_dlp

_TMP_COOKIE_PATH: str | None = None


def get_cookie_path() -> str | None:
    """Resolve a Netscape cookie file path from env.

    Precedence: YT_COOKIES_PATH (file) > YT_COOKIES_B64 (base64-encoded body, written to /tmp).
    Returns None when neither is set — caller proceeds anonymously.
    """
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
    """requests.Session with the configured cookie jar attached (if any)."""
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

DEFAULT_VIDEO_IDS = [
    "9bZkp7q19f0",
    "jNQXAC9IVRw",
    "dQw4w9WgXcQ",
]

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _truncate(s: str | None, n: int = 240) -> str:
    if s is None:
        return ""
    s = s.replace("\n", " ").replace("\r", " ")
    return s if len(s) <= n else s[:n] + "..."


def probe_environment() -> dict[str, Any]:
    cookie_path = get_cookie_path()
    cookie_info: dict[str, Any] = {"path": cookie_path, "loaded_count": 0}
    if cookie_path:
        try:
            jar = MozillaCookieJar(cookie_path)
            jar.load(ignore_discard=True, ignore_expires=True)
            cookie_info["loaded_count"] = sum(1 for _ in jar)
        except Exception as e:
            cookie_info["error"] = f"{type(e).__name__}: {e}"

    out: dict[str, Any] = {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "yt_dlp": getattr(yt_dlp.version, "__version__", "?"),
        "requests": requests.__version__,
        "cookies": cookie_info,
        "env_proxies": {
            k: os.environ.get(k)
            for k in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy")
            if os.environ.get(k)
        },
    }
    try:
        r = requests.get("https://api.ipify.org?format=json", timeout=10)  # cookie-irrelevant
        out["outbound_ip"] = r.json().get("ip")
    except Exception as e:
        out["outbound_ip_error"] = f"{type(e).__name__}: {e}"

    if out.get("outbound_ip"):
        try:
            r = requests.get(f"https://ipinfo.io/{out['outbound_ip']}/json", timeout=10)
            d = r.json()
            out["geo"] = {
                "ip": d.get("ip"),
                "city": d.get("city"),
                "region": d.get("region"),
                "country": d.get("country"),
                "org": d.get("org"),
                "hostname": d.get("hostname"),
            }
        except Exception as e:
            out["geo_error"] = f"{type(e).__name__}: {e}"
    return out


def probe_watch_page(video_id: str) -> dict[str, Any]:
    url = f"https://www.youtube.com/watch?v={video_id}"
    out: dict[str, Any] = {"url": url}
    try:
        t0 = time.time()
        r = make_session().get(
            url,
            headers={"User-Agent": UA, "Accept-Language": "ko,en;q=0.9"},
            timeout=20,
            allow_redirects=True,
        )
        out["status"] = r.status_code
        out["elapsed_ms"] = int((time.time() - t0) * 1000)
        out["final_url"] = r.url
        out["redirected_to_consent"] = "consent.youtube.com" in r.url or "consent.google.com" in r.url
        body = r.text or ""
        out["body_len"] = len(body)
        out["has_captionTracks"] = '"captionTracks"' in body
        out["has_player_response"] = "ytInitialPlayerResponse" in body
        out["has_recaptcha"] = "recaptcha" in body.lower() or "/sorry/" in r.url
        out["body_head"] = _truncate(body, 400)
        out["headers_sample"] = {
            k: v for k, v in r.headers.items()
            if k.lower() in ("content-type", "set-cookie", "server", "alt-svc", "x-frame-options")
        }
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {_truncate(str(e), 300)}"
    return out


def probe_ytdlp(video_id: str) -> dict[str, Any]:
    url = f"https://www.youtube.com/watch?v={video_id}"
    out: dict[str, Any] = {"url": url}
    try:
        ydl_opts: dict[str, Any] = {"quiet": True, "no_warnings": True, "skip_download": True}
        cookie_path = get_cookie_path()
        if cookie_path:
            ydl_opts["cookiefile"] = cookie_path
        t0 = time.time()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False, process=False)
        out["elapsed_ms"] = int((time.time() - t0) * 1000)
        auto = info.get("automatic_captions") or {}
        manual = info.get("subtitles") or {}
        out["auto_langs"] = sorted(auto.keys())
        out["manual_langs"] = sorted(manual.keys())
        sample: dict[str, Any] = {}
        for lang in ("ko", "en"):
            for label, src in (("manual", manual), ("auto", auto)):
                items = src.get(lang) or []
                fmts = [it.get("ext") for it in items if isinstance(it, dict)]
                urls = [it.get("url") for it in items if isinstance(it, dict) and "url" in it]
                if fmts:
                    sample[f"{lang}_{label}"] = {
                        "formats": fmts,
                        "first_url": _truncate(urls[0] if urls else None, 160),
                    }
        out["sample"] = sample
        out["title"] = _truncate(info.get("title"), 80)
        out["uploader"] = info.get("uploader")
        out["duration"] = info.get("duration")
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {_truncate(str(e), 400)}"
    return out


def probe_caption_fetch(ytdlp_result: dict[str, Any]) -> dict[str, Any]:
    sample = ytdlp_result.get("sample") or {}
    if not sample:
        return {"skipped": "no caption urls available from ytdlp stage"}

    target_url = None
    target_label = None
    for label in ("ko_manual", "ko_auto", "en_manual", "en_auto"):
        if label in sample and sample[label].get("first_url"):
            target_url = sample[label]["first_url"]
            target_label = label
            break

    if not target_url:
        return {"skipped": "no usable url in sample"}

    out: dict[str, Any] = {"label": target_label, "url_head": target_url}

    if target_url.endswith("..."):
        out["note"] = "url was truncated for display; refetching from ytdlp output not supported in this probe"
        return out

    try:
        t0 = time.time()
        r = make_session().get(target_url, timeout=20)
        out["status"] = r.status_code
        out["elapsed_ms"] = int((time.time() - t0) * 1000)
        out["body_len"] = len(r.text or "")
        out["body_head"] = _truncate(r.text, 300)
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {_truncate(str(e), 300)}"
    return out


def probe_caption_fetch_full(video_id: str) -> dict[str, Any]:
    """Re-extract metadata WITHOUT truncation, then fetch first ko/en json3 or vtt."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    out: dict[str, Any] = {}
    try:
        ydl_opts: dict[str, Any] = {"quiet": True, "no_warnings": True, "skip_download": True}
        cookie_path = get_cookie_path()
        if cookie_path:
            ydl_opts["cookiefile"] = cookie_path
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False, process=False)
        subs = info.get("automatic_captions") or info.get("subtitles") or {}
        chosen = None
        for lang in ("ko", "en"):
            for it in subs.get(lang) or []:
                if isinstance(it, dict) and it.get("ext") in ("json3", "vtt") and it.get("url"):
                    chosen = (lang, it["ext"], it["url"])
                    break
            if chosen:
                break
        if not chosen:
            return {"skipped": "no ko/en json3|vtt url"}
        lang, ext, curl = chosen
        out["lang"] = lang
        out["ext"] = ext
        out["url_host"] = curl.split("/")[2] if "://" in curl else "?"
        t0 = time.time()
        r = make_session().get(curl, timeout=20)
        out["status"] = r.status_code
        out["elapsed_ms"] = int((time.time() - t0) * 1000)
        out["body_len"] = len(r.text or "")
        out["body_head"] = _truncate(r.text, 300)
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {_truncate(str(e), 400)}"
    return out


def diagnose(video_ids: list[str]) -> dict[str, Any]:
    report: dict[str, Any] = {"env": probe_environment(), "videos": {}}
    for vid in video_ids:
        v: dict[str, Any] = {}
        v["watch"] = probe_watch_page(vid)
        v["ytdlp"] = probe_ytdlp(vid)
        v["caption"] = probe_caption_fetch_full(vid)
        report["videos"][vid] = v
    return report


def render_human(report: dict[str, Any]) -> str:
    env = report["env"]
    lines = []
    lines.append("=" * 72)
    lines.append(f"HOST       : {env.get('hostname')} ({env.get('platform')})")
    lines.append(f"PYTHON     : {env.get('python')}  yt-dlp={env.get('yt_dlp')}  requests={env.get('requests')}")
    lines.append(f"OUTBOUND IP: {env.get('outbound_ip') or env.get('outbound_ip_error')}")
    geo = env.get("geo") or {}
    lines.append(
        f"GEO        : {geo.get('country')}/{geo.get('region')}/{geo.get('city')}  org={geo.get('org')}"
    )
    if env.get("env_proxies"):
        lines.append(f"PROXIES    : {env['env_proxies']}")
    cookies = env.get("cookies") or {}
    if cookies.get("path") or cookies.get("loaded_count"):
        lines.append(
            f"COOKIES    : path={cookies.get('path')} loaded={cookies.get('loaded_count')} err={cookies.get('error')}"
        )
    else:
        lines.append("COOKIES    : (none — anonymous)")
    lines.append("=" * 72)
    for vid, v in report["videos"].items():
        lines.append(f"\n[ video_id = {vid} ]")
        w = v["watch"]
        lines.append(
            f"  [1] watch    status={w.get('status')} consent={w.get('redirected_to_consent')} "
            f"captionTracks={w.get('has_captionTracks')} recaptcha={w.get('has_recaptcha')} "
            f"len={w.get('body_len')} err={w.get('error')}"
        )
        y = v["ytdlp"]
        lines.append(
            f"  [2] ytdlp    auto={y.get('auto_langs')} manual={y.get('manual_langs')} "
            f"err={y.get('error')}"
        )
        c = v["caption"]
        lines.append(
            f"  [3] caption  lang={c.get('lang')} ext={c.get('ext')} status={c.get('status')} "
            f"len={c.get('body_len')} err={c.get('error')} skip={c.get('skipped')}"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="Transcript fetch diagnostic probe")
    p.add_argument("video_ids", nargs="*", default=DEFAULT_VIDEO_IDS)
    p.add_argument("--json", action="store_true", help="emit full JSON to stdout")
    args = p.parse_args()

    report = diagnose(args.video_ids)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_human(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
