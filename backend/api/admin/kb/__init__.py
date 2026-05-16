"""KB admin sub-package.

Individual route modules (imports.py, chunks.py, production.py) are added
in later tasks. This package exposes a single `router` that main.py mounts
under /api/admin.
"""
from fastapi import APIRouter

from .chunks import router as chunks_router
from .imports import router as imports_router
from .production import router as production_router

router = APIRouter(prefix="/kb", tags=["kb"])
router.include_router(imports_router)
router.include_router(chunks_router)
router.include_router(production_router)
