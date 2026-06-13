"""YouTube Data API v3 키 풀 + quota/403 자동 failover (P1).

`.env` 의 `YOUTUBE_API_KEYS`(`;` 구분)만 채우면 모든 호출부가 자동 rotation 한다.
단일 `YOUTUBE_API_KEY` 와 100% 호환(키 1개짜리 풀). 커서는 프로세스 전역·스레드
안전 — quotaExceeded(403) 난 키는 다음 키로 전진해 그날 다시 쓰지 않는다. 키가
전부 소진되면 호출부가 받던 원래 예외를 그대로 올린다(기존 안전 퇴화 유지).

- httpx 호출부: ``get_with_rotation(client, url, params)`` 한 줄로 교체.
- googleapiclient 호출부(댓글 수집기): ``current_key()`` 로 시작 + 예외에
  ``is_google_quota_error()`` 면 ``rotate()`` 후 클라이언트 재생성.

키 소비량(search.list=100유닛/콜)이 일 quota(키당 10k)를 빨리 소진하므로 서로 다른
GCP 프로젝트 키 여러 개를 돌려 quota 를 늘리는 것이 목적. (계획: v3 fallback 감축 P1)
"""
from __future__ import annotations

import threading

import httpx

from scripts.config import YOUTUBE_API_KEYS

_lock = threading.Lock()
_idx = 0


def has_keys() -> bool:
    return bool(YOUTUBE_API_KEYS)


def key_count() -> int:
    return len(YOUTUBE_API_KEYS)


def current_key() -> str:
    """현재 커서가 가리키는 키. 키가 없으면 빈 문자열."""
    with _lock:
        return YOUTUBE_API_KEYS[_idx] if YOUTUBE_API_KEYS else ""


def rotate(failed_key: str) -> str | None:
    """`failed_key` 가 현재 키면 다음 키로 커서를 전진시키고 그 키를 반환한다.

    더 쓸 키가 없으면 None. 다른 스레드가 이미 전진시켰으면(현재 키 != failed_key)
    중복 전진 없이 현재(새) 키를 반환한다.
    """
    global _idx
    with _lock:
        if not YOUTUBE_API_KEYS:
            return None
        if YOUTUBE_API_KEYS[_idx] != failed_key:
            return YOUTUBE_API_KEYS[_idx]          # 이미 누가 돌림 → 새 키 사용
        if _idx + 1 >= len(YOUTUBE_API_KEYS):
            return None                            # 마지막 키까지 소진
        _idx += 1
        print(
            f"[youtube_api_keys] quota/403 → rotate to key #{_idx + 1}/{len(YOUTUBE_API_KEYS)}",
            flush=True,
        )
        return YOUTUBE_API_KEYS[_idx]


# quotaExceeded·dailyLimitExceeded·rateLimitExceeded 는 모두 403. 다른 키로
# 넘기면 별도 quota 버킷이라 회복 가능.
_QUOTA_MARKERS = ("quota", "dailylimit", "ratelimit")


def _is_quota_403(resp: httpx.Response) -> bool:
    if resp.status_code != 403:
        return False
    body = resp.text.lower()
    return any(m in body for m in _QUOTA_MARKERS)


def get_with_rotation(
    client: httpx.Client,
    url: str,
    params: dict,
    *,
    timeout: float = 30.0,
) -> httpx.Response:
    """httpx GET + 키 자동 주입 + quota(403) 시 다음 키 재시도.

    `params` 에 ``key`` 를 넣지 말 것(여기서 주입). 성공 응답을 반환하고, quota 가
    아닌 에러나 모든 키 소진은 ``raise_for_status()`` 로 호출부에 그대로 위임한다
    (기존 동작 보존 — 호출부의 try/except 가 그대로 받는다).
    """
    while True:
        key = current_key()
        merged = dict(params)
        if key:
            merged["key"] = key
        resp = client.get(url, params=merged, timeout=timeout)
        if key and _is_quota_403(resp) and rotate(key) is not None:
            continue                               # 다음 키로 재시도
        resp.raise_for_status()                     # 2xx 통과 / 그 외(소진 포함) 예외
        return resp


def is_google_quota_error(exc: Exception) -> bool:
    """googleapiclient ``HttpError`` 가 quota/403 인지 판정(임포트 의존 없이 duck-type)."""
    resp = getattr(exc, "resp", None)
    status = getattr(resp, "status", None)
    try:
        if int(status) != 403:
            return False
    except (TypeError, ValueError):
        return False
    content = getattr(exc, "content", b"") or b""
    if isinstance(content, bytes):
        content = content.decode("utf-8", "ignore")
    body = content.lower()
    return any(m in body for m in _QUOTA_MARKERS)
