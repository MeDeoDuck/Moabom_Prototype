"""앱 쿠키 로더(get_cookie_path) YT_COOKIES_LIST round-robin 단위 테스트 (P1)."""
from __future__ import annotations

from scripts.youtube import cookies


def _write(p, body="# Netscape HTTP Cookie File\n"):
    p.write_text(body)
    return str(p)


def test_cookies_list_round_robin(tmp_path, monkeypatch):
    a = _write(tmp_path / "a.txt")
    b = _write(tmp_path / "b.txt")
    c = _write(tmp_path / "c.txt")
    monkeypatch.setenv("YT_COOKIES_LIST", f"{a};{b};{c}")
    monkeypatch.setattr(cookies, "_cookie_idx", 0)
    got = [cookies.get_cookie_path() for _ in range(4)]
    assert got == [a, b, c, a]                       # 호출마다 순환


def test_cookies_list_skips_missing(tmp_path, monkeypatch):
    a = _write(tmp_path / "a.txt")
    monkeypatch.setenv("YT_COOKIES_LIST", f"{tmp_path}/nope.txt;{a}")
    monkeypatch.setattr(cookies, "_cookie_idx", 0)
    assert cookies.get_cookie_path() == a            # 존재하는 것만


def test_single_path_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("YT_COOKIES_LIST", raising=False)
    a = _write(tmp_path / "single.txt")
    monkeypatch.setenv("YT_COOKIES_PATH", a)
    assert cookies.get_cookie_path() == a


def test_none_when_unset(monkeypatch):
    monkeypatch.delenv("YT_COOKIES_LIST", raising=False)
    monkeypatch.delenv("YT_COOKIES_PATH", raising=False)
    monkeypatch.delenv("YT_COOKIES_B64", raising=False)
    assert cookies.get_cookie_path() is None
