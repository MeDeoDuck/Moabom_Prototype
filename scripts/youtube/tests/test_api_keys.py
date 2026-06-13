"""YouTube API 키 풀 + quota rotation 단위 테스트 (P1).

네트워크 없이 fake httpx client 로 rotation 분기만 검증. 모듈 전역 커서
(`_idx`)·키 리스트는 monkeypatch 로 주입하고 테스트 후 자동 복원.
"""
from __future__ import annotations

import pytest

from scripts.youtube import api_keys


# ---------- fakes ----------

class _Resp:
    def __init__(self, status, text="", payload=None):
        self.status_code = status
        self.text = text
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Client:
    """params['key'] 로 응답을 고르는 fake httpx.Client."""
    def __init__(self, by_key):
        self.by_key = by_key
        self.calls = []

    def get(self, url, params=None, timeout=None):
        key = (params or {}).get("key")
        self.calls.append(key)
        return self.by_key[key]


class _FakeHttpError(Exception):
    def __init__(self, status, content):
        class _R:
            pass
        self.resp = _R()
        self.resp.status = status
        self.content = content


@pytest.fixture
def keys(monkeypatch):
    """기본 2키 풀 + 커서 0 으로 초기화하는 헬퍼."""
    def _set(lst):
        monkeypatch.setattr(api_keys, "YOUTUBE_API_KEYS", list(lst))
        monkeypatch.setattr(api_keys, "_idx", 0)
    return _set


# ---------- 커서/rotate ----------

def test_has_keys_and_empty(keys):
    keys([])
    assert not api_keys.has_keys()
    assert api_keys.key_count() == 0
    assert api_keys.current_key() == ""
    assert api_keys.rotate("anything") is None


def test_single_key_no_next(keys):
    keys(["only"])
    assert api_keys.has_keys() and api_keys.key_count() == 1
    assert api_keys.current_key() == "only"
    assert api_keys.rotate("only") is None          # 다음 키 없음


def test_rotate_advances_and_dedups_stale(keys):
    keys(["a", "b", "c"])
    assert api_keys.current_key() == "a"
    assert api_keys.rotate("a") == "b"              # 전진
    assert api_keys.current_key() == "b"
    assert api_keys.rotate("a") == "b"              # stale 키로 재호출 → 현재키 반환, 재전진 X
    assert api_keys.rotate("b") == "c"
    assert api_keys.rotate("c") is None             # 소진


# ---------- get_with_rotation (httpx) ----------

def test_get_switches_on_quota(keys):
    keys(["k1", "k2"])
    client = _Client({
        "k1": _Resp(403, text="quotaExceeded"),
        "k2": _Resp(200, payload={"ok": True}),
    })
    resp = api_keys.get_with_rotation(client, "http://x", {"part": "snippet"})
    assert resp.json() == {"ok": True}
    assert client.calls == ["k1", "k2"]            # k1 quota → k2 성공
    assert api_keys.current_key() == "k2"          # 커서 전진


def test_get_raises_when_all_quota(keys):
    keys(["k1", "k2"])
    client = _Client({"k1": _Resp(403, text="quota"), "k2": _Resp(403, text="quota")})
    with pytest.raises(RuntimeError):
        api_keys.get_with_rotation(client, "http://x", {})
    assert client.calls == ["k1", "k2"]            # 둘 다 시도 후 소진 → 예외


def test_get_non_quota_403_no_rotation(keys):
    keys(["k1", "k2"])
    client = _Client({"k1": _Resp(403, text="commentsDisabled")})
    with pytest.raises(RuntimeError):
        api_keys.get_with_rotation(client, "http://x", {})
    assert client.calls == ["k1"]                  # quota 아님 → rotation 안 함
    assert api_keys.current_key() == "k1"


def test_get_single_key_success(keys):
    keys(["only"])
    client = _Client({"only": _Resp(200, payload={"a": 1})})
    assert api_keys.get_with_rotation(client, "u", {}).json() == {"a": 1}
    assert client.calls == ["only"]


def test_get_injects_key_not_mutating_params(keys):
    keys(["k1"])
    client = _Client({"k1": _Resp(200, payload={})})
    params = {"part": "snippet"}
    api_keys.get_with_rotation(client, "u", params)
    assert "key" not in params                      # 호출부 dict 불변


# ---------- googleapiclient quota 판정 ----------

def test_is_google_quota_error():
    assert api_keys.is_google_quota_error(_FakeHttpError(403, b'{"reason":"quotaExceeded"}')) is True
    assert api_keys.is_google_quota_error(_FakeHttpError(403, b"userRateLimitExceeded")) is True
    assert api_keys.is_google_quota_error(_FakeHttpError(404, b"quota")) is False
    assert api_keys.is_google_quota_error(_FakeHttpError(403, b"commentsDisabled")) is False
    assert api_keys.is_google_quota_error(RuntimeError("x")) is False
