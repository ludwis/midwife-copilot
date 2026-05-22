"""POST /api/admin/kb/imports  — Upload chat export to GCS and create Firestore doc.
GET  /api/admin/kb/imports  — List past import runs (newest first).

Pipeline (event-driven via Firebase Function):
  Firestore document.create on kb_imports triggers Phase 2 Firebase Function,
  which downloads from GCS, runs extraction, and updates the document.

Env vars:
  GOOGLE_CLOUD_PROJECT  — GCP project ID
  KB_IMPORTS_BUCKET_NAME — GCS bucket for uploaded chat exports
  ADMIN_TOKEN           — checked by require_admin_token dependency (api/auth.py)
"""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from google.cloud import firestore, storage

import core.audit

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB
_VALID_FORMATS = {"whatsapp_txt", "messenger_json"}
_VALID_STATUSES = {"processing", "completed", "failed", "no_pairs_found"}

KB_IMPORTS_BUCKET_NAME = os.environ.get("KB_IMPORTS_BUCKET_NAME", "")

# Lazy singletons
_firestore_client: firestore.Client | None = None
_gcs_client: storage.Client | None = None


def _get_firestore() -> firestore.Client:
    global _firestore_client
    if _firestore_client is None:
        _firestore_client = firestore.Client()
    return _firestore_client


def _get_gcs() -> storage.Client:
    global _gcs_client
    if _gcs_client is None:
        _gcs_client = storage.Client()
    return _gcs_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ts_to_str(ts: Any) -> str | None:
    """Convert a Firestore Timestamp / datetime to ISO-8601 string, or None."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        dt = ts
    else:
        # google.cloud.firestore DatetimeWithNanoseconds or similar
        try:
            dt = ts.astimezone(timezone.utc)
        except AttributeError:
            return str(ts)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _doc_to_summary(doc_id: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "import_id": doc_id,
        "source_format": data.get("source_format", ""),
        "status": data.get("status", ""),
        "submitted_at": _ts_to_str(data.get("submitted_at")) or "",
        "completed_at": _ts_to_str(data.get("completed_at")),
        "chunks_extracted": data.get("chunks_extracted"),
        "chunks_flagged_duplicate": data.get("chunks_flagged_duplicate"),
    }


def _doc_to_detail(doc_id: str, data: dict[str, Any]) -> dict[str, Any]:
    detail = _doc_to_summary(doc_id, data)
    detail["error_message"] = data.get("error_message")
    return detail


def _extension_for_format(source_format: str) -> str:
    """Return the file extension for a given source format."""
    if source_format == "whatsapp_txt":
        return ".txt"
    return ".json"  # messenger_json


def _upload_import_file(
    content: bytes,
    import_id: str,
    filename_hash: str,
    source_format: str,
) -> str:
    """Upload file bytes to GCS and return the gs:// URI.

    Raises RuntimeError if KB_IMPORTS_BUCKET_NAME is not set.
    """
    if not KB_IMPORTS_BUCKET_NAME:
        raise RuntimeError(
            "KB_IMPORTS_BUCKET_NAME environment variable is not set"
        )
    ext = _extension_for_format(source_format)
    blob_name = f"imports/{import_id}/{filename_hash}{ext}"
    bucket = _get_gcs().bucket(KB_IMPORTS_BUCKET_NAME)
    blob = bucket.blob(blob_name)
    blob.upload_from_string(content)
    return f"gs://{KB_IMPORTS_BUCKET_NAME}/{blob_name}"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/imports", status_code=202)
async def create_import(
    file: UploadFile,
    source_format: str = Form(...),
) -> JSONResponse:
    """Upload a chat export file to GCS and create a Firestore import doc."""
    if source_format not in _VALID_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid source_format {source_format!r}. "
                f"Must be 'whatsapp_txt' or 'messenger_json'."
            ),
        )

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > _MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")

    original_filename = file.filename or ""
    filename_hash = hashlib.sha256(original_filename.encode()).hexdigest()

    # Allocate the Firestore doc ref first so we know the import_id for the GCS path.
    db = _get_firestore()
    doc_ref = db.collection("kb_imports").document()
    import_id = doc_ref.id

    # Upload to GCS before any Firestore write; fail fast on storage errors.
    try:
        gcs_path = _upload_import_file(content, import_id, filename_hash, source_format)
    except Exception as exc:
        logger.exception("GCS upload failed for import_id=%s", import_id)
        raise HTTPException(status_code=500, detail=f"File upload failed: {exc}") from exc

    now = datetime.now(timezone.utc)
    doc_ref.set(
        {
            "filename_hash": filename_hash,
            "source_format": source_format,
            "submitted_at": now,
            "submitted_by": "midwife",
            "status": "processing",
            "gcs_path": gcs_path,
        }
    )

    core.audit.write_event(
        "kb_import_started",
        actor="midwife",
        import_id=import_id,
        source_format=source_format,
        filename_hash=filename_hash,
    )

    submitted_at_str = (
        now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    )
    return JSONResponse(
        status_code=202,
        content={
            "import_id": import_id,
            "status": "processing",
            "submitted_at": submitted_at_str,
        },
    )


@router.get("/imports")
async def list_imports(
    status: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """List past import runs, newest first."""
    if status is not None and status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status filter {status!r}.",
        )
    limit = min(max(limit, 1), 100)

    db = _get_firestore()
    query = db.collection("kb_imports").order_by(
        "submitted_at", direction=firestore.Query.DESCENDING
    )
    if status is not None:
        query = query.where(filter=firestore.FieldFilter("status", "==", status))

    docs = list(query.limit(limit).stream())

    return {
        "imports": [_doc_to_summary(doc.id, doc.to_dict()) for doc in docs]
    }


@router.get("/imports/{import_id}")
async def get_import(import_id: str) -> dict[str, Any]:
    """Fetch details of a single import run by ID. Returns 404 if not found."""
    db = _get_firestore()
    doc = db.collection("kb_imports").document(import_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Import not found")
    return _doc_to_detail(doc.id, doc.to_dict())
