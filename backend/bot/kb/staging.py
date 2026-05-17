"""Staging writer for KB chunks.

stage_chunks(chunks, import_id, client) -> list[str]:
  For each ChunkDraft:
    1. compute content_hash = SHA-256(question + "\\n" + answer)
    2. call deduplicator.check_duplicate()
    3. create kb_chunks Firestore doc (status=staged)
    4. emit kb_chunk_staged audit event immediately after Firestore write
    5. write to Vertex AI staging data store via Discovery Engine API (best-effort)
  Returns list of chunk_id strings.

The client parameter is google.cloud.discoveryengine_v1.DocumentServiceAsyncClient.
Pass None to skip Vertex AI writes (e.g. in tests).

IMPORTANT: audit events are emitted via ``import core.audit; core.audit.write_event(...)``
— NOT via ``from core.audit import write_event`` — so the integration-test mock patch
at ``core.audit.write_event`` intercepts correctly.

Env vars:
    GOOGLE_CLOUD_PROJECT         — GCP project ID
    STILLA_ENV                   — Environment suffix (dev/prod); defaults to 'dev'
    VERTEX_STAGING_DATA_STORE    — Discovery Engine data store ID; defaults to 'midwife-staging'
    VERTEX_LOCATION              — Discovery Engine location; defaults to 'eu'
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore

import core.audit
from bot.kb import deduplicator
from bot.kb.extractor import ChunkDraft

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level Firestore client (lazy singleton)
# ---------------------------------------------------------------------------

_firestore_client: firestore.Client | None = None


def _get_firestore() -> firestore.Client:
    global _firestore_client
    if _firestore_client is None:
        _firestore_client = firestore.Client()
    return _firestore_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WS_RE = re.compile(r"\s+")


def _content_hash(question: str, answer: str) -> str:
    """SHA-256 of question + newline + answer (per data-model.md §kb_chunks)."""
    return hashlib.sha256((question + "\n" + answer).encode()).hexdigest()


def _question_hash(question: str) -> str:
    """Normalised question hash matching deduplicator.py pass-1 logic.

    Used to populate existing_hashes for intra-batch duplicate detection.
    """
    normalised = _WS_RE.sub(" ", question.lower()).strip()
    return hashlib.sha256(normalised.encode()).hexdigest()


async def _write_vertex_staging(
    client: Any,
    chunk_id: str,
    draft: ChunkDraft,
    import_id: str,
    content_hash: str,
    staged_at: datetime,
) -> None:
    """Write a document to the Vertex AI staging data store.

    Schema per data-model.md §Vertex AI Search Documents.
    Raises on error — caller catches and logs.
    """
    from google.cloud import discoveryengine_v1 as discoveryengine  # type: ignore[import]
    from google.protobuf import struct_pb2

    project = os.environ.get("GCP_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    location = os.environ.get("VERTEX_SEARCH_LOCATION") or os.environ.get("VERTEX_LOCATION", "eu")
    data_store = os.environ.get("VERTEX_SEARCH_DATASTORE_STAGING") or os.environ.get("VERTEX_STAGING_DATA_STORE", "midwife-staging")

    parent = (
        f"projects/{project}/locations/{location}"
        f"/collections/default_collection"
        f"/dataStores/{data_store}/branches/default_branch"
    )

    text_content = f"Q: {draft.question}\nA: {draft.answer}"

    struct_data = struct_pb2.Struct()
    struct_data.update(
        {
            "question": draft.question,
            "answer": draft.answer,
            "language": draft.language,
            "source_type": "export",
            "import_id": import_id,
            "content_hash": content_hash,
            "staged_at": staged_at.strftime("%Y-%m-%d"),
        }
    )

    request = discoveryengine.CreateDocumentRequest(
        parent=parent,
        document=discoveryengine.Document(
            id=chunk_id,
            content=discoveryengine.Document.Content(
                mime_type="text/plain",
                raw_bytes=text_content.encode("utf-8"),
            ),
            struct_data=struct_data,
        ),
        document_id=chunk_id,
    )

    await client.create_document(request)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def stage_chunks(
    chunks: list[ChunkDraft],
    import_id: str,
    client: Any,  # DocumentServiceAsyncClient | None
    *,
    batch_size: int = 50,
) -> list[str]:
    """Stage extracted Q&A pairs into Firestore and Vertex AI Search.

    Parameters
    ----------
    chunks:
        Extracted Q&A pairs (after PII stripping) to be staged.
    import_id:
        Firestore document ID of the parent kb_imports record.
    client:
        google.cloud.discoveryengine_v1.DocumentServiceAsyncClient for writing
        to the Vertex AI staging data store.  Pass None to skip Vertex AI writes
        (e.g. in unit/integration tests where Discovery Engine is unavailable).

    Returns
    -------
    list[str]
        Firestore document IDs (chunk_id values) for all staged chunks.
    """
    db = _get_firestore()
    chunk_ids: list[str] = []

    # Build existing_hashes incrementally so intra-batch duplicates are caught.
    # Maps question_hash → chunk_id (same contract as deduplicator.check_duplicate).
    existing_hashes: dict[str, str] = {}

    batch = db.batch()
    batch_count = 0

    for draft in chunks:
        c_hash = _content_hash(draft.question, draft.answer)

        # Allocate Firestore document ID before the dedup check so that the
        # chunk's own ID is available for self-comparison exclusion.
        doc_ref = db.collection("kb_chunks").document()
        chunk_id = doc_ref.id

        # Deduplication (pass 1: exact hash; pass 2: near via cosine similarity).
        dedup = deduplicator.check_duplicate(
            question=draft.question,
            chunk_id=chunk_id,
            existing_hashes=existing_hashes,
        )

        now = datetime.now(timezone.utc)

        # Stage kb_chunks Firestore document into the current WriteBatch.
        doc_data: dict[str, Any] = {
            "question": draft.question,
            "answer": draft.answer,
            "language": draft.language,
            "content_hash": c_hash,
            "source_type": "export",
            "import_id": import_id,
            "status": "staged",
            "staged_at": now,
            "duplicate_flag": dedup.flag,
            "duplicate_of_chunk_id": dedup.duplicate_of_chunk_id,
            "similarity_score": dedup.similarity_score,
        }
        batch.set(doc_ref, doc_data)
        batch_count += 1

        # Emit audit event per chunk, outside the batch (not transactional with
        # the Firestore write — see module docstring).
        # NOTE: must call core.audit.write_event — not a locally-bound import — so
        # the integration-test patch on ``core.audit.write_event`` intercepts correctly.
        core.audit.write_event(
            "kb_chunk_staged",
            actor="midwife",
            import_id=import_id,
            chunk_id=chunk_id,
            content_hash=c_hash,
            duplicate_flag=dedup.flag,
        )

        if batch_count >= batch_size:
            batch.commit()
            batch = db.batch()
            batch_count = 0

        # Write to Vertex AI staging data store (best-effort; non-fatal on failure).
        if client is not None:
            try:
                await _write_vertex_staging(
                    client, chunk_id, draft, import_id, c_hash, now
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Vertex AI staging write failed for chunk %s: %s", chunk_id, exc
                )

        # Register question hash for subsequent intra-batch dedup checks.
        existing_hashes[_question_hash(draft.question)] = chunk_id
        chunk_ids.append(chunk_id)

    if batch_count > 0:
        batch.commit()

    return chunk_ids
