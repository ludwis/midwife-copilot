"""Integration tests for chunk review actions (T037).

TDD: Written before implementation (T039–T042). Tests will be RED until
PATCH /api/admin/kb/chunks/{chunk_id} and bot/kb/promotion.py are implemented.

Contract encoded by this test suite:
  1. PATCH approve   → status=promoted, production_vertex_id set, reviewed_at set
  2. PATCH edit_approve → content_hash updated, content_hash_before_edit preserved, status=promoted
  3. PATCH discard   → status=discarded, reviewed_at set
  4. PATCH on already-actioned chunk → 409 Conflict

Requirements to run:
  FIRESTORE_EMULATOR_HOST=localhost:8080  (Firestore emulator must be running)
  bot.kb.promotion.promote_chunk is mocked — no Vertex AI calls are made.

NOTE: `bot.kb.promotion.promote_chunk` must be called via the module path so
that patching `bot.kb.promotion.promote_chunk` at source works correctly.
"""
from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from google.cloud import firestore

from api.main import app

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ADMIN_TOKEN = "integration-test-token"
_PROJECT_ID = "test-project"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def firestore_client():
    """Firestore client directed at the local emulator."""
    host = os.environ.get("FIRESTORE_EMULATOR_HOST", "localhost:8080")
    os.environ["FIRESTORE_EMULATOR_HOST"] = host
    client = firestore.Client(project=_PROJECT_ID)
    yield client


@pytest.fixture()
def captured_audit_events() -> list[dict[str, Any]]:
    """Capture calls to core.audit.write_event without GCS/Cloud Logging."""
    events: list[dict[str, Any]] = []

    def _capture(event_type: str, **kwargs: Any) -> None:
        events.append({"event_type": event_type, **kwargs})

    with patch("core.audit.write_event", side_effect=_capture):
        yield events


@pytest.fixture()
def admin_client(monkeypatch, captured_audit_events):  # noqa: ARG001
    """FastAPI TestClient with admin token and emulator env vars."""
    monkeypatch.setenv("ADMIN_TOKEN", _ADMIN_TOKEN)
    monkeypatch.setenv(
        "FIRESTORE_EMULATOR_HOST",
        os.environ.get("FIRESTORE_EMULATOR_HOST", "localhost:8080"),
    )
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", _PROJECT_ID)
    monkeypatch.setenv("SPACY_MODEL", "xx_ent_wiki_sm")
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client


def _content_hash(question: str, answer: str) -> str:
    return hashlib.sha256((question + "\n" + answer).encode()).hexdigest()


def _seed_staged_chunk(
    db: firestore.Client,
    question: str,
    answer: str,
) -> str:
    """Write a staged kb_chunks doc and return its chunk_id."""
    doc_ref = db.collection("kb_chunks").document()
    doc_ref.set(
        {
            "question": question,
            "answer": answer,
            "content_hash": _content_hash(question, answer),
            "source_type": "export",
            "import_id": "test-import-001",
            "status": "staged",
            "staged_at": datetime.now(timezone.utc),
            "duplicate_flag": None,
            "similarity_score": None,
        }
    )
    return doc_ref.id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_approve_transitions_chunk_to_promoted(
    admin_client: TestClient,
    firestore_client: firestore.Client,
    captured_audit_events: list[dict[str, Any]],
):
    """PATCH approve → status=promoted, production_vertex_id set, reviewed_at set.

    Why: The promote action must atomically transition Firestore state and
    record audit provenance. The production_vertex_id confirms promotion to
    Vertex AI; reviewed_at enables compliance reporting.
    """
    chunk_id = _seed_staged_chunk(
        firestore_client,
        question="What is normal pelvic pressure at 36 weeks?",
        answer="Pelvic pressure is common in the third trimester as the baby descends.",
    )

    fake_vertex_id = f"vertex-prod-{chunk_id}"

    async def _fake_promote(
        chunk_id: str, question: str, answer: str, content_hash: str
    ) -> str:
        return fake_vertex_id

    with patch(
        "bot.kb.promotion.promote_chunk",
        side_effect=_fake_promote,
    ):
        resp = admin_client.patch(
            f"/api/admin/kb/chunks/{chunk_id}",
            headers={"X-Admin-Token": _ADMIN_TOKEN},
            json={"action": "approve"},
        )

    assert resp.status_code == 200, (
        f"Expected 200, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert body["chunk_id"] == chunk_id
    assert body["status"] == "promoted"
    assert body["production_vertex_id"] == fake_vertex_id
    assert body["reviewed_at"] is not None

    # Verify Firestore state
    doc = firestore_client.collection("kb_chunks").document(chunk_id).get()
    assert doc.exists
    data = doc.to_dict()
    assert data["status"] == "promoted"
    assert data["production_vertex_id"] == fake_vertex_id
    assert data["reviewed_at"] is not None
    assert data["promoted_at"] is not None

    # Audit event must be emitted
    review_events = [
        e for e in captured_audit_events if e["event_type"] == "kb_chunk_approved"
    ]
    assert len(review_events) == 1
    assert review_events[0]["chunk_id"] == chunk_id


@pytest.mark.integration
def test_edit_approve_updates_content_and_preserves_original_hash(
    admin_client: TestClient,
    firestore_client: firestore.Client,
    captured_audit_events: list[dict[str, Any]],
):
    """PATCH edit_approve → content_hash updated, content_hash_before_edit preserved, status=promoted.

    Why: The original content_hash must be preserved for audit provenance
    (7-year immutable audit trail requirement). The new content_hash must
    reflect the edited question/answer for deduplication integrity.
    """
    original_question = "Is swelling in late pregnancy dangerous?"
    original_answer = "Some swelling is normal but sudden swelling needs urgent review."
    original_hash = _content_hash(original_question, original_answer)

    chunk_id = _seed_staged_chunk(
        firestore_client,
        question=original_question,
        answer=original_answer,
    )

    edited_question = "Is leg swelling in late pregnancy dangerous?"
    edited_answer = "Mild leg swelling is normal; sudden face/hand swelling needs urgent review."
    expected_new_hash = _content_hash(edited_question, edited_answer)

    async def _fake_promote(
        chunk_id: str, question: str, answer: str, content_hash: str
    ) -> str:
        return f"vertex-prod-{chunk_id}"

    with patch(
        "bot.kb.promotion.promote_chunk",
        side_effect=_fake_promote,
    ):
        resp = admin_client.patch(
            f"/api/admin/kb/chunks/{chunk_id}",
            headers={"X-Admin-Token": _ADMIN_TOKEN},
            json={
                "action": "edit_approve",
                "question": edited_question,
                "answer": edited_answer,
            },
        )

    assert resp.status_code == 200, (
        f"Expected 200, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert body["status"] == "promoted"
    assert body["content_hash"] == expected_new_hash, (
        "content_hash must reflect the edited Q&A"
    )
    assert body["content_hash_before_edit"] == original_hash, (
        "content_hash_before_edit must preserve the pre-edit hash for audit"
    )

    # Firestore must match
    doc = firestore_client.collection("kb_chunks").document(chunk_id).get()
    data = doc.to_dict()
    assert data["status"] == "promoted"
    assert data["question"] == edited_question
    assert data["answer"] == edited_answer
    assert data["content_hash"] == expected_new_hash
    assert data["content_hash_before_edit"] == original_hash

    # Audit event
    edit_events = [
        e for e in captured_audit_events if e["event_type"] == "kb_chunk_edited"
    ]
    assert len(edit_events) == 1
    assert edit_events[0]["chunk_id"] == chunk_id
    assert edit_events[0]["content_hash_before"] == original_hash
    assert edit_events[0]["content_hash_after"] == expected_new_hash


@pytest.mark.integration
def test_edit_approve_returns_400_when_question_or_answer_missing(
    admin_client: TestClient,
    firestore_client: firestore.Client,
    captured_audit_events: list[dict[str, Any]],  # noqa: ARG001
):
    """PATCH edit_approve without question/answer → 400 Bad Request.

    Why: edit_approve requires both fields to compute a valid content_hash.
    Missing either field must be rejected before any Firestore write.
    """
    chunk_id = _seed_staged_chunk(
        firestore_client,
        question="What vitamins should I take?",
        answer="Folic acid and vitamin D are recommended.",
    )

    resp = admin_client.patch(
        f"/api/admin/kb/chunks/{chunk_id}",
        headers={"X-Admin-Token": _ADMIN_TOKEN},
        json={"action": "edit_approve", "question": "Updated question only"},
        # answer intentionally omitted
    )
    assert resp.status_code == 400, (
        f"Expected 400 for edit_approve missing answer, got {resp.status_code}: {resp.text}"
    )


@pytest.mark.integration
def test_discard_transitions_chunk_to_discarded(
    admin_client: TestClient,
    firestore_client: firestore.Client,
    captured_audit_events: list[dict[str, Any]],
):
    """PATCH discard → status=discarded, reviewed_at set.

    Why: Discard is a terminal state — the chunk must never appear in the
    review queue again. reviewed_at enables compliance audit of who discarded
    what and when.
    """
    chunk_id = _seed_staged_chunk(
        firestore_client,
        question="How often should I exercise when pregnant?",
        answer="Light exercise is generally safe; consult your midwife.",
    )

    resp = admin_client.patch(
        f"/api/admin/kb/chunks/{chunk_id}",
        headers={"X-Admin-Token": _ADMIN_TOKEN},
        json={"action": "discard"},
    )

    assert resp.status_code == 200, (
        f"Expected 200, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert body["status"] == "discarded"
    assert body["reviewed_at"] is not None

    # Firestore state
    doc = firestore_client.collection("kb_chunks").document(chunk_id).get()
    data = doc.to_dict()
    assert data["status"] == "discarded"
    assert data["reviewed_at"] is not None

    # Audit event
    discard_events = [
        e for e in captured_audit_events if e["event_type"] == "kb_chunk_discarded"
    ]
    assert len(discard_events) == 1
    assert discard_events[0]["chunk_id"] == chunk_id


@pytest.mark.integration
def test_second_patch_to_actioned_chunk_returns_409(
    admin_client: TestClient,
    firestore_client: firestore.Client,
    captured_audit_events: list[dict[str, Any]],  # noqa: ARG001
):
    """Second PATCH to already-actioned chunk → 409 Conflict.

    Why: Concurrent review races must be prevented. A midwife starting to
    review a chunk that another session already actioned must receive a clear
    conflict error — not a silent double-transition that corrupts audit state.
    """
    chunk_id = _seed_staged_chunk(
        firestore_client,
        question="Can I travel by plane in my second trimester?",
        answer="Air travel is generally safe in the second trimester for uncomplicated pregnancies.",
    )

    # First PATCH — discard it
    async def _fake_promote(
        chunk_id: str, question: str, answer: str, content_hash: str
    ) -> str:
        return f"vertex-prod-{chunk_id}"

    with patch(
        "bot.kb.promotion.promote_chunk",
        side_effect=_fake_promote,
    ):
        first = admin_client.patch(
            f"/api/admin/kb/chunks/{chunk_id}",
            headers={"X-Admin-Token": _ADMIN_TOKEN},
            json={"action": "discard"},
        )
    assert first.status_code == 200, (
        f"First PATCH failed unexpectedly: {first.status_code}: {first.text}"
    )

    # Second PATCH — must be rejected with 409
    with patch(
        "bot.kb.promotion.promote_chunk",
        side_effect=_fake_promote,
    ):
        second = admin_client.patch(
            f"/api/admin/kb/chunks/{chunk_id}",
            headers={"X-Admin-Token": _ADMIN_TOKEN},
            json={"action": "approve"},
        )
    assert second.status_code == 409, (
        f"Expected 409 for second PATCH on actioned chunk, got {second.status_code}: {second.text}"
    )


@pytest.mark.integration
def test_seed_5_review_mix_promoted_count_is_3(
    admin_client: TestClient,
    firestore_client: firestore.Client,
    captured_audit_events: list[dict[str, Any]],  # noqa: ARG001
):
    """Seed 5 staged chunks, perform approve×2 + edit_approve×1 + discard×1,
    verify GET /api/admin/kb/chunks?status=promoted filtered by import_id returns 3.

    Why: End-to-end acceptance criterion for Phase 04 US2. Confirms the full
    review pipeline transitions state correctly — 2 approved + 1 edit-approved
    = 3 promoted, 1 discarded, 1 remaining staged. The import_id filter scopes
    the assertion to chunks seeded by this test, making it safe to run against
    a shared emulator with residual state.
    """
    _IMPORT_ID = f"verification-seed-{uuid.uuid4().hex[:8]}"

    async def _fake_promote(
        chunk_id: str, question: str, answer: str, content_hash: str
    ) -> str:
        return f"vertex-prod-{chunk_id}"

    # ---- Seed 5 staged chunks with a unique import_id ----
    chunks_data = [
        ("What is a Braxton Hicks contraction?", "Braxton Hicks are irregular practice contractions."),
        ("When should I call my midwife about contractions?", "Call if contractions are 5 mins apart for 1 hour."),
        ("Can I eat sushi during pregnancy?", "Avoid raw fish; cooked sushi is generally safe."),
        ("How much weight should I gain in pregnancy?", "Recommended gain varies by pre-pregnancy BMI."),
        ("Is heartburn normal in third trimester?", "Yes, heartburn is common as the uterus grows."),
    ]
    chunk_ids: list[str] = []
    for question, answer in chunks_data:
        doc_ref = firestore_client.collection("kb_chunks").document()
        doc_ref.set(
            {
                "question": question,
                "answer": answer,
                "content_hash": _content_hash(question, answer),
                "source_type": "export",
                "import_id": _IMPORT_ID,
                "status": "staged",
                "staged_at": datetime.now(timezone.utc),
                "duplicate_flag": None,
                "similarity_score": None,
            }
        )
        chunk_ids.append(doc_ref.id)

    assert len(chunk_ids) == 5

    # ---- Approve chunk[0] ----
    with patch("bot.kb.promotion.promote_chunk", side_effect=_fake_promote):
        r = admin_client.patch(
            f"/api/admin/kb/chunks/{chunk_ids[0]}",
            headers={"X-Admin-Token": _ADMIN_TOKEN},
            json={"action": "approve"},
        )
    assert r.status_code == 200, f"approve[0] failed: {r.status_code} {r.text}"
    assert r.json()["status"] == "promoted"

    # ---- Approve chunk[1] ----
    with patch("bot.kb.promotion.promote_chunk", side_effect=_fake_promote):
        r = admin_client.patch(
            f"/api/admin/kb/chunks/{chunk_ids[1]}",
            headers={"X-Admin-Token": _ADMIN_TOKEN},
            json={"action": "approve"},
        )
    assert r.status_code == 200, f"approve[1] failed: {r.status_code} {r.text}"
    assert r.json()["status"] == "promoted"

    # ---- Edit-approve chunk[2] ----
    edited_q = "Can I eat cooked sushi during pregnancy?"
    edited_a = "Cooked sushi is generally safe; avoid raw fish and high-mercury species."
    with patch("bot.kb.promotion.promote_chunk", side_effect=_fake_promote):
        r = admin_client.patch(
            f"/api/admin/kb/chunks/{chunk_ids[2]}",
            headers={"X-Admin-Token": _ADMIN_TOKEN},
            json={"action": "edit_approve", "question": edited_q, "answer": edited_a},
        )
    assert r.status_code == 200, f"edit_approve[2] failed: {r.status_code} {r.text}"
    body = r.json()
    assert body["status"] == "promoted"
    assert body["content_hash"] == _content_hash(edited_q, edited_a)
    assert body["content_hash_before_edit"] == _content_hash(
        chunks_data[2][0], chunks_data[2][1]
    )

    # ---- Discard chunk[3] ----
    r = admin_client.patch(
        f"/api/admin/kb/chunks/{chunk_ids[3]}",
        headers={"X-Admin-Token": _ADMIN_TOKEN},
        json={"action": "discard"},
    )
    assert r.status_code == 200, f"discard[3] failed: {r.status_code} {r.text}"
    assert r.json()["status"] == "discarded"

    # chunk[4] remains staged — no PATCH issued

    # ---- Verify GET /chunks?status=promoted&import_id returns 3 ----
    r = admin_client.get(
        "/api/admin/kb/chunks",
        headers={"X-Admin-Token": _ADMIN_TOKEN},
        params={"status": "promoted", "import_id": _IMPORT_ID},
    )
    assert r.status_code == 200, f"list promoted failed: {r.status_code} {r.text}"
    resp = r.json()
    promoted = resp["chunks"]
    assert len(promoted) == 3, (
        f"Expected 3 promoted chunks, got {len(promoted)}: {promoted}"
    )
    promoted_ids = {c["chunk_id"] for c in promoted}
    assert chunk_ids[0] in promoted_ids
    assert chunk_ids[1] in promoted_ids
    assert chunk_ids[2] in promoted_ids

    # ---- Verify chunk[3] is discarded in Firestore ----
    doc3 = firestore_client.collection("kb_chunks").document(chunk_ids[3]).get()
    assert doc3.to_dict()["status"] == "discarded"

    # ---- Verify chunk[4] is still staged ----
    doc4 = firestore_client.collection("kb_chunks").document(chunk_ids[4]).get()
    assert doc4.to_dict()["status"] == "staged"
