"""Drop candidates whose YouTube videos lack a Korean/English caption track.

자막 가용성 확인 전략:
  1. video_transcripts 테이블에 row 가 이미 있는 영상은 통과
     (이전에 자막을 성공적으로 가져온 영상)
  2. 처음 보는 영상은 youtube-transcript-api 의 list_transcripts() 로
     수동·자동 자막 메타데이터를 받아 ko/en 트랙 존재 여부 확인

호출은 직렬 — 단일 데이터센터 IP 에서의 동시 호출은 봇 탐지를 자극.
후보 풀이 보통 30개 이하라 ~5~15초 추가에 그침.
"""
from __future__ import annotations

from video_selection_agent.graph.state import SelectionState

try:
    from youtube_transcript_api import (
        YouTubeTranscriptApi,
        TranscriptsDisabled,
        NoTranscriptFound,
        VideoUnavailable,
        CouldNotRetrieveTranscript,
    )
    _CAPTION_LIB_AVAILABLE = True
except ImportError:
    _CAPTION_LIB_AVAILABLE = False


_PREFERRED_LANGS = ("ko", "en")


def _videos_with_cached_transcript(video_ids: list[str]) -> set[str]:
    if not video_ids:
        return set()
    from scripts.database.queries import query_all

    rows = query_all(
        "SELECT video_id FROM video_transcripts WHERE video_id = ANY(%s)",
        (video_ids,),
    )
    return {r["video_id"] for r in rows}


def _has_remote_caption(video_id: str) -> bool:
    try:
        listing = YouTubeTranscriptApi.list_transcripts(video_id)
    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable):
        return False
    except CouldNotRetrieveTranscript:
        return False
    except Exception:
        # 일시적 네트워크 오류는 보수적으로 후보를 유지 — 보고서 단계에서 다시 검증됨
        return True

    for t in listing:
        if t.language_code in _PREFERRED_LANGS:
            return True
    return False


def filter_captioned_videos(state: SelectionState) -> SelectionState:
    candidates = state.get("candidates", [])
    trace = list(state.get("trace", []))

    if not candidates:
        trace.append("filter_captioned_videos: no candidates to inspect")
        return {**state, "candidates": candidates, "trace": trace}

    if not _CAPTION_LIB_AVAILABLE:
        trace.append(
            "filter_captioned_videos: youtube-transcript-api unavailable — skip"
        )
        return {**state, "candidates": candidates, "trace": trace}

    video_ids = [c.video_id for c in candidates if c.video_id]
    cached = _videos_with_cached_transcript(video_ids)

    kept = []
    probed = 0
    for c in candidates:
        if c.video_id in cached:
            kept.append(c)
            continue
        probed += 1
        if _has_remote_caption(c.video_id):
            kept.append(c)

    dropped = len(candidates) - len(kept)
    trace.append(
        f"filter_captioned_videos: kept {len(kept)}/{len(candidates)} "
        f"(cached={len(cached)}, probed={probed}, dropped={dropped})"
    )
    return {**state, "candidates": kept, "trace": trace}
