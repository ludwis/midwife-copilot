"""POST /api/admin/kb/imports  — Upload chat export and trigger extraction.
GET  /api/admin/kb/imports  — List past import runs (newest first).

Pipeline (background task):
  parse → PII strip each turn → Gemini extract Q&A → dedup + stage
  → update kb_imports (status, chunks_extracted, chunks_flagged_duplicate, completed_at)
  → emit kb_import_completed audit event

Env vars:
  GOOGLE_CLOUD_PROJECT  — GCP project ID
  ADMIN_TOKEN           — checked by require_admin_token dependency (api/auth.py)
"""
from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from google.cloud import firestore

import core.audit
from bot.kb.extractor import extract_qa_pairs
from bot.kb.parsers.messenger import parse_messenger
from bot.kb.parsers.whatsapp import parse_whatsapp
from bot.kb.pii_stripper import strip_pii
from bot.kb.staging import stage_chunks

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB
_VALID_FORMATS = {"whatsapp_txt", "messenger_json"}
_VALID_STATUSES = {"processing", "completed", "failed", "no_pairs_found"}

# Lazy Firestore singleton (same pattern as staging.py)
_firestore_client: firestore.Client | None = None


def _get_firestore() -> firestore.Client:
    global _firestore_client
    if _firestore_client is None:
        _firestore_client = firestore.Client()
    return _firestore_client


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


# ---------------------------------------------------------------------------
# Background pipeline
# ---------------------------------------------------------------------------


async def _run_pipeline(
    import_id: str,
    source_format: str,
    file_content: bytes,
    original_filename: str,
) -> None:
    """Full extraction pipeline; called via BackgroundTasks."""
    db = _get_firestore()
    import_ref = db.collection("kb_imports").document(import_id)
    started_at = datetime.now(timezone.utc)

    try:
        # 1. Parse raw chat export
        if source_format == "whatsapp_txt":
            text = file_content.decode("utf-8", errors="replace")
            turns = parse_whatsapp(text)
        else:  # messenger_json
            # parse_messenger reads from file paths, so write to a temp file
            suffix = ".json"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(file_content)
                tmp_path = tmp.name
            try:
                turns = parse_messenger([tmp_path])
            finally:
                os.unlink(tmp_path)

        # 2. PII-strip each turn's content before passing to Gemini
        stripped_turns = []
        for turn in turns:
            stripped_content, _flag = strip_pii(turn["content"])
            stripped_turns.append({**turn, "content": stripped_content})

        # 3. Gemini Q&A extraction
        chunks = extract_qa_pairs(stripped_turns)

        if not chunks:
            now = datetime.now(timezone.utc)
            import_ref.update(
                {
                    "status": "no_pairs_found",
                    "completed_at": now,
                    "chunks_extracted": 0,
                    "chunks_flagged_duplicate": 0,
                }
            )
            core.audit.write_event(
                "kb_import_completed",
                actor="midwife",
                import_id=import_id,
                status="no_pairs_found",
                chunks_extracted=0,
                chunks_flagged_duplicate=0,
                duration_ms=int((now - started_at).total_seconds() * 1000),
            )
            return

        # 4. Dedup + stage into Firestore + Vertex AI (best-effort)
        chunk_ids = await stage_chunks(chunks, import_id, client=None)

        # Count how many staged chunks were flagged as duplicates
        chunks_flagged = 0
        for chunk_id in chunk_ids:
            doc = db.collection("kb_chunks").document(chunk_id).get()
            if doc.exists and doc.to_dict().get("duplicate_flag"):
                chunks_flagged += 1

        completed_at = datetime.now(timezone.utc)

        # 5. Update kb_imports with final status
        import_ref.update(
            {
                "status": "completed",
                "completed_at": completed_at,
                "chunks_extracted": len(chunk_ids),
                "chunks_flagged_duplicate": chunks_flagged,
            }
        )

        core.audit.write_event(
            "kb_import_completed",
            actor="midwife",
            import_id=import_id,
            status="completed",
            chunks_extracted=len(chunk_ids),
            chunks_flagged_duplicate=chunks_flagged,
            duration_ms=int((completed_at - started_at).total_seconds() * 1000),
        )

    except Exception as exc:  # noqa: BLE001
        logger.exception("Import pipeline failed for import_id=%s", import_id)
        failed_at = datetime.now(timezone.utc)
        import_ref.update(
            {
                "status": "failed",
                "completed_at": failed_at,
                "error_message": str(exc),
            }
        )
        core.audit.write_event(
            "kb_import_completed",
            actor="midwife",
            import_id=import_id,
            status="failed",
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/imports", status_code=202)
async def create_import(
    background_tasks: BackgroundTasks,
    file: UploadFile,
    source_format: str = Form(...),
) -> JSONResponse:
    """Upload a chat export file and enqueue the extraction pipeline."""
    if source_format not in _VALID_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid source_format {source_format!r}. "
                f"Must be 'whatsapp_txt' or 'messenger_json'."
            ),
        )

    content = await file.read()
    if len(content) > _MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")

    original_filename = file.filename or ""
    filename_hash = hashlib.sha256(original_filename.encode()).hexdigest()

    db = _get_firestore()
    now = datetime.now(timezone.utc)
    doc_ref = db.collection("kb_imports").document()
    import_id = doc_ref.id

    doc_ref.set(
        {
            "filename_hash": filename_hash,
            "source_format": source_format,
            "submitted_at": now,
            "submitted_by": "midwife",
            "status": "processing",
        }
    )

    core.audit.write_event(
        "kb_import_started",
        actor="midwife",
        import_id=import_id,
        source_format=source_format,
        filename_hash=filename_hash,
    )

    background_tasks.add_task(
        _run_pipeline,
        import_id=import_id,
        source_format=source_format,
        file_content=content,
        original_filename=original_filename,
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
        query = query.where("status", "==", status)

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
