"""GET /PATCH /api/admin/kb/chunks — List, retrieve, and review knowledge chunks.

Implements listChunks, getChunk, and reviewChunk from kb-review.yaml.
Auth: inherited from /api/admin router (X-Admin-Token via main.py).

Env vars:
  GOOGLE_CLOUD_PROJECT  — GCP project ID (read by Firestore client)
"""
from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timezone
from typing import Any, Optional

import core.audit
import bot.kb.promotion as _promotion
from fastapi import APIRouter, HTTPException
from google.cloud import firestore
from pydantic import BaseModel

router = APIRouter()

_VALID_STATUSES = {"staged", "approved", "promoted", "discarded"}
_VALID_DUP_FLAGS = {"exact", "near"}
_VALID_ACTIONS = {"approve", "edit_approve", "discard"}


class ReviewActionBody(BaseModel):
    action: str
    question: Optional[str] = None
    answer: Optional[str] = None


class _ChunkConflict(Exception):
    """Raised inside a Firestore transaction when the chunk is no longer staged."""


@firestore.transactional
def _commit_review(
    transaction: firestore.Transaction,
    chunk_ref: firestore.DocumentReference,
    updates: dict[str, Any],
) -> None:
    """Read chunk in transaction, assert staged, apply updates.

    Raises _ChunkConflict if the chunk is no longer in staged status —
    guards against concurrent review races.
    """
    snap = chunk_ref.get(transaction=transaction)
    if snap.exists and snap.to_dict().get("status") != "staged":
        raise _ChunkConflict(snap.to_dict().get("status"))
    transaction.update(chunk_ref, updates)

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
        "language": data.get("language", "unknown"),
        "status": data.get("status", ""),
        "source_type": data.get("source_type", "export"),
        "import_id": data.get("import_id"),
        "staged_at": _ts_to_str(data.get("staged_at")),
        "duplicate_flag": data.get("duplicate_flag"),
        "similarity_score": data.get("similarity_score"),
        "duplicate_of": None,
    }


def _doc_to_detail(doc_id: str, data: dict[str, Any]) -> dict[str, Any]:
    detail = _doc_to_summary(doc_id, data)
    detail.update(
        {
            "content_hash": data.get("content_hash"),
            "content_hash_before_edit": data.get("content_hash_before_edit"),
            "reviewed_at": _ts_to_str(data.get("reviewed_at")),
            "reviewed_by": data.get("reviewed_by"),
            "production_vertex_id": data.get("production_vertex_id"),
            "promoted_at": _ts_to_str(data.get("promoted_at")),
        }
    )
    return detail


def _encode_cursor(chunk_id: str) -> str:
    return base64.urlsafe_b64encode(chunk_id.encode()).decode()


def _decode_cursor(cursor: str) -> str:
    return base64.urlsafe_b64decode(cursor.encode()).decode()


@router.get("/chunks")
async def list_chunks(
    status: str | None = None,
    import_id: str | None = None,
    duplicate_flag: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Return knowledge chunks, newest-first, with optional filters and cursor pagination."""
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
        query = query.where(filter=firestore.FieldFilter("status", "==", status))
    if import_id is not None:
        query = query.where(filter=firestore.FieldFilter("import_id", "==", import_id))
    if duplicate_flag is not None:
        query = query.where(filter=firestore.FieldFilter("duplicate_flag", "==", duplicate_flag))

    # Apply cursor pagination: decode cursor → fetch snapshot → start_after
    if cursor is not None:
        try:
            cursor_chunk_id = _decode_cursor(cursor)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid pagination cursor.")
        cursor_doc = db.collection("kb_chunks").document(cursor_chunk_id).get()
        if cursor_doc.exists:
            query = query.start_after(cursor_doc)

    docs = list(query.limit(limit + 1).stream())

    # Determine if there is a next page
    has_more = len(docs) > limit
    page_docs = docs[:limit]

    chunks = [_doc_to_summary(doc.id, doc.to_dict()) for doc in page_docs]

    # Embed duplicate_of summary for flagged chunks
    for i, doc in enumerate(page_docs):
        data = doc.to_dict()
        dup_id = data.get("duplicate_of_chunk_id")
        if data.get("duplicate_flag") and dup_id:
            dup_doc = db.collection("kb_chunks").document(dup_id).get()
            if dup_doc.exists:
                chunks[i]["duplicate_of"] = _doc_to_summary(dup_doc.id, dup_doc.to_dict())

    # Count total staged chunks for the review-queue badge
    total_staged_count = (
        db.collection("kb_chunks")
        .where(filter=firestore.FieldFilter("status", "==", "staged"))
        .count()
        .get()[0][0]
        .value
    )

    next_cursor = _encode_cursor(page_docs[-1].id) if has_more and page_docs else None

    return {
        "chunks": chunks,
        "next_cursor": next_cursor,
        "total_staged": total_staged_count,
    }


@router.get("/chunks/{chunk_id}")
async def get_chunk(chunk_id: str) -> dict[str, Any]:
    """Return full ChunkDetail for a single knowledge chunk."""
    db = _get_firestore()
    doc = db.collection("kb_chunks").document(chunk_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail=f"Chunk {chunk_id!r} not found.")

    data = doc.to_dict()
    detail = _doc_to_detail(doc.id, data)

    # Embed duplicate_of summary if flagged
    dup_id = data.get("duplicate_of_chunk_id")
    if data.get("duplicate_flag") and dup_id:
        dup_doc = db.collection("kb_chunks").document(dup_id).get()
        if dup_doc.exists:
            detail["duplicate_of"] = _doc_to_summary(dup_doc.id, dup_doc.to_dict())

    return detail


@router.patch("/chunks/{chunk_id}")
async def review_chunk(chunk_id: str, body: ReviewActionBody) -> dict[str, Any]:
    """Apply a review action (approve / edit_approve / discard) to a staged chunk.

    Raises:
        400 — invalid action, or edit_approve missing question/answer
        404 — chunk not found
        409 — chunk already actioned (concurrent review race)
    """
    if body.action not in _VALID_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action {body.action!r}. Must be one of {sorted(_VALID_ACTIONS)}.",
        )
    if body.action == "edit_approve" and (not body.question or not body.answer):
        raise HTTPException(
            status_code=400,
            detail="edit_approve requires both 'question' and 'answer' fields.",
        )

    db = _get_firestore()
    chunk_ref = db.collection("kb_chunks").document(chunk_id)

    doc = chunk_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail=f"Chunk {chunk_id!r} not found.")

    data = doc.to_dict()

    # Pre-check: fast 409 before any external calls when chunk is already actioned.
    if data.get("status") != "staged":
        raise HTTPException(
            status_code=409,
            detail=f"Chunk {chunk_id} was already actioned — concurrent review conflict",
        )

    now = datetime.now(timezone.utc)
    updates: dict[str, Any] = {"reviewed_at": now}

    if body.action == "discard":
        updates["status"] = "discarded"

        try:
            _commit_review(db.transaction(), chunk_ref, updates)
        except _ChunkConflict:
            raise HTTPException(
                status_code=409,
                detail=f"Chunk {chunk_id} was already actioned — concurrent review conflict",
            )

        core.audit.write_event("kb_chunk_discarded", actor="admin", chunk_id=chunk_id)

    elif body.action == "approve":
        question = data["question"]
        answer = data["answer"]
        content_hash = data["content_hash"]
        language = data.get("language", "unknown")

        vertex_id = await _promotion.promote_chunk(chunk_id, question, answer, content_hash, language)

        updates.update(
            {
                "status": "promoted",
                "production_vertex_id": vertex_id,
                "promoted_at": now,
            }
        )

        try:
            _commit_review(db.transaction(), chunk_ref, updates)
        except _ChunkConflict:
            raise HTTPException(
                status_code=409,
                detail=f"Chunk {chunk_id} was already actioned — concurrent review conflict",
            )

        core.audit.write_event(
            "kb_chunk_approved",
            actor="admin",
            chunk_id=chunk_id,
            content_hash=content_hash,
        )
        core.audit.write_event(
            "kb_chunk_promoted",
            actor="admin",
            chunk_id=chunk_id,
            content_hash=content_hash,
            production_vertex_id=vertex_id,
        )

    else:  # edit_approve
        new_question: str = body.question  # type: ignore[assignment]
        new_answer: str = body.answer  # type: ignore[assignment]
        original_hash = data["content_hash"]
        new_hash = hashlib.sha256((new_question + "\n" + new_answer).encode()).hexdigest()

        language = data.get("language", "unknown")
        vertex_id = await _promotion.promote_chunk(chunk_id, new_question, new_answer, new_hash, language)

        updates.update(
            {
                "status": "promoted",
                "question": new_question,
                "answer": new_answer,
                "content_hash": new_hash,
                "content_hash_before_edit": original_hash,
                "production_vertex_id": vertex_id,
                "promoted_at": now,
            }
        )

        try:
            _commit_review(db.transaction(), chunk_ref, updates)
        except _ChunkConflict:
            raise HTTPException(
                status_code=409,
                detail=f"Chunk {chunk_id} was already actioned — concurrent review conflict",
            )

        core.audit.write_event(
            "kb_chunk_edited",
            actor="admin",
            chunk_id=chunk_id,
            content_hash_before=original_hash,
            content_hash_after=new_hash,
        )
        core.audit.write_event(
            "kb_chunk_promoted",
            actor="admin",
            chunk_id=chunk_id,
            content_hash=new_hash,
            production_vertex_id=vertex_id,
        )

    updated_doc = chunk_ref.get()
    return _doc_to_detail(chunk_id, updated_doc.to_dict())
