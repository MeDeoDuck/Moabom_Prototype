"""FastAPI app for the YouTube fetch worker.

Runs on the home desktop (residential IP) to bypass datacenter bot detection
on YouTube caption fetch. Exposed to Azure via Tailscale Funnel.
"""
from __future__ import annotations

from fastapi import FastAPI

from services.fetch_worker.routes import health, transcript

app = FastAPI(
    title="Moabom Fetch Worker",
    description="Residential-IP YouTube fetch (transcript) for Azure offload.",
    version="0.1.0",
)

app.include_router(health.router)
app.include_router(transcript.router)
