"""FastAPI application factory for the Stilla admin backend.

Startup sequence (lifespan):
  1. Load the spaCy model once into module-level `nlp` — reused by the
     extraction pipeline so the model is never loaded per-request.

Router layout:
  /api/admin   — all KB admin endpoints; protected by X-Admin-Token auth.

Static files:
  frontend/dist is mounted at "/" when it exists (built Vue PWA).
  The directory is absent during development; uvicorn starts regardless.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import spacy
from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from .admin.kb import router as kb_router
from .auth import require_admin_token

logger = logging.getLogger(__name__)

# Populated once during lifespan startup; read by bot/kb pipeline modules.
nlp: spacy.Language | None = None

_FRONTEND_DIST = Path(__file__).parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    """Load heavy singletons on startup; release on shutdown (if needed)."""
    global nlp
    model_name = os.environ.get("SPACY_MODEL", "xx_ent_wiki_sm")
    logger.info("Loading spaCy model '%s'…", model_name)
    nlp = spacy.load(model_name)
    logger.info("spaCy model loaded.")
    yield


app = FastAPI(
    title="Stilla Admin API",
    version="0.1.0",
    lifespan=lifespan,
)

# All /api/admin/** routes require a valid X-Admin-Token header.
app.include_router(
    kb_router,
    prefix="/api/admin",
    dependencies=[Depends(require_admin_token)],
)

# Serve the compiled Vue PWA from Cloud Run (single-artifact deployment).
# Skipped in development where `frontend/dist` does not yet exist.
if _FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="static")
else:
    logger.warning(
        "frontend/dist not found at %s — static file serving disabled. "
        "Run `npm run build` inside frontend/ to enable it.",
        _FRONTEND_DIST,
    )
