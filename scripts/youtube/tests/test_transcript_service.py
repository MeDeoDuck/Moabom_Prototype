"""앱→워커 자막 fetch 의 429 처리 테스트 (0단계 B, 앱쪽).

워커가 rate-limit(429) 을 반환하면 앱은 5xx 처럼 재시도 후 None(→로컬 폴백)해야 한다.
404('자막 없음')·200(성공)은 기존대로 즉시 처리. 네트워크 없이 requests.post monkeypatch.
"""
from __future__ import annotations

from scripts.youtube import transcript_service as ts


class _Resp:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


def test_worker_429_retries_then_falls_through(monkeypatch):
    monkeypatch.setattr(ts.time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def fake_post(*a, **k):
        calls["n"] += 1
        return _Resp(429, text="Too Many Requests")

    monkeypatch.setattr(ts.requests, "post", fake_post)
    result = ts._fetch_via_worker("vid", "http://w", "tok")
    assert result is None            # 소진 후 None → caller 가 로컬 폴백
    assert calls["n"] == 3           # 429 는 5xx 처럼 3회 재시도 (기존엔 1회 폐기)


def test_worker_404_no_retry(monkeypatch):
    monkeypatch.setattr(ts.time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def fake_post(*a, **k):
        calls["n"] += 1
        return _Resp(404, text="no transcript")

    monkeypatch.setattr(ts.requests, "post", fake_post)
    result = ts._fetch_via_worker("vid", "http://w", "tok")
    assert result is None and calls["n"] == 1   # '자막 없음'은 재시도 안 함(회귀 가드)


def test_worker_200_success(monkeypatch):
    payload = {"transcript_text": "hello", "language_code": "ko", "segment_count": 1}

    def fake_post(*a, **k):
        return _Resp(200, payload=payload)

    monkeypatch.setattr(ts.requests, "post", fake_post)
    result = ts._fetch_via_worker("vid", "http://w", "tok")
    assert result == payload                      # 성공은 그대로(회귀 가드)
