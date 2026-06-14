"""/classify — batch classify comments into 3 classes.

PRODUCT_OPINION / VIDEO_REACTION / QUESTION, backed by the klue/roberta-large
3-class checkpoint loaded once on first call. Same Bearer auth as /transcript
and /scope-classify.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from services.fetch_worker.auth import require_bearer
from services.fetch_worker.classify_logic import MODEL_VERSION, classify_batch

MAX_ITEMS = 100

router = APIRouter(dependencies=[Depends(require_bearer)])


class ClassifyRequest(BaseModel):
    comments: list[str] = Field(default_factory=list)


class ClassifyResultOut(BaseModel):
    label: str
    confidence: float
    latency_ms: int


class ClassifyResponse(BaseModel):
    results: list[ClassifyResultOut]
    model_version: str
    total_latency_ms: int


@router.post("/classify", response_model=ClassifyResponse)
def classify(req: ClassifyRequest) -> ClassifyResponse:
    if len(req.comments) > MAX_ITEMS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Too many comments: {len(req.comments)} > {MAX_ITEMS}",
        )
    t0 = time.perf_counter()
    try:
        raw = classify_batch(req.comments)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    total_ms = int((time.perf_counter() - t0) * 1000)
    return ClassifyResponse(
        results=[
            ClassifyResultOut(
                label=r.label,
                confidence=r.confidence,
                latency_ms=r.latency_ms,
            )
            for r in raw
        ],
        model_version=MODEL_VERSION,
        total_latency_ms=total_ms,
    )
