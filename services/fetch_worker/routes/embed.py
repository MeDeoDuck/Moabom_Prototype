"""/embed — batch text embedding (Qwen3-Embedding-4B, GPU).

v3 coarse_cluster(설계 §6) 임베딩 백엔드. scope 와 동일 Bearer auth.
첫 호출은 모델 cold-load(~수십초) — 호출부(client)는 넉넉한 timeout 사용.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from services.fetch_worker.auth import require_bearer
from services.fetch_worker.embed_logic import EMBED_DIM, MODEL_VERSION, embed_texts

MAX_ITEMS = 64

router = APIRouter(dependencies=[Depends(require_bearer)])


class EmbedRequest(BaseModel):
    texts: list[str] = Field(default_factory=list)


class EmbedResponse(BaseModel):
    vectors: list[list[float]]
    model_version: str
    dim: int
    total_latency_ms: int


@router.post("/embed", response_model=EmbedResponse)
def embed(req: EmbedRequest) -> EmbedResponse:
    if len(req.texts) > MAX_ITEMS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Too many texts: {len(req.texts)} > {MAX_ITEMS}",
        )
    t0 = time.perf_counter()
    try:
        vectors, _ = embed_texts(req.texts)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    total_ms = int((time.perf_counter() - t0) * 1000)
    return EmbedResponse(
        vectors=vectors,
        model_version=MODEL_VERSION,
        dim=EMBED_DIM,
        total_latency_ms=total_ms,
    )
