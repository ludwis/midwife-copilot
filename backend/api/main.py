"""FastAPI application factory for the Stilla admin backend.

Startup sequence (lifespan):
  1. Initialise Vertex AI client.
  2. Load the spaCy model once into module-level `nlp` — reused by the
     extraction pipeline so the model is never loaded per-request.
  The embedding deduplication cache loads lazily on first pipeline run.

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

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import spacy
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .admin.kb import router as kb_router
from .auth import require_firebase_token
from .internal.kb_pipeline import router as pipeline_router

logger = logging.getLogger(__name__)

# Populated once during lifespan startup; read by bot/kb pipeline modules.
nlp: spacy.Language | None = None

_FRONTEND_DIST = Path(__file__).parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    """Load heavy singletons on startup; release on shutdown (if needed)."""
    global nlp

    import firebase_admin  # type: ignore[import]
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
        logger.info("Firebase Admin SDK initialised.")

    import vertexai  # type: ignore[import]
    project = os.environ.get("GCP_PROJECT_ID", "")
    vertexai.init(project=project, location="global")
    logger.info("Vertex AI initialised (project=%s, location=global)", project)

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

# CORS: allow Firebase Hosting origins + localhost dev server.
# Override via CORS_ORIGINS env var (comma-separated) if needed.
_default_origins = [
    "https://midwife-copilot.web.app",
    "https://midwife-copilot.firebaseapp.com",
    "http://localhost:5173",
    "http://localhost:4173",  # vite preview
]
_cors_origins = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", "").split(",")
    if o.strip()
] or _default_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Return errors as {error: ...} per the contract's ErrorResponse schema."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail},
        headers=dict(exc.headers) if exc.headers else None,
    )

# All /api/admin/** routes require a valid Firebase ID token.
app.include_router(
    kb_router,
    prefix="/api/admin",
    dependencies=[Depends(require_firebase_token)],
)

# Internal service-to-service routes (auth handled per-route via OIDC).
app.include_router(pipeline_router, prefix="/internal")

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
