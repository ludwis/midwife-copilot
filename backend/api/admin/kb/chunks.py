"""GET /api/admin/kb/chunks — List knowledge chunks, filterable by status.

Implements the listChunks operation from kb-review.yaml.
Auth: inherited from /api/admin router (X-Admin-Token via main.py).

Env vars:
  GOOGLE_CLOUD_PROJECT  — GCP project ID (read by Firestore client)
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from google.cloud import firestore

router = APIRouter()

_VALID_STATUSES = {"staged", "approved", "promoted", "discarded"}
_VALID_DUP_FLAGS = {"exact", "near"}

# Lazy Firestore singleton (same pattern as imports.py / staging.py)
_firestore_client: firestore.Client | None = None


def _get_firestore() -> firestore.Client:
    global _firestore_client
    if _firestore_client is None:
        _firestore_client = firestore.Client()
    return _firestore_client


def _ts_to_str(ts: Any) -> str | None:
    """Convert Firestore Timestamp / datetime to ISO-8601 string, or None."""
    if ts is None:
        return None
    from datetime import datetime, timezone

    if isinstance(ts, datetime):
        dt = ts
    else:
        try:
            dt = ts.astimezone(timezone.utc)
        except AttributeError:
            return str(ts)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _doc_to_summary(doc_id: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": doc_id,
        "question": data.get("question", ""),
        "answer": data.get("answer", ""),
        "status": data.get("status", ""),
        "source_type": data.get("source_type", "export"),
        "import_id": data.get("import_id"),
        "staged_at": _ts_to_str(data.get("staged_at")),
        "duplicate_flag": data.get("duplicate_flag"),
        "similarity_score": data.get("similarity_score"),
    }


@router.get("/chunks")
async def list_chunks(
    status: str | None = None,
    import_id: str | None = None,
    duplicate_flag: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Return knowledge chunks, newest-first, with optional filters."""
    if status is not None and status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status {status!r}. Must be one of {sorted(_VALID_STATUSES)}.",
        )
    if duplicate_flag is not None and duplicate_flag not in _VALID_DUP_FLAGS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid duplicate_flag {duplicate_flag!r}. Must be 'exact' or 'near'.",
        )
    limit = min(max(limit, 1), 200)

    db = _get_firestore()
    query: Any = db.collection("kb_chunks").order_by(
        "staged_at", direction=firestore.Query.DESCENDING
    )
    if status is not None:
        query = query.where("status", "==", status)
    if import_id is not None:
        query = query.where("import_id", "==", import_id)
    if duplicate_flag is not None:
        query = query.where("duplicate_flag", "==", duplicate_flag)

    docs = list(query.limit(limit).stream())
    chunks = [_doc_to_summary(doc.id, doc.to_dict()) for doc in docs]

    # Count total staged chunks for the review-queue badge
    total_staged_count = (
        db.collection("kb_chunks")
        .where("status", "==", "staged")
        .count()
        .get()[0][0]
        .value
    )

    return {
        "chunks": chunks,
        "next_cursor": None,
        "total_staged": total_staged_count,
    }
