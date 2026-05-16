"""Integration test for the KB import flow (T025).

TDD: Written before implementation (T026–T033). Tests will be RED until
the full pipeline is implemented.

Contract encoded by this test:
  1. POST /api/admin/kb/imports returns 202 with import_id and status=processing
  2. Background pipeline: parse → PII strip → Gemini extract → dedup + stage
  3. GET /api/admin/kb/imports/{import_id} eventually returns status=completed
  4. kb_imports Firestore doc contains all required fields
  5. kb_chunks docs: status=staged, no PII in question/answer
  6. kb_chunk_staged audit events contain event_type, chunk_id, import_id, content_hash

Requirements to run:
  FIRESTORE_EMULATOR_HOST=localhost:8080  (Firestore emulator must be running)
  VCR cassette in cassettes/test_import_flow/
    test_post_upload_and_poll_until_completed.yaml
  (replays Gemini generateContent HTTPS response; record_mode=none)

NOTE on import patching — the staged event assertions patch core.audit.write_event
at the source module level. The staging implementation (T031) must call audit via
  ``import core.audit; core.audit.write_event(...)``
NOT via ``from core.audit import write_event`` — the latter creates a local binding
that bypasses the patch.
"""
from __future__ import annotations

import os
import re
import time
from io import BytesIO
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from google.cloud import firestore

from api.main import app

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ADMIN_TOKEN = "integration-test-token"
_PROJECT_ID = "test-project"

# PII patterns that must NOT appear in any staged chunk's question or answer.
_PII_PATTERNS = [
    re.compile(r"\+?\d[\d\s\-]{7,}\d"),  # phone numbers (≥8-digit sequences)
    re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"),  # email
    re.compile(r"\b\d{11}\b"),  # PESEL (11 consecutive digits)
    re.compile(r"\b\d{10}\b"),  # NIP  (10 consecutive digits)
]

# WhatsApp export fixture that includes deliberate PII (name, phone, email).
# After extraction + PII stripping, none of these identifiers should appear
# in staged chunks.
_GOLDEN_WHATSAPP_EXPORT = """\
[15/05/2026, 09:00:00] - Anna Kowalska: Czy ból w okolicy miednicy jest normalny w 36. tygodniu?
[15/05/2026, 09:01:30] - Położna: Tak, ból miednicy w 36. tygodniu jest typowy. Dziecko opuszcza się ku dołowi.
[15/05/2026, 09:01:45] - Położna: Mój numer to +48 601 234 567 jeśli będziesz potrzebować pomocy.
[15/05/2026, 09:02:00] - Anna Kowalska: Dziękuję bardzo. Napiszę na anna.kowalska@gmail.com
Messages and calls are end-to-end encrypted. No one outside of this chat, not even WhatsApp, can read or listen to them.
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def firestore_client():
    """Firestore client directed at the local emulator.

    Requires FIRESTORE_EMULATOR_HOST=localhost:8080 in the environment.
    """
    host = os.environ.get("FIRESTORE_EMULATOR_HOST", "localhost:8080")
    os.environ["FIRESTORE_EMULATOR_HOST"] = host
    client = firestore.Client(project=_PROJECT_ID)
    yield client


@pytest.fixture()
def captured_audit_events() -> list[dict[str, Any]]:
    """Captures every call to core.audit.write_event and returns them as a list.

    Why: The integration test must verify audit events without hitting real
    GCS/Cloud Logging. Patching at the source module means any module that
    calls ``core.audit.write_event(...)`` directly will be intercepted.
    """
    events: list[dict[str, Any]] = []

    def _capture(event_type: str, **kwargs: Any) -> None:
        events.append({"event_type": event_type, **kwargs})

    with patch("core.audit.write_event", side_effect=_capture):
        yield events


@pytest.fixture()
def admin_client(monkeypatch, captured_audit_events):  # noqa: ARG001 — fixture must activate
    """FastAPI TestClient with admin token and Firestore emulator env vars set.

    captured_audit_events is injected here (even though unused directly) so
    that the patch is active before the TestClient starts handling requests.
    """
    monkeypatch.setenv("ADMIN_TOKEN", _ADMIN_TOKEN)
    monkeypatch.setenv(
        "FIRESTORE_EMULATOR_HOST",
        os.environ.get("FIRESTORE_EMULATOR_HOST", "localhost:8080"),
    )
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", _PROJECT_ID)
    monkeypatch.setenv("SPACY_MODEL", "xx_ent_wiki_sm")
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _poll_import(
    client: TestClient,
    import_id: str,
    *,
    timeout_s: float = 10.0,
    interval_s: float = 0.1,
) -> dict[str, Any]:
    """Poll GET /api/admin/kb/imports/{import_id} until status is terminal.

    Terminal statuses: completed, failed, no_pairs_found.
    Raises TimeoutError if terminal status is not reached within timeout_s.
    """
    terminal = {"completed", "failed", "no_pairs_found"}
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        resp = client.get(
            f"/api/admin/kb/imports/{import_id}",
            headers={"X-Admin-Token": _ADMIN_TOKEN},
        )
        assert resp.status_code == 200, (
            f"GET /api/admin/kb/imports/{import_id} returned {resp.status_code}: {resp.text}"
        )
        data = resp.json()
        if data["status"] in terminal:
            return data
        time.sleep(interval_s)
    raise TimeoutError(
        f"Import {import_id!r} did not reach terminal status within {timeout_s}s"
    )


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.vcr
@pytest.mark.integration
def test_post_upload_and_poll_until_completed(
    admin_client: TestClient,
    firestore_client: firestore.Client,
    captured_audit_events: list[dict[str, Any]],
):
    """Full import flow: upload → pipeline → poll → Firestore + audit assertions.

    Why encoding each assertion matters:
    - 202 + import_id: caller contract for the async pattern
    - status=processing on POST response: ensures UI can display progress state
    - status=completed on final GET: pipeline ran without error
    - kb_imports fields: compliance requires filename_hash (never real filename)
    - kb_chunks no-PII: GDPR/RODO — no personal data in the knowledge base
    - audit event fields: 7-year retention audit trail requires chunk_id +
      import_id + content_hash on every staged event
    """
    # ── POST: upload the golden WhatsApp export ──────────────────────────────
    resp = admin_client.post(
        "/api/admin/kb/imports",
        headers={"X-Admin-Token": _ADMIN_TOKEN},
        files={
            "file": (
                "export.txt",
                BytesIO(_GOLDEN_WHATSAPP_EXPORT.encode("utf-8")),
                "text/plain",
            )
        },
        data={"source_format": "whatsapp_txt"},
    )

    assert resp.status_code == 202, (
        f"Expected 202 Accepted, got {resp.status_code}: {resp.text}"
    )
    created = resp.json()
    assert "import_id" in created, "202 response must contain import_id"
    assert created["status"] == "processing", (
        "Initial status in 202 response must be 'processing'"
    )
    assert "submitted_at" in created, "202 response must contain submitted_at"

    import_id: str = created["import_id"]

    # ── POLL: wait for terminal status ────────────────────────────────────────
    final = _poll_import(admin_client, import_id)
    assert final["status"] == "completed", (
        f"Import ended with status={final['status']!r}; "
        f"error_message={final.get('error_message')!r}"
    )
    chunks_extracted: int = final.get("chunks_extracted", 0)
    assert chunks_extracted > 0, (
        "At least one Q&A pair must be extracted from the golden export"
    )

    # ── FIRESTORE: kb_imports doc ─────────────────────────────────────────────
    import_doc = (
        firestore_client.collection("kb_imports").document(import_id).get()
    )
    assert import_doc.exists, f"kb_imports/{import_id} must exist in Firestore"
    import_data = import_doc.to_dict()

    assert import_data["status"] == "completed"
    assert "filename_hash" in import_data, (
        "filename_hash must be stored — the real filename must never be persisted"
    )
    assert "submitted_by" in import_data
    assert import_data["source_format"] == "whatsapp_txt"
    assert "submitted_at" in import_data
    assert "completed_at" in import_data, "completed_at must be set on completion"
    assert "chunks_extracted" in import_data
    assert import_data["chunks_extracted"] > 0
    assert "chunks_flagged_duplicate" in import_data

    # ── FIRESTORE: kb_chunks docs ─────────────────────────────────────────────
    staged_chunks = list(
        firestore_client.collection("kb_chunks")
        .where("import_id", "==", import_id)
        .where("status", "==", "staged")
        .stream()
    )
    assert len(staged_chunks) > 0, (
        f"Expected at least one staged kb_chunks doc for import_id={import_id!r}"
    )
    assert len(staged_chunks) == chunks_extracted, (
        f"Firestore chunk count ({len(staged_chunks)}) must equal "
        f"chunks_extracted field ({chunks_extracted})"
    )

    for chunk_doc in staged_chunks:
        chunk = chunk_doc.to_dict()
        chunk_id = chunk_doc.id

        # Required fields per data-model.md
        assert chunk.get("question"), f"chunk {chunk_id}: question must be non-empty"
        assert chunk.get("answer"), f"chunk {chunk_id}: answer must be non-empty"
        assert "content_hash" in chunk, f"chunk {chunk_id}: content_hash must be set"
        assert chunk.get("source_type") == "export", (
            f"chunk {chunk_id}: source_type must be 'export'"
        )
        assert chunk.get("import_id") == import_id, (
            f"chunk {chunk_id}: import_id must match"
        )
        assert chunk.get("status") == "staged"
        assert "staged_at" in chunk, f"chunk {chunk_id}: staged_at must be set"

        # PII must NOT appear in question or answer after stripping
        combined_text = chunk["question"] + " " + chunk["answer"]
        for pattern in _PII_PATTERNS:
            assert not pattern.search(combined_text), (
                f"PII pattern {pattern.pattern!r} found in chunk {chunk_id}: "
                f"{combined_text[:120]!r}"
            )

    # ── AUDIT: kb_chunk_staged events ────────────────────────────────────────
    staged_events = [
        e for e in captured_audit_events if e["event_type"] == "kb_chunk_staged"
    ]
    assert len(staged_events) == len(staged_chunks), (
        f"Expected {len(staged_chunks)} kb_chunk_staged audit events, "
        f"got {len(staged_events)}"
    )

    chunk_ids_in_firestore = {doc.id for doc in staged_chunks}
    for event in staged_events:
        assert event.get("event_type") == "kb_chunk_staged"
        assert "chunk_id" in event, "kb_chunk_staged event must include chunk_id"
        assert "import_id" in event, "kb_chunk_staged event must include import_id"
        assert "content_hash" in event, (
            "kb_chunk_staged event must include content_hash for audit provenance"
        )
        assert event["import_id"] == import_id, (
            f"Audit event import_id={event['import_id']!r} does not match {import_id!r}"
        )
        assert event["chunk_id"] in chunk_ids_in_firestore, (
            f"Audit event chunk_id={event['chunk_id']!r} not found among "
            f"Firestore staged chunks"
        )
