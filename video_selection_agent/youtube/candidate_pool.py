"""다중 쿼리 후보 풀 수집.

쿼리 4종 병렬:
  - "{product} 리뷰"
  - "{product} review"
  - "{product} 단점"
  - "{brand} {product}" (brand가 있을 때)
각 쿼리 15~20건 → search.list → videos.list 로 metadata 보강 → dedupe.
`scripts.youtube.video_service`는 팀원 코드라 복제하지 않고 별개 모듈로 구현.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable

import httpx

from scripts.config import YOUTUBE_API_KEY
from video_selection_agent.core.models import ProductContext, VideoCandidate


_PER_QUERY_LIMIT = 18
_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


def _build_queries(product: ProductContext) -> list[str]:
    name = product.name.strip()
    queries = [f"{name} 리뷰", f"{name} review", f"{name} 단점"]
    if product.brand:
        queries.append(f"{product.brand} {name}")
    return queries


_ISO_DURATION_RE = re.compile(
    r"P(?:\d+D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?"
)


def parse_iso8601_duration(value: str) -> int:
    """YouTube 'PT1H2M3S' → 초 단위. 파싱 실패 시 0."""
    if not value:
        return 0
    m = _ISO_DURATION_RE.fullmatch(value)
    if not m:
        return 0
    h, mn, s = m.groups()
    return int(h or 0) * 3600 + int(mn or 0) * 60 + int(s or 0)


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


def _search_once(client: httpx.Client, query: str, limit: int) -> list[str]:
    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "videoEmbeddable": "true",
        "maxResults": limit,
        "key": YOUTUBE_API_KEY,
    }
    resp = client.get(_SEARCH_URL, params=params, timeout=30.0)
    resp.raise_for_status()
    data = resp.json()
    ids: list[str] = []
    for item in data.get("items", []):
        vid = item.get("id", {}).get("videoId")
        if vid:
            ids.append(vid)
    return ids


def _fetch_video_details(
    client: httpx.Client, video_ids: list[str]
) -> dict[str, dict]:
    """videos.list는 한 번에 최대 50 ID 처리."""
    details: dict[str, dict] = {}
    for chunk in _chunked(video_ids, 50):
        params = {
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(chunk),
            "key": YOUTUBE_API_KEY,
        }
        resp = client.get(_VIDEOS_URL, params=params, timeout=30.0)
        resp.raise_for_status()
        for item in resp.json().get("items", []):
            details[item["id"]] = item
    return details


def _chunked(seq: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _to_candidate(
    video_id: str,
    item: dict,
    source_query: str,
) -> VideoCandidate | None:
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    content = item.get("contentDetails", {})
    duration = parse_iso8601_duration(content.get("duration", ""))
    if duration <= 60:  # Shorts / 0초 처리
        return None
    if content.get("liveBroadcastContent") == "live":
        return None

    return VideoCandidate(
        video_id=video_id,
        title=snippet.get("title", ""),
        description=snippet.get("description", ""),
        channel_id=snippet.get("channelId", ""),
        channel_name=snippet.get("channelTitle", ""),
        published_at=_parse_datetime(snippet.get("publishedAt")),
        duration_seconds=duration,
        view_count=int(stats.get("viewCount", 0) or 0),
        like_count=int(stats.get("likeCount", 0) or 0),
        comment_count=int(stats.get("commentCount", 0) or 0),
        channel_subscriber_count=0,  # enrich_metadata 단계에서 채움
        thumbnail_url=(
            snippet.get("thumbnails", {}).get("medium", {}).get("url", "")
        ),
        source_query=source_query,
    )


def build_candidate_pool(
    product: ProductContext,
    target_size: int = 30,
) -> list[VideoCandidate]:
    """각 쿼리로 search → videos.list 로 metadata 보강 → dedupe → target_size까지."""
    if not YOUTUBE_API_KEY:
        return []

    queries = _build_queries(product)
    candidates: dict[str, VideoCandidate] = {}

    with httpx.Client() as client:
        id_to_query: dict[str, str] = {}
        all_ids: list[str] = []
        for query in queries:
            try:
                ids = _search_once(client, query, _PER_QUERY_LIMIT)
            except httpx.HTTPError as e:
                print(f"[candidate_pool] search failed '{query}': {e}")
                continue
            for vid in ids:
                if vid not in id_to_query:
                    id_to_query[vid] = query
                    all_ids.append(vid)

        if not all_ids:
            return []

        try:
            details = _fetch_video_details(client, all_ids)
        except httpx.HTTPError as e:
            print(f"[candidate_pool] videos.list failed: {e}")
            return []

    for vid, item in details.items():
        candidate = _to_candidate(vid, item, id_to_query.get(vid, ""))
        if candidate:
            candidates[vid] = candidate

    pool = list(candidates.values())
    # view_count 내림차순으로 target_size 까지 절삭 (대형 채널 bias는 스코어링에서 보정)
    pool.sort(key=lambda c: c.view_count, reverse=True)
    return pool[:target_size]
