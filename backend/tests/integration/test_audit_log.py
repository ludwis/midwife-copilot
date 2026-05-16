"""Integration tests for audit log coverage (T048).

TDD: Verifies all 8 knowledge-event types are emitted with required fields
across a full import → review → query sequence, per data-model.md §Audit Log Schema.

Required event types:
  kb_import_started, kb_import_completed, kb_chunk_staged,
  kb_chunk_approved, kb_chunk_edited, kb_chunk_discarded,
  kb_chunk_promoted, kb_query_test

NOTE: kb_chunk_promoted is currently absent from chunks.py (TDD RED until T052
      adds the missing audit.write_event() call for the approve/edit_approve branches).

Requirements to run:
  FIRESTORE_EMULATOR_HOST=localhost:8080  (Firestore emulator must be running)

GCS and Cloud Logging writes are intercepted — no real GCS bucket required.
Gemini extraction, spaCy PII stripping, deduplication embeddings, and Vertex AI
promotion are all mocked so the test runs fully offline.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from io import BytesIO
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from google.cloud import firestore

from api.main import app
from bot.kb.deduplicator import DedupResult
from bot.kb.extractor import ChunkDraft

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ADMIN_TOKEN = "integration-test-token"
_PROJECT_ID = "test-project"

# Three fixed Q&A pairs returned by the mocked extractor for every import.
_FIXTURE_CHUNKS = [
    ChunkDraft(
        question="Is pelvic pressure normal at 36 weeks?",
        answer="Yes, pelvic pressure is common in the third trimester.",
    ),
    ChunkDraft(
        question="When should I call my midwife about contractions?",
        answer="Call if contractions are 5 minutes apart for 1 hour.",
    ),
    ChunkDraft(
        question="Can I exercise while pregnant?",
        answer="Light exercise is generally safe with your midwife's guidance.",
    ),
]

# Minimal valid WhatsApp export — content is irrelevant because the extractor is mocked.
_MINIMAL_WHATSAPP = (
    "[15/05/2026, 09:00:00] - Client: Czy ból miednicy jest normalny?\n"
    "[15/05/2026, 09:00:30] - Midwife: Tak, to typowe w 3. trymestrze.\n"
)

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
def captured_audit() -> dict[str, Any]:
    """Capture core.audit.write_event calls without real GCS/Cloud Logging writes.

    The side_effect reconstructs the same JSON line that write_event would produce,
    giving both structured event dicts and raw JSONL strings for assertion.

    Returns a dict with keys:
      'events' — list of dicts: {event_type, timestamp, actor, **extra_fields}
      'lines'  — list of JSON strings (what would be appended to audit.jsonl)

    Why: Tests must verify that (a) the right event types are emitted,
    (b) required fields are present, and (c) the payload serialises to valid JSON.
    Reconstructing the line inside the side_effect tests (b) and (c) without
    needing a real GCS bucket.
    """
    result: dict[str, Any] = {"events": [], "lines": []}

    def _capture(event_type: str, actor: str, **kwargs: Any) -> None:
        now = datetime.now(timezone.utc)
        entry: dict[str, Any] = {
            "event_type": event_type,
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z",
            "actor": actor,
            **kwargs,
        }
        result["events"].append(entry)
        result["lines"].append(json.dumps(entry, ensure_ascii=False))

    with patch("core.audit.write_event", side_effect=_capture):
        yield result


@pytest.fixture()
def admin_client(monkeypatch, captured_audit):  # noqa: ARG001 — fixture must activate patch
    """FastAPI TestClient with admin token and emulator env vars set.

    captured_audit is injected here to ensure the core.audit.write_event patch
    is active before the TestClient begins handling requests.
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


def _content_hash(question: str, answer: str) -> str:
    return hashlib.sha256((question + "\n" + answer).encode()).hexdigest()


def _poll_import(
    client: TestClient,
    import_id: str,
    *,
    timeout_s: float = 10.0,
    interval_s: float = 0.1,
) -> dict[str, Any]:
    """Poll GET /api/admin/kb/imports/{import_id} until the pipeline reaches a terminal status."""
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


def _make_mock_discovery_engine(query_result_count: int = 1) -> MagicMock:
    """Build a minimal mock of google.cloud.discoveryengine_v1 for production query tests."""
    mock_struct_q = MagicMock()
    mock_struct_q.string_value = "Is pelvic pressure normal at 36 weeks?"
    mock_struct_a = MagicMock()
    mock_struct_a.string_value = "Yes, pelvic pressure is common in the third trimester."
    mock_struct_at = MagicMock()
    mock_struct_at.string_value = "2026-05-16T00:00:00Z"

    fake_doc = MagicMock()
    fake_doc.id = "chunk-prod-001"
    fake_doc.struct_data.fields = {
        "question": mock_struct_q,
        "answer": mock_struct_a,
        "promoted_at": mock_struct_at,
    }
    fake_doc.derived_struct_data.fields = {}

    fake_result = MagicMock()
    fake_result.document = fake_doc

    fake_response = MagicMock()
    fake_response.results = [fake_result] * query_result_count

    mock_client = MagicMock()
    mock_client.search.return_value = fake_response

    mock_module = MagicMock()
    mock_module.SearchServiceClient.return_value = mock_client
    return mock_module


async def _fake_promote(
    chunk_id: str, question: str, answer: str, content_hash: str
) -> str:
    """Stub for bot.kb.promotion.promote_chunk — returns a deterministic vertex ID."""
    return f"vertex-prod-{chunk_id}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_all_8_event_types_emitted_in_full_sequence(
    admin_client: TestClient,
    firestore_client: firestore.Client,  # noqa: ARG001 — ensures emulator is up
    captured_audit: dict[str, Any],
):
    """Full import → review → query sequence emits all 8 required audit event types.

    Sequence executed:
      1. POST /imports → kb_import_started + kb_chunk_staged×3 + kb_import_completed
      2. PATCH approve   → kb_chunk_approved + kb_chunk_promoted (TDD RED: T052 adds)
      3. PATCH edit_approve → kb_chunk_edited + kb_chunk_promoted  (TDD RED: T052 adds)
      4. PATCH discard   → kb_chunk_discarded
      5. GET /production/query → kb_query_test

    Why: SC-003 requires 100% audit coverage of all knowledge-management events.
    A single sequence test that spans the full pipeline is the only reliable way
    to verify that no event type silently regresses.
    """
    _REQUIRED_EVENTS = {
        "kb_import_started",
        "kb_import_completed",
        "kb_chunk_staged",
        "kb_chunk_approved",
        "kb_chunk_edited",
        "kb_chunk_discarded",
        "kb_chunk_promoted",  # TDD RED: not yet emitted — T052 will add
        "kb_query_test",
    }

    with (
        patch("api.admin.kb.imports.extract_qa_pairs", return_value=_FIXTURE_CHUNKS),
        patch(
            "api.admin.kb.imports.strip_pii",
            side_effect=lambda content: (content, False),
        ),
        patch(
            "bot.kb.deduplicator.check_duplicate",
            return_value=DedupResult(flag=None),
        ),
        patch(
            "bot.kb.promotion.promote_chunk",
            side_effect=_fake_promote,
        ),
    ):
        # ── Step 1: POST /imports ─────────────────────────────────────────
        resp = admin_client.post(
            "/api/admin/kb/imports",
            headers={"X-Admin-Token": _ADMIN_TOKEN},
            files={
                "file": (
                    "export.txt",
                    BytesIO(_MINIMAL_WHATSAPP.encode("utf-8")),
                    "text/plain",
                ),
            },
            data={"source_format": "whatsapp_txt"},
        )
        assert resp.status_code == 202, (
            f"POST /imports failed: {resp.status_code} {resp.text}"
        )
        import_id: str = resp.json()["import_id"]

        # Poll until pipeline completes
        final = _poll_import(admin_client, import_id)
        assert final["status"] == "completed", (
            f"Import pipeline did not complete: {final}"
        )

        # Retrieve the 3 staged chunks
        chunks_resp = admin_client.get(
            "/api/admin/kb/chunks",
            headers={"X-Admin-Token": _ADMIN_TOKEN},
            params={"import_id": import_id, "status": "staged"},
        )
        assert chunks_resp.status_code == 200, (
            f"GET /chunks failed: {chunks_resp.status_code} {chunks_resp.text}"
        )
        staged = chunks_resp.json()["chunks"]
        assert len(staged) == 3, (
            f"Expected 3 staged chunks for import_id={import_id}, got {len(staged)}"
        )
        chunk_ids = [c["chunk_id"] for c in staged]

        # ── Step 2: Approve chunk[0] ──────────────────────────────────────
        resp = admin_client.patch(
            f"/api/admin/kb/chunks/{chunk_ids[0]}",
            headers={"X-Admin-Token": _ADMIN_TOKEN},
            json={"action": "approve"},
        )
        assert resp.status_code == 200, (
            f"approve failed: {resp.status_code} {resp.text}"
        )

        # ── Step 3: Edit-approve chunk[1] ─────────────────────────────────
        edited_q = "Is pelvic pressure in the third trimester dangerous?"
        edited_a = "Mild pressure is normal; severe or sudden pain needs review."
        resp = admin_client.patch(
            f"/api/admin/kb/chunks/{chunk_ids[1]}",
            headers={"X-Admin-Token": _ADMIN_TOKEN},
            json={"action": "edit_approve", "question": edited_q, "answer": edited_a},
        )
        assert resp.status_code == 200, (
            f"edit_approve failed: {resp.status_code} {resp.text}"
        )

        # ── Step 4: Discard chunk[2] ──────────────────────────────────────
        resp = admin_client.patch(
            f"/api/admin/kb/chunks/{chunk_ids[2]}",
            headers={"X-Admin-Token": _ADMIN_TOKEN},
            json={"action": "discard"},
        )
        assert resp.status_code == 200, (
            f"discard failed: {resp.status_code} {resp.text}"
        )

        # ── Step 5: Production query (mock Discovery Engine) ─────────────
        mock_de = _make_mock_discovery_engine(query_result_count=1)
        with patch.dict(sys.modules, {"google.cloud.discoveryengine_v1": mock_de}):
            resp = admin_client.get(
                "/api/admin/kb/production/query",
                headers={"X-Admin-Token": _ADMIN_TOKEN},
                params={"q": "pelvic pressure"},
            )
        assert resp.status_code == 200, (
            f"production query failed: {resp.status_code} {resp.text}"
        )

    # ── Assert all 8 event types are present ──────────────────────────────
    events: list[dict[str, Any]] = captured_audit["events"]
    emitted_types = {e["event_type"] for e in events}
    missing = _REQUIRED_EVENTS - emitted_types
    assert not missing, (
        f"Missing event types: {missing!r}\n"
        f"Emitted types: {emitted_types!r}\n"
        f"All events: {[e['event_type'] for e in events]}"
    )

    # ── Assert every emitted event has the base fields ─────────────────────
    # (event_type, timestamp, actor)
    lines: list[str] = captured_audit["lines"]
    assert len(lines) == len(events), "Each write_event call must produce one JSONL line"
    for line, event in zip(lines, events):
        parsed = json.loads(line)
        assert "event_type" in parsed, f"Missing event_type in line: {line}"
        assert "timestamp" in parsed, f"Missing timestamp in line: {line}"
        assert "actor" in parsed, f"Missing actor in line: {line}"
        # timestamp must be ISO-8601 UTC
        ts = parsed["timestamp"]
        assert ts.endswith("Z"), f"timestamp must end with Z (UTC): {ts!r}"
        assert "T" in ts, f"timestamp must be ISO-8601: {ts!r}"

    # ── Assert kb_import_completed includes duration_ms ───────────────────
    completed_events = [e for e in events if e["event_type"] == "kb_import_completed"]
    assert completed_events, "kb_import_completed event must be emitted"
    for ev in completed_events:
        assert "duration_ms" in ev, (
            f"kb_import_completed must include duration_ms; got fields: {list(ev.keys())}"
        )
        assert isinstance(ev["duration_ms"], int), (
            f"duration_ms must be an int, got: {type(ev['duration_ms'])}"
        )

    # ── Assert kb_chunk_edited includes content_hash_before and _after ─────
    edited_events = [e for e in events if e["event_type"] == "kb_chunk_edited"]
    assert edited_events, "kb_chunk_edited event must be emitted"
    for ev in edited_events:
        assert "content_hash_before" in ev, (
            f"kb_chunk_edited must include content_hash_before; got: {list(ev.keys())}"
        )
        assert "content_hash_after" in ev, (
            f"kb_chunk_edited must include content_hash_after; got: {list(ev.keys())}"
        )
        assert ev["content_hash_before"] != ev["content_hash_after"], (
            "content_hash_before and content_hash_after must differ after an edit"
        )

    # ── Assert kb_chunk_staged includes required fields per data-model.md ──
    staged_events = [e for e in events if e["event_type"] == "kb_chunk_staged"]
    assert len(staged_events) == 3, (
        f"Expected 3 kb_chunk_staged events (one per chunk), got {len(staged_events)}"
    )
    for ev in staged_events:
        assert "import_id" in ev, f"kb_chunk_staged missing import_id: {ev}"
        assert "chunk_id" in ev, f"kb_chunk_staged missing chunk_id: {ev}"
        assert "content_hash" in ev, f"kb_chunk_staged missing content_hash: {ev}"
        assert "duplicate_flag" in ev, f"kb_chunk_staged missing duplicate_flag: {ev}"
        assert ev["import_id"] == import_id, (
            f"kb_chunk_staged.import_id mismatch: {ev['import_id']} != {import_id}"
        )

    # ── Assert kb_import_started includes required fields ──────────────────
    started_events = [e for e in events if e["event_type"] == "kb_import_started"]
    assert started_events, "kb_import_started event must be emitted"
    for ev in started_events:
        assert "import_id" in ev, f"kb_import_started missing import_id: {ev}"
        assert "source_format" in ev, f"kb_import_started missing source_format: {ev}"
        assert "filename_hash" in ev, f"kb_import_started missing filename_hash: {ev}"

    # ── Assert kb_query_test includes required fields ──────────────────────
    query_events = [e for e in events if e["event_type"] == "kb_query_test"]
    assert query_events, "kb_query_test event must be emitted"
    for ev in query_events:
        assert "query_text" in ev, f"kb_query_test missing query_text: {ev}"
        assert "result_count" in ev, f"kb_query_test missing result_count: {ev}"
        assert isinstance(ev["result_count"], int), (
            f"kb_query_test.result_count must be int, got {type(ev['result_count'])}"
        )

    # ── Assert kb_chunk_promoted includes required fields ──────────────────
    # TDD: This assertion will fail until T052 adds kb_chunk_promoted events.
    promoted_events = [e for e in events if e["event_type"] == "kb_chunk_promoted"]
    assert len(promoted_events) >= 2, (  # one for approve, one for edit_approve
        f"Expected at least 2 kb_chunk_promoted events (approve + edit_approve); "
        f"got {len(promoted_events)}.  "
        f"NOTE: T052 must add audit.write_event('kb_chunk_promoted', ...) in chunks.py."
    )
    for ev in promoted_events:
        assert "chunk_id" in ev, f"kb_chunk_promoted missing chunk_id: {ev}"
        assert "content_hash" in ev, f"kb_chunk_promoted missing content_hash: {ev}"
        assert "production_vertex_id" in ev, (
            f"kb_chunk_promoted missing production_vertex_id: {ev}"
        )
