"""
YouTube transcript fetching service using youtube-transcript-api.

Uses YouTube's official caption endpoint via youtube-transcript-api,
which generally bypasses the IP-based bot detection that affects
yt-dlp on data-center egress IPs (e.g. Azure Container Apps).
"""
from typing import Optional, Dict, Any
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
    CouldNotRetrieveTranscript,
)


def fetch_video_transcript(video_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch a YouTube transcript for the given video.

    Prefers Korean, falls back to English. Returns None when the video
    has no transcripts, transcripts are disabled, or the video is
    unavailable.

    Returns:
        {
            "transcript_text": str,   # whitespace-joined caption segments
            "language_code": str,     # e.g. "ko", "en"
            "segment_count": int,     # number of caption segments
        }
    """
    print(f"[TRANSCRIPT] Fetching for video_id={video_id}")

    try:
        listing = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = listing.find_transcript(["ko", "en"])
        segments = transcript.fetch()
        language_code = transcript.language_code
    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable):
        print(f"[TRANSCRIPT] No transcript available for {video_id}")
        return None
    except CouldNotRetrieveTranscript as e:
        print(f"[TRANSCRIPT] Retrieval failed: {type(e).__name__}: {str(e)[:150]}")
        return None
    except Exception as e:
        print(f"[TRANSCRIPT] Unexpected error: {type(e).__name__}: {str(e)[:150]}")
        return None

    if not segments:
        print(f"[TRANSCRIPT] Empty segments for {video_id}")
        return None

    transcript_text = " ".join(
        seg["text"].strip() for seg in segments if seg.get("text")
    ).strip()

    if not transcript_text:
        print(f"[TRANSCRIPT] All segments empty for {video_id}")
        return None

    print(
        f"[TRANSCRIPT] SUCCESS: {len(transcript_text)} chars, "
        f"language={language_code}, segments={len(segments)}"
    )

    return {
        "transcript_text": transcript_text,
        "language_code": language_code,
        "segment_count": len(segments),
    }
