"""/transcript — fetch a single YouTube video's transcript by video_id."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from services.fetch_worker.auth import require_bearer
from services.fetch_worker.pacing import TRANSCRIPT_PACER
from services.fetch_worker.transcript_logic import fetch_transcript_status

router = APIRouter(dependencies=[Depends(require_bearer)])


class TranscriptRequest(BaseModel):
    video_id: str = Field(min_length=5, max_length=20)


class TranscriptResponse(BaseModel):
    video_id: str
    transcript_text: str
    language_code: str
    segment_count: int


@router.post("/transcript", response_model=TranscriptResponse)
def transcript(req: TranscriptRequest) -> TranscriptResponse:
    # 워커 전역 페이싱: 동시 fetch 수 상한 + 시작 간격 (F2 IP/ASN 밴 예방).
    with TRANSCRIPT_PACER.slot():
        result, rate_limited = fetch_transcript_status(req.video_id)
    if result:
        return TranscriptResponse(video_id=req.video_id, **result)
    if rate_limited:
        # rate-limit/봇차단 → 앱이 재시도·폴백하도록 429 (404='자막 없음'과 구분).
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate-limited fetching transcript for video_id={req.video_id}",
        )
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"No transcript available for video_id={req.video_id}",
    )
