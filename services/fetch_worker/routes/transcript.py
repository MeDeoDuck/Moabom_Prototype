"""/transcript — fetch a single YouTube video's transcript by video_id."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from services.fetch_worker.auth import require_bearer
from services.fetch_worker.transcript_logic import fetch_transcript

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
    result = fetch_transcript(req.video_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No transcript available for video_id={req.video_id}",
        )
    return TranscriptResponse(video_id=req.video_id, **result)
