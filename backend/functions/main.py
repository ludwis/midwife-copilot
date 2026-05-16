"""Firebase Cloud Function: extract_kb_import.

Triggered by creation of a ``kb_imports/{importId}`` Firestore document.
Runs the full KB extraction pipeline:
  parse → PII strip → Gemini extract → stage chunks → update Firestore → delete GCS file.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# sys.path: allow imports from the backend/ sibling directory so that
# bot.kb.* and core.* modules resolve correctly.
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# Load .env from the backend directory before sibling package module-level
# code reads os.environ.
# ---------------------------------------------------------------------------
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

import firebase_admin  # noqa: E402
from firebase_admin import firestore as admin_firestore  # noqa: E402
from firebase_functions import firestore_fn  # noqa: E402
from google.cloud import storage  # noqa: E402

import core.audit  # noqa: E402
from bot.kb.extractor import extract_qa_pairs  # noqa: E402
from bot.kb.parsers.messenger import parse_messenger  # noqa: E402
from bot.kb.parsers.whatsapp import parse_whatsapp  # noqa: E402
from bot.kb.pii_stripper import strip_pii  # noqa: E402
from bot.kb.staging import stage_chunks  # noqa: E402

# ---------------------------------------------------------------------------
# Firebase app singleton — must be called before any firebase_admin API use.
# ---------------------------------------------------------------------------
firebase_admin.initialize_app()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _delete_gcs_file(gcs_uri: str) -> None:
    """Delete *gcs_uri* from GCS. Swallows all exceptions — never raises."""
    try:
        without_scheme = gcs_uri[len("gs://"):]
        bucket_name, _, blob_path = without_scheme.partition("/")
        storage.Client().bucket(bucket_name).blob(blob_path).delete()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to delete GCS file %s: %s", gcs_uri, exc)


# ---------------------------------------------------------------------------
# Firebase Cloud Function
# ---------------------------------------------------------------------------


@firestore_fn.on_document_created(
    document="kb_imports/{importId}",
    region="europe-west1",
    memory=512,
    timeout_sec=3600,
)
def extract_kb_import(event: firestore_fn.Event) -> None:
    """Process a newly created kb_imports document through the full extraction pipeline."""
    import_id: str = event.params["importId"]
    db = admin_firestore.client()
    doc_ref = db.collection("kb_imports").document(import_id)

    gcs_path: str | None = None
    try:
        doc = doc_ref.get()

        # Idempotency guard: skip if the doc was already processed or doesn't exist.
        if not doc.exists or doc.get("status") != "processing":
            logger.info(
                "Skipping import %s: doc exists=%s, status=%s",
                import_id,
                doc.exists,
                doc.get("status") if doc.exists else "n/a",
            )
            return

        data = doc.to_dict() or {}
        gcs_path = data["gcs_path"]
        source_format: str = data["source_format"]

        # --- Download file bytes from GCS ---
        without_scheme = gcs_path[len("gs://"):]
        bucket_name, _, blob_path = without_scheme.partition("/")
        gcs_client = storage.Client()
        file_bytes: bytes = gcs_client.bucket(bucket_name).blob(blob_path).download_as_bytes()

        # --- Parse ---
        if source_format == "whatsapp_txt":
            turns = parse_whatsapp(file_bytes.decode("utf-8"))
        elif source_format == "messenger_json":
            with tempfile.NamedTemporaryFile(mode="wb", suffix=".json", delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name
            try:
                turns = parse_messenger([tmp_path])
            finally:
                os.unlink(tmp_path)
        else:
            raise ValueError(f"Unsupported source_format: {source_format!r}")

        # --- PII-strip each turn ---
        stripped_turns = []
        for turn in turns:
            stripped_content, _ = strip_pii(turn["content"])
            stripped_turns.append({**turn, "content": stripped_content})

        # --- Extract Q&A pairs ---
        chunks = extract_qa_pairs(stripped_turns)

        now = datetime.now(timezone.utc)

        if not chunks:
            doc_ref.update({"status": "no_pairs_found", "completed_at": now})
            core.audit.write_event(
                "kb_import_completed",
                actor="system",
                import_id=import_id,
                status="no_pairs_found",
            )
            _delete_gcs_file(gcs_path)
            return

        # --- Stage chunks (async; run synchronously in Firebase Function thread) ---
        chunk_ids: list[str] = asyncio.run(stage_chunks(chunks, import_id, client=None))

        # --- Count duplicate chunks from Firestore ---
        chunks_flagged_duplicate = 0
        for cid in chunk_ids:
            cd = db.collection("kb_chunks").document(cid).get()
            if cd.exists and cd.get("duplicate_flag"):
                chunks_flagged_duplicate += 1

        # --- Update Firestore ---
        now = datetime.now(timezone.utc)
        doc_ref.update(
            {
                "status": "completed",
                "completed_at": now,
                "chunks_extracted": len(chunk_ids),
                "chunks_flagged_duplicate": chunks_flagged_duplicate,
            }
        )

        # --- Emit audit event ---
        core.audit.write_event(
            "kb_import_completed",
            actor="system",
            import_id=import_id,
            status="completed",
            chunks_extracted=len(chunk_ids),
            chunks_flagged_duplicate=chunks_flagged_duplicate,
        )

        # --- Delete GCS file (best-effort) ---
        _delete_gcs_file(gcs_path)

    except Exception as exc:
        logger.exception("Fatal error processing import %s", import_id)
        now = datetime.now(timezone.utc)
        try:
            doc_ref.update(
                {"status": "failed", "error_message": str(exc), "completed_at": now}
            )
        except Exception:  # noqa: BLE001
            logger.warning("Could not update Firestore status to failed for import %s", import_id)
        try:
            core.audit.write_event(
                "kb_import_completed",
                actor="system",
                import_id=import_id,
                status="failed",
                error_message=str(exc),
            )
        except Exception:  # noqa: BLE001
            logger.warning("Could not emit audit event for failed import %s", import_id)
        if gcs_path:
            _delete_gcs_file(gcs_path)
        raise
