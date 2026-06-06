"""fetch_transcripts (설계 §4 [8], PR3 fine 단계).

shortlist(~10) 만 자막 fetch — 기존 `fetch_video_transcript`(워커 + 로컬 폴백)를
그대로 재사용한다. 자막은 임베딩/입력 한도 고려해 **first/middle/last 샘플링**
(테크 리뷰는 단점이 중후반에 나옴 — 앞부분 cap 금지). 자막 없으면 None.

⚠️ 차단 위험(설계 §10): shadow 가 자막 fetch 하면 YouTube 호출이 늘어 차단
위험이 커진다. 호출부가 별도 플래그(V3_SHADOW_FETCH_TRANSCRIPTS)로 좁게 게이트.
shadow ephemeral 분석이라 DB(video_transcripts, videos FK)엔 적재하지 않는다.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

_SAMPLE_CHUNK = 1500   # 구간당 문자 수
_MAX_WORKERS = 5       # 설계 §3: Semaphore=5


def sample_transcript(text: str, chunk: int = _SAMPLE_CHUNK) -> str:
    """긴 자막을 first/middle/last 3구간으로 샘플링.

    text 가 3*chunk 이하면 통째 반환. 그보다 길면 앞·중간·뒤 chunk 씩 이어붙임
    (단점이 중후반에 나오므로 앞부분만 자르지 않는다).
    """
    if not text:
        return ""
    if len(text) <= chunk * 3:
        return text
    mid = len(text) // 2
    head = text[:chunk]
    middle = text[mid - chunk // 2 : mid + chunk // 2]
    tail = text[-chunk:]
    return f"{head}\n…\n{middle}\n…\n{tail}"


def _load_cached_transcripts(video_ids: list[str]) -> dict[str, str]:
    """video_transcripts 캐시(v1 self-healing 적재분)를 read-only 조회.

    캐시 HIT 면 YouTube 재fetch 를 건너뛰어 지연·차단 위험을 줄인다(PR4 속도 최적화).
    DB 부재/오류는 best-effort 로 무시(빈 dict).
    """
    if not video_ids:
        return {}
    try:
        from scripts.database.connection import get_connection

        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT video_id, transcript_text FROM video_transcripts "
                "WHERE video_id = ANY(%s)",
                (list(video_ids),),
            )
            return {row[0]: row[1] for row in cur.fetchall() if row[1]}
        finally:
            conn.close()
    except Exception as e:
        print(f"[fine] transcript cache read skipped: {e}", flush=True)
        return {}


def fetch_shortlist_transcripts(video_ids: list[str]) -> tuple[dict[str, str], dict]:
    """shortlist video_id 들의 자막 → {video_id: sampled_text}.

    캐시(video_transcripts) 우선, 미스만 fetch_video_transcript(워커+로컬 폴백)로
    병렬 fetch. 자막 없는 영상은 결과에서 빠진다(호출부가 제목+설명 fallback).
    meta = {attempted, succeeded, failed, cache_hits}.
    """
    meta = {"attempted": len(video_ids), "succeeded": 0, "failed": 0, "cache_hits": 0}
    if not video_ids:
        return {}, meta

    cached = _load_cached_transcripts(video_ids)
    out: dict[str, str] = {vid: sample_transcript(txt) for vid, txt in cached.items()}
    meta["cache_hits"] = len(cached)
    meta["succeeded"] = len(cached)

    misses = [v for v in video_ids if v not in cached]
    if not misses:
        return out, meta

    from scripts.youtube.transcript_service import fetch_video_transcript

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as ex:
        futures = {ex.submit(fetch_video_transcript, vid): vid for vid in misses}
        for fut in as_completed(futures):
            vid = futures[fut]
            try:
                result = fut.result()
            except Exception:
                result = None
            text = (result or {}).get("transcript_text") if result else None
            if text:
                out[vid] = sample_transcript(text)
                meta["succeeded"] += 1
            else:
                meta["failed"] += 1
    return out, meta
