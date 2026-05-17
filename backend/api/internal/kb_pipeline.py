"""Cloud Tasks KB pipeline worker — POST /internal/kb/process-import/{import_id}.

Authentication is via Google OIDC tokens (issued by Cloud Tasks).
The endpoint runs the full parse → PII strip → Gemini extract → stage pipeline.

Error handling contract:
  Fatal errors  → write status=failed, return HTTP 200 (no retry)
  Transient errors → write status=failed, return HTTP 503 (Cloud Tasks retries)
  Always write status=failed before returning any error response.
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import traceback
from datetime import datetime, timezone

import google.api_core.exceptions
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from google.cloud import firestore, storage

import core.audit
from bot.kb.extractor import extract_qa_pairs
from bot.kb.parsers.messenger import parse_messenger
from bot.kb.parsers.whatsapp import parse_whatsapp
from bot.kb.pii_stripper import strip_pii
from bot.kb.staging import stage_chunks

from .auth import require_tasks_oidc

logger = logging.getLogger(__name__)

router = APIRouter()

_TRANSIENT_EXC = (
    google.api_core.exceptions.ServiceUnavailable,
    google.api_core.exceptions.DeadlineExceeded,
    ConnectionError,
    TimeoutError,
)

# Lazy Firestore singleton (shared with staging.py pattern)
_db: firestore.Client | None = None


def _get_db() -> firestore.Client:
    global _db
    if _db is None:
        _db = firestore.Client()
    return _db


def _is_transient(exc: Exception) -> bool:
    return isinstance(exc, _TRANSIENT_EXC)


@router.post("/kb/process-import/{import_id}", dependencies=[Depends(require_tasks_oidc)])
async def process_import(import_id: str) -> JSONResponse:
    db = _get_db()
    import_ref = db.collection("kb_imports").document(import_id)

    # --- Step 1: Idempotency guard via Firestore transaction ---
    snapshot = import_ref.get()
    if not snapshot.exists:
        return JSONResponse({"status": "skipped", "reason": "not_found"}, status_code=200)

    doc = snapshot.to_dict() or {}
    if doc.get("status") != "processing":
        return JSONResponse({"status": "skipped", "reason": doc.get("status")}, status_code=200)

    now = datetime.now(timezone.utc)

    @firestore.transactional
    def _claim(transaction: firestore.Transaction, ref: firestore.DocumentReference) -> bool:
        snap = ref.get(transaction=transaction)
        if (snap.to_dict() or {}).get("status") != "processing":
            return False
        transaction.update(ref, {"status": "extracting", "started_at": now})
        return True

    try:
        transaction = db.transaction()
        claimed = _claim(transaction, import_ref)
    except Exception:
        return JSONResponse({"status": "skipped", "reason": "concurrent_claim"}, status_code=200)

    if not claimed:
        return JSONResponse({"status": "skipped", "reason": "concurrent_claim"}, status_code=200)

    source_format = doc.get("source_format", "")

    try:
        # --- Step 2: Download from GCS ---
        bucket_name = os.environ.get("KB_IMPORTS_BUCKET_NAME", "")
        gcs_client = storage.Client()
        bucket_obj = gcs_client.bucket(bucket_name)
        blobs = list(bucket_obj.list_blobs(prefix=f"imports/{import_id}/"))

        if not blobs:
            import_ref.update({
                "status": "failed",
                "error_message": "GCS file not found",
                "completed_at": datetime.now(timezone.utc),
            })
            return JSONResponse({"status": "failed"}, status_code=200)

        file_bytes = blobs[0].download_as_bytes()

        # --- Step 3: Parse ---
        if source_format == "whatsapp_txt":
            text = file_bytes.decode("utf-8")
            turns = parse_whatsapp(text)
        elif source_format == "messenger_json":
            tmp_path: str | None = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
                    tmp.write(file_bytes)
                    tmp_path = tmp.name
                turns = parse_messenger([tmp_path])
            finally:
                if tmp_path:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
        else:
            import_ref.update({
                "status": "failed",
                "error_message": f"Unsupported source_format: {source_format}",
                "completed_at": datetime.now(timezone.utc),
            })
            return JSONResponse({"status": "failed"}, status_code=200)

        # Best-effort progress field
        try:
            import_ref.update({"turns_parsed": len(turns)})
        except Exception:  # noqa: BLE001
            pass

        # --- Step 4: PII stripping ---
        for turn in turns:
            stripped, _ = strip_pii(turn["content"])
            turn["content"] = stripped

        # --- Step 5: Gemini extraction ---
        chunks = await asyncio.to_thread(extract_qa_pairs, turns)

        if not chunks:
            import_ref.update({"status": "no_pairs_found", "completed_at": datetime.now(timezone.utc)})
            core.audit.write_event(
                "kb_import_completed",
                actor="system",
                import_id=import_id,
                result="no_pairs_found",
            )
            return JSONResponse({"status": "no_pairs_found"}, status_code=200)

        # --- Step 6: Stage chunks ---
        chunk_ids = await stage_chunks(chunks, import_id, client=None)

        # --- Step 7: Count duplicates and update Firestore ---
        dup_query = (
            db.collection("kb_chunks")
            .where("import_id", "==", import_id)
            .where("duplicate_flag", "in", ["exact", "near"])
        )
        dup_count = len(dup_query.get())

        import_ref.update({
            "status": "completed",
            "completed_at": datetime.now(timezone.utc),
            "chunks_extracted": len(chunk_ids),
            "chunks_flagged_duplicate": dup_count,
        })

        # --- Step 8: Audit event + GCS cleanup ---
        core.audit.write_event(
            "kb_import_completed",
            actor="system",
            import_id=import_id,
            result="completed",
            chunks_extracted=len(chunk_ids),
            chunks_flagged_duplicate=dup_count,
        )

        try:
            for blob in blobs:
                blob.delete()
        except Exception:  # noqa: BLE001
            pass

        return JSONResponse({"status": "completed"}, status_code=200)

    except Exception as exc:
        logger.error(
            "KB pipeline failed for import %s:\n%s", import_id, traceback.format_exc()
        )
        import_ref.update({
            "status": "failed",
            "error_message": str(exc)[:500],
            "completed_at": datetime.now(timezone.utc),
        })
        if _is_transient(exc):
            raise HTTPException(status_code=503, detail=str(exc))
        return JSONResponse({"status": "failed"}, status_code=200)
