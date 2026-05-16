"""KB admin sub-package.

Individual route modules (imports.py, chunks.py, production.py) are added
in later tasks. This package exposes a single `router` that main.py mounts
under /api/admin.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/kb", tags=["kb"])
