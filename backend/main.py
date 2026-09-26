"""
backend/main.py
----------------
Pitchproof FastAPI application entry point.

Usage:
    uvicorn backend.main:app --reload --port 8000

Or from project root:
    python -m uvicorn backend.main:app --reload
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import router as api_router


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Reads configuration from environment variables (see .env.example):
      CORS_ORIGINS — comma-separated list of allowed origins
      API_HOST     — host to bind (used for docs display only)
      API_PORT     — port to bind (used for docs display only)
    """
    app = FastAPI(
        title="Pitchproof API",
        description=(
            "AI-powered developer workflow assistant for the IBM Bob 2.0 Hackathon.\n\n"
            "Accepts bug reports + repository paths and returns root-cause analysis, "
            "fix plans, proposed code changes, and test cases."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ── CORS ─────────────────────────────────────────────────────────────
    raw_origins = os.environ.get("CORS_ORIGINS", "http://localhost:8501")
    allowed_origins = [o.strip() for o in raw_origins.split(",") if o.strip()]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )

    # ── Root health endpoint ──────────────────────────────────────────────
    @app.get("/health", tags=["health"], summary="Root health check")
    async def root_health():
        """Top-level liveness probe — returns immediately, no agent dependency."""
        return {"status": "ok", "service": "pitchproof"}

    # ── Mount API router ──────────────────────────────────────────────────
    app.include_router(api_router)

    return app


# Module-level app instance for uvicorn
app = create_app()
