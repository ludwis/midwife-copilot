"""Chunk promotion writer: staging → production Vertex AI Search data store.

promote_chunk(chunk_id, question, answer, content_hash) -> str:
  1. Write document to Vertex AI production data store via Discovery Engine API.
     Document schema per data-model.md §Vertex AI Search Documents.
  2. Append {chunk_id, embedding} entry to GCS embedding cache (best-effort;
     non-fatal on failure).
  Returns the production_vertex_id (equals chunk_id in Vertex AI Search).

NOTE: Firestore state transition (status=promoted, production_vertex_id,
promoted_at) is the responsibility of the PATCH handler (api/admin/kb/chunks.py)
which calls this function and wraps the Firestore update in a transaction.

Env vars:
    GOOGLE_CLOUD_PROJECT          — GCP project ID
    STILLA_ENV                    — Environment suffix (dev/prod); defaults to 'dev'
    VERTEX_PRODUCTION_DATA_STORE  — Discovery Engine data store ID;
                                    defaults to 'midwife-production'
    VERTEX_LOCATION               — Discovery Engine location; defaults to 'eu'
    EMBEDDING_BUCKET_NAME         — GCS bucket for embedding cache;
                                    if absent, falls back to midwife-bot-audit-{STILLA_ENV}
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _write_vertex_production(
    chunk_id: str,
    question: str,
    answer: str,
    content_hash: str,
    promoted_at: datetime,
) -> None:
    """Write a document to the Vertex AI production data store.

    Schema per data-model.md §Vertex AI Search Documents.
    Raises on failure — caller must not catch (production write is non-optional).
    """
    from google.cloud import discoveryengine_v1 as discoveryengine  # type: ignore[import]
    from google.protobuf import struct_pb2  # type: ignore[import]

    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    location = os.environ.get("VERTEX_LOCATION", "eu")
    data_store = os.environ.get("VERTEX_PRODUCTION_DATA_STORE", "midwife-production")

    parent = (
        f"projects/{project}/locations/{location}"
        f"/collections/default_collection"
        f"/dataStores/{data_store}/branches/default_branch"
    )

    text_content = f"Q: {question}\nA: {answer}"

    struct_data = struct_pb2.Struct()
    struct_data.update(
        {
            "question": question,
            "answer": answer,
            "source_type": "export",
            "content_hash": content_hash,
            "promoted_at": promoted_at.strftime("%Y-%m-%d"),
        }
    )

    client = discoveryengine.DocumentServiceAsyncClient()
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


def _append_embedding_cache(chunk_id: str, text: str) -> None:
    """Append embedding entry to GCS embedding cache (best-effort; non-fatal)."""
    try:
        from google.cloud import storage  # type: ignore[import]
        from vertexai.language_models import TextEmbeddingModel  # type: ignore[import]

        model = TextEmbeddingModel.from_pretrained("textembedding-gecko-multilingual@001")
        embeddings = model.get_embeddings([text])
        embedding = embeddings[0].values

        env = os.environ.get("STILLA_ENV", "dev")
        bucket_name = os.environ.get(
            "EMBEDDING_BUCKET_NAME", f"midwife-bot-audit-{env}"
        )
        blob_path = "embeddings/cache.jsonl"
        line = json.dumps({"chunk_id": chunk_id, "embedding": embedding}, ensure_ascii=False)

        gcs = storage.Client()
        bucket = gcs.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        existing = blob.download_as_text(encoding="utf-8") if blob.exists() else ""
        blob.upload_from_string(
            existing + line + "\n",
            content_type="application/x-ndjson",
        )
        logger.info(
            "Appended embedding for chunk %s to gs://%s/%s",
            chunk_id,
            bucket_name,
            blob_path,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "GCS embedding cache update failed for chunk %s: %s", chunk_id, exc
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def promote_chunk(
    chunk_id: str,
    question: str,
    answer: str,
    content_hash: str,
) -> str:
    """Promote a knowledge chunk to the production Vertex AI Search data store.

    Parameters
    ----------
    chunk_id:
        Firestore document ID of the chunk (becomes the Vertex AI document ID).
    question:
        Chunk question text (PII-stripped; final version after any edits).
    answer:
        Chunk answer text (PII-stripped; final version after any edits).
    content_hash:
        SHA-256 of ``question + "\\n" + answer``; stored in Vertex AI
        structData for document provenance.

    Returns
    -------
    str
        The production Vertex AI document ID (equals chunk_id).

    Raises
    ------
    Exception
        If writing to the Vertex AI production data store fails.
        GCS embedding cache failure is non-fatal (logged as warning only).
    """
    promoted_at = datetime.now(timezone.utc)

    await _write_vertex_production(chunk_id, question, answer, content_hash, promoted_at)

    # GCS embedding cache update — best-effort; never raises
    text = f"Q: {question}\nA: {answer}"
    _append_embedding_cache(chunk_id, text)

    return chunk_id
