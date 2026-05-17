"""Cloud Workflows KB pipeline worker — POST /internal/kb/process-import/{import_id}.

Authentication is via Google OIDC tokens (issued by Cloud Workflows).
The endpoint claims the import, returns 202 immediately, and runs the full
parse → PII strip → Gemini extract → stage pipeline as a background task.

The pipeline can run for 20–40 minutes. Returning 202 immediately decouples
the workflow's 30-minute HTTP step timeout from the actual pipeline duration.

Error handling:
  Fatal errors    → write status=failed, background task exits silently
  Transient errors → write status=processing so a workflow retry can reclaim it
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import traceback
from datetime import datetime, timezone

import google.api_core.exceptions
from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import JSONResponse
from google.cloud import firestore, storage

import core.audit
from bot.kb.extractor import extract_qa_pairs_async
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

_db: firestore.Client | None = None


def _get_db() -> firestore.Client:
    global _db
    if _db is None:
        _db = firestore.Client()
    return _db


def _is_transient(exc: Exception) -> bool:
    return isinstance(exc, _TRANSIENT_EXC)


@router.post("/kb/process-import/{import_id}", dependencies=[Depends(require_tasks_oidc)])
async def process_import(import_id: str, background_tasks: BackgroundTasks) -> JSONResponse:
    """Accept a KB import, claim it, and start the pipeline in the background."""
    db = _get_db()
    import_ref = db.collection("kb_imports").document(import_id)

    # --- Idempotency guard via Firestore transaction ---
    snapshot = import_ref.get()
    if not snapshot.exists:
        return JSONResponse({"status": "skipped", "reason": "not_found"})

    doc = snapshot.to_dict() or {}
    if doc.get("status") != "processing":
        return JSONResponse({"status": "skipped", "reason": doc.get("status")})

    now = datetime.now(timezone.utc)

    @firestore.transactional
    def _claim(transaction: firestore.Transaction, ref: firestore.DocumentReference) -> bool:
        snap = ref.get(transaction=transaction)
        if (snap.to_dict() or {}).get("status") != "processing":
            return False
        transaction.update(ref, {"status": "extracting", "started_at": now})
        return True

    try:
        claimed = _claim(db.transaction(), import_ref)
    except Exception:
        return JSONResponse({"status": "skipped", "reason": "concurrent_claim"})

    if not claimed:
        return JSONResponse({"status": "skipped", "reason": "concurrent_claim"})

    source_format = doc.get("source_format", "")

    # Start the pipeline and return 202 immediately.
    # The workflow's HTTP step completes as soon as it receives this response;
    # the actual extraction continues independently in the background.
    background_tasks.add_task(_run_pipeline, import_id, source_format, import_ref, now)
    return JSONResponse({"status": "accepted"}, status_code=202)


async def _run_pipeline(
    import_id: str,
    source_format: str,
    import_ref: firestore.DocumentReference,
    started_at: datetime,
) -> None:
    """Run the full extraction pipeline. Called as a FastAPI background task."""
    blobs: list = []
    try:
        # --- Step 1: Download from GCS ---
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
            return

        file_bytes = blobs[0].download_as_bytes()

        # --- Step 2: Parse ---
        if source_format == "whatsapp_txt":
            turns = parse_whatsapp(file_bytes.decode("utf-8"))
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
            return

        try:
            import_ref.update({"turns_parsed": len(turns)})
        except Exception:  # noqa: BLE001
            pass

        # --- Step 3: PII stripping ---
        for turn in turns:
            stripped, _ = strip_pii(turn["content"])
            turn["content"] = stripped

        # --- Step 4: Gemini extraction (concurrent windows) ---
        chunks = await extract_qa_pairs_async(turns, max_concurrent_windows=4)

        if not chunks:
            duration_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
            import_ref.update({"status": "no_pairs_found", "completed_at": datetime.now(timezone.utc)})
            core.audit.write_event(
                "kb_import_completed",
                actor="system",
                import_id=import_id,
                result="no_pairs_found",
                duration_ms=duration_ms,
            )
            return

        # --- Step 5: Stage chunks ---
        chunk_ids = await stage_chunks(chunks, import_id, client=None)

        # --- Step 6: Count duplicates and update Firestore ---
        db = _get_db()
        dup_count = len(
            db.collection("kb_chunks")
            .where("import_id", "==", import_id)
            .where("duplicate_flag", "in", ["exact", "near"])
            .get()
        )

        duration_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
        import_ref.update({
            "status": "completed",
            "completed_at": datetime.now(timezone.utc),
            "chunks_extracted": len(chunk_ids),
            "chunks_flagged_duplicate": dup_count,
        })

        # --- Step 7: Audit event + GCS cleanup ---
        core.audit.write_event(
            "kb_import_completed",
            actor="system",
            import_id=import_id,
            result="completed",
            chunks_extracted=len(chunk_ids),
            chunks_flagged_duplicate=dup_count,
            duration_ms=duration_ms,
        )

        try:
            for blob in blobs:
                blob.delete()
        except Exception:  # noqa: BLE001
            pass

    except Exception as exc:
        logger.error("KB pipeline failed for import %s:\n%s", import_id, traceback.format_exc())
        if _is_transient(exc):
            # Reset to processing so a workflow retry can reclaim it.
            try:
                import_ref.update({"status": "processing"})
            except Exception:  # noqa: BLE001
                pass
        else:
            import_ref.update({
                "status": "failed",
                "error_message": str(exc)[:500],
                "completed_at": datetime.now(timezone.utc),
            })
