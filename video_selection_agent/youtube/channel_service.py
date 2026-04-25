"""channels.list 래퍼. 구독자 수·채널명 조회."""
from __future__ import annotations

from typing import Iterable

import httpx

from scripts.config import YOUTUBE_API_KEY


_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"


def _chunked(seq: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def fetch_channel_metadata(channel_ids: list[str]) -> dict[str, dict]:
    """channels.list → {channel_id: {name, subscriber_count}}."""
    if not YOUTUBE_API_KEY or not channel_ids:
        return {}

    unique_ids = list({cid for cid in channel_ids if cid})
    out: dict[str, dict] = {}

    with httpx.Client() as client:
        for chunk in _chunked(unique_ids, 50):
            params = {
                "part": "snippet,statistics",
                "id": ",".join(chunk),
                "key": YOUTUBE_API_KEY,
            }
            try:
                resp = client.get(_CHANNELS_URL, params=params, timeout=30.0)
                resp.raise_for_status()
            except httpx.HTTPError as e:
                print(f"[channel_service] channels.list failed: {e}")
                continue

            for item in resp.json().get("items", []):
                cid = item.get("id")
                if not cid:
                    continue
                snippet = item.get("snippet", {})
                stats = item.get("statistics", {})
                out[cid] = {
                    "name": snippet.get("title", ""),
                    "subscriber_count": int(stats.get("subscriberCount", 0) or 0),
                    "hidden_subscriber_count": bool(
                        stats.get("hiddenSubscriberCount", False)
                    ),
                }
    return out
