#!/usr/bin/env python3
"""
YouTube Tech Product Review Analysis Service - Modularized Version

Main entry point for the FastAPI application.
All functionality is modularized into scripts/ folder.

Usage:
    python main.py
    python main.py 8001  # custom port
"""
import os
import sys
import uvicorn
from pathlib import Path

# Force UTF-8 stdout so Korean text and emoji print correctly on Windows cp949 consoles
sys.stdout.reconfigure(encoding="utf-8")
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

# Import database initialization
from scripts.database.schema import init_db

# Import API route registrations
from scripts.api.products import register_product_routes
from scripts.api.videos import register_video_routes
from scripts.api.sync import register_sync_routes
from scripts.api.admin import register_admin_routes
from video_selection_agent.api.routes import register_selection_routes
from scripts.tracking import UsageTrackingMiddleware, GATagMiddleware


# ============================================================================
# FASTAPI APP INITIALIZATION
# ============================================================================

app = FastAPI(title="YouTube Product Analysis Service")


# Add middleware to set UTF-8 charset for HTML responses
class UTF8CharsetMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if "text/html" in response.headers.get("content-type", ""):
            response.headers["content-type"] = "text/html; charset=utf-8"
        return response


app.add_middleware(UTF8CharsetMiddleware)
app.add_middleware(GATagMiddleware, measurement_id=os.getenv("GA_MEASUREMENT_ID"))
app.add_middleware(UsageTrackingMiddleware)


# Ensure templates directory exists
TEMPLATES_DIR = Path("templates")
TEMPLATES_DIR.mkdir(exist_ok=True)


@app.on_event("startup")
async def startup_event():
    """Initialize database on startup."""
    print("[STARTUP] Initializing database...")
    init_db()
    print("[STARTUP] Database ready")


# ============================================================================
# REGISTER ALL ROUTES
# ============================================================================

print("[STARTUP] Registering API routes...")
register_product_routes(app)
register_video_routes(app)
register_sync_routes(app)
register_admin_routes(app)
register_selection_routes(app)
print("[STARTUP] All routes registered")


# ============================================================================
# APP ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    
    # Allow command line override: python main.py 8001
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    
    print(f"\n{'='*70}")
    print(f"  YouTube Tech Product Review Analysis Service")
    print(f"  Modularized version - All code in scripts/ folder")
    print(f"{'='*70}")
    print(f"  🚀 Starting server on http://0.0.0.0:{port}")
    print(f"  📁 Project root: {Path.cwd()}")
    print(f"  📋 Templates: {TEMPLATES_DIR}")
    print(f"{'='*70}\n")
    
    uvicorn.run(app, host="0.0.0.0", port=port)
