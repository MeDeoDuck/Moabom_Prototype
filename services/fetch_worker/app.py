"""FastAPI app for the YouTube fetch worker.

Runs on the home desktop (residential IP) to bypass datacenter bot detection
on YouTube caption fetch. Exposed to Azure via Tailscale Funnel.
"""
from __future__ import annotations

from fastapi import FastAPI

from services.fetch_worker.routes import embed, health, scope, transcript

app = FastAPI(
    title="Moabom Fetch Worker",
    description=(
        "Residential-IP YouTube fetch (transcript) + GPU scope classifier "
        "+ Qwen3 embedding for Azure offload."
    ),
    version="0.3.0",
)

app.include_router(health.router)
app.include_router(transcript.router)
app.include_router(scope.router)
app.include_router(embed.router)
