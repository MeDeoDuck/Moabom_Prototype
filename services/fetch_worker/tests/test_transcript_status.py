"""429↔404 구분 테스트 (0단계 B).

fetch_transcript_status 는 rate-limit(=재시도 가치)과 '진짜 자막 없음'을 구분해
(result, rate_limited) 로 반환한다. 라우트는 이를 200/429/404 로 매핑한다.
네트워크 없이 _fetch_transcript_once 를 monkeypatch 로 대체.
"""
from __future__ import annotations

import contextlib

import pytest

import transcript_logic as tl


def _write(p):
    p.write_text("# Netscape HTTP Cookie File\n")
    return str(p)


# ── fetch_transcript_status: rate-limit vs 자막없음 구분 ──────────────

def test_status_success(tmp_path, monkeypatch):
    a = _write(tmp_path / "a.txt")
    monkeypatch.setenv("YT_COOKIES_LIST", a)
    monkeypatch.setattr(tl, "_cookie_idx", 0)
    monkeypatch.setattr(
        tl, "_fetch_transcript_once",
        lambda vid, ck: ({"transcript_text": "t", "language_code": "ko", "segment_count": 1}, False),
    )
    result, rate_limited = tl.fetch_transcript_status("vid")
    assert result and result["transcript_text"] == "t"
    assert rate_limited is False


def test_status_rate_limited_all_cookies(tmp_path, monkeypatch):
    a = _write(tmp_path / "a.txt")
    b = _write(tmp_path / "b.txt")
    monkeypatch.setenv("YT_COOKIES_LIST", f"{a};{b}")
    monkeypatch.setattr(tl, "_cookie_idx", 0)
    monkeypatch.setattr(tl, "_fetch_transcript_once", lambda vid, ck: (None, True))
    result, rate_limited = tl.fetch_transcript_status("vid")
    assert result is None
    assert rate_limited is True                 # 전 쿠키 rate-limited → 신호 유지


def test_status_no_subs_not_rate_limited(tmp_path, monkeypatch):
    a = _write(tmp_path / "a.txt")
    monkeypatch.setenv("YT_COOKIES_LIST", a)
    monkeypatch.setattr(tl, "_cookie_idx", 0)
    monkeypatch.setattr(tl, "_fetch_transcript_once", lambda vid, ck: (None, False))
    result, rate_limited = tl.fetch_transcript_status("vid")
    assert result is None
    assert rate_limited is False                # 진짜 자막 없음 → 404 로 매핑돼야


def test_fetch_transcript_wrapper_backward_compat(tmp_path, monkeypatch):
    a = _write(tmp_path / "a.txt")
    monkeypatch.setenv("YT_COOKIES_LIST", a)
    monkeypatch.setattr(tl, "_cookie_idx", 0)
    monkeypatch.setattr(
        tl, "_fetch_transcript_once",
        lambda vid, ck: ({"transcript_text": "t", "language_code": "ko", "segment_count": 1}, False),
    )
    # 기존 호출부·테스트 호환: dict|None 만 반환
    assert tl.fetch_transcript("vid") == {"transcript_text": "t", "language_code": "ko", "segment_count": 1}


# ── 라우트 매핑: 200 / 429 / 404 ─────────────────────────────────────

class _NoPace:
    @contextlib.contextmanager
    def slot(self):
        yield


def _route_module():
    import services.fetch_worker.routes.transcript as rt
    return rt


def test_route_returns_200_on_success(monkeypatch):
    rt = _route_module()
    monkeypatch.setattr(rt, "TRANSCRIPT_PACER", _NoPace())
    monkeypatch.setattr(
        rt, "fetch_transcript_status",
        lambda vid: ({"transcript_text": "t", "language_code": "ko", "segment_count": 1}, False),
    )
    resp = rt.transcript(rt.TranscriptRequest(video_id="abcde"))
    assert resp.transcript_text == "t" and resp.language_code == "ko"


def test_route_returns_429_on_rate_limit(monkeypatch):
    from fastapi import HTTPException
    rt = _route_module()
    monkeypatch.setattr(rt, "TRANSCRIPT_PACER", _NoPace())
    monkeypatch.setattr(rt, "fetch_transcript_status", lambda vid: (None, True))
    with pytest.raises(HTTPException) as ei:
        rt.transcript(rt.TranscriptRequest(video_id="abcde"))
    assert ei.value.status_code == 429


def test_route_returns_404_on_no_subs(monkeypatch):
    from fastapi import HTTPException
    rt = _route_module()
    monkeypatch.setattr(rt, "TRANSCRIPT_PACER", _NoPace())
    monkeypatch.setattr(rt, "fetch_transcript_status", lambda vid: (None, False))
    with pytest.raises(HTTPException) as ei:
        rt.transcript(rt.TranscriptRequest(video_id="abcde"))
    assert ei.value.status_code == 404
