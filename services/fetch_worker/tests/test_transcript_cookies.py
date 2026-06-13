"""워커 쿠키 풀(round-robin + rate-limit 회전) 단위 테스트 (P1).

네트워크/yt-dlp 없이 helper + rotation 분기만 검증. _fetch_transcript_once 는
monkeypatch 로 대체해 rotation 결정 로직만 본다.
"""
from __future__ import annotations

import transcript_logic as tl


def _write(p, body="# Netscape HTTP Cookie File\n"):
    p.write_text(body)
    return str(p)


# ---------- _cookie_paths ----------

def test_cookie_paths_list_existing_only(tmp_path, monkeypatch):
    a = _write(tmp_path / "a.txt")
    b = _write(tmp_path / "b.txt")
    monkeypatch.setenv("YT_COOKIES_LIST", f"{a};{b};{tmp_path}/missing.txt")
    assert tl._cookie_paths() == [a, b]            # 존재하는 경로만


def test_cookie_paths_single_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("YT_COOKIES_LIST", raising=False)
    a = _write(tmp_path / "s.txt")
    monkeypatch.setenv("YT_COOKIES_PATH", a)
    assert tl._cookie_paths() == [a]               # 리스트 없으면 단일


# ---------- round-robin / rate marker ----------

def test_next_start_round_robin(monkeypatch):
    monkeypatch.setattr(tl, "_cookie_idx", 0)
    assert [tl._next_start(3) for _ in range(4)] == [0, 1, 2, 0]


def test_looks_rate_limited():
    assert tl._looks_rate_limited("Sign in to confirm you're not a bot")
    assert tl._looks_rate_limited("HTTP Error 429: Too Many Requests")
    assert not tl._looks_rate_limited("Video unavailable")
    assert not tl._looks_rate_limited("Private video")


# ---------- _fetch_with_backoff 429 신호 ----------

def test_fetch_with_backoff_429(monkeypatch):
    monkeypatch.setattr(tl.time, "sleep", lambda *_: None)

    class _R:
        status_code = 429
        text = "x"
        def raise_for_status(self):
            pass

    class _Sess:
        def get(self, *a, **k):
            return _R()

    content, rl = tl._fetch_with_backoff(_Sess(), "u", max_retries=2)
    assert content is None and rl is True


def test_fetch_with_backoff_ok():
    class _R:
        status_code = 200
        text = "hello"
        def raise_for_status(self):
            pass

    class _Sess:
        def get(self, *a, **k):
            return _R()

    content, rl = tl._fetch_with_backoff(_Sess(), "u")
    assert content == "hello" and rl is False


# ---------- fetch_transcript rotation 결정 ----------

def test_rotates_on_rate_limit(tmp_path, monkeypatch):
    a = _write(tmp_path / "a.txt")
    b = _write(tmp_path / "b.txt")
    monkeypatch.setenv("YT_COOKIES_LIST", f"{a};{b}")
    monkeypatch.setattr(tl, "_cookie_idx", 0)
    calls = []

    def fake_once(vid, cookie):
        calls.append(cookie)
        if cookie == a:
            return None, True                      # a 는 rate-limited
        return {"transcript_text": "t", "language_code": "ko", "segment_count": 1}, False

    monkeypatch.setattr(tl, "_fetch_transcript_once", fake_once)
    out = tl.fetch_transcript("vid")
    assert out and out["transcript_text"] == "t"
    assert calls == [a, b]                          # a(rate)→b 회전


def test_no_rotation_on_no_subs(tmp_path, monkeypatch):
    a = _write(tmp_path / "a.txt")
    b = _write(tmp_path / "b.txt")
    monkeypatch.setenv("YT_COOKIES_LIST", f"{a};{b}")
    monkeypatch.setattr(tl, "_cookie_idx", 0)
    calls = []

    def fake_once(vid, cookie):
        calls.append(cookie)
        return None, False                          # 자막 없음(rate 아님)

    monkeypatch.setattr(tl, "_fetch_transcript_once", fake_once)
    out = tl.fetch_transcript("vid")
    assert out is None
    assert len(calls) == 1                           # 헛fetch 방지 — 회전 안 함
