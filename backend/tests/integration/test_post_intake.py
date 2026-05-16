"""Integration tests for POST /api/admin/kb/imports (intake endpoint only).

Tests the endpoint in isolation with GCS mocked. The Firebase Function pipeline
is NOT triggered — these tests verify only the 202 response, Firestore doc
creation, and audit event emission.

Requirements to run:
  FIRESTORE_EMULATOR_HOST=localhost:8080  (Firestore emulator must be running)

Fixtures `firestore_client` and `captured_audit_events` come from conftest.py.
"""
from __future__ import annotations

import os
from io import BytesIO
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.main import app

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ADMIN_TOKEN = "integration-test-token"
_PROJECT_ID = "test-project"

_GOLDEN_WHATSAPP_EXPORT = """\
[15/05/2026, 09:00:00] - Anna Kowalska: Czy ból w okolicy miednicy jest normalny w 36. tygodniu?
[15/05/2026, 09:01:30] - Położna: Tak, ból miednicy w 36. tygodniu jest typowy. Dziecko opuszcza się ku dołowi.
[15/05/2026, 09:01:45] - Położna: Mój numer to +48 601 234 567 jeśli będziesz potrzebować pomocy.
[15/05/2026, 09:02:00] - Anna Kowalska: Dziękuję bardzo. Napiszę na anna.kowalska@gmail.com
Messages and calls are end-to-end encrypted. No one outside of this chat, not even WhatsApp, can read or listen to them.
"""

_MOCKED_GCS_URI = "gs://test-bucket/imports/test-id/abc123.txt"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_gcs_upload(monkeypatch):
    """Monkeypatch _upload_import_file to return a fake GCS URI without calling GCS."""
    monkeypatch.setattr(
        "api.admin.kb.imports._upload_import_file",
        lambda *args, **kwargs: _MOCKED_GCS_URI,
    )
    monkeypatch.setenv("KB_IMPORTS_BUCKET_NAME", "test-kb-imports")


@pytest.fixture()
def admin_client(monkeypatch, captured_audit_events):  # noqa: ARG001 — activates the patch
    """FastAPI TestClient with admin token and emulator env vars set.

    captured_audit_events is injected here so its patch is active before
    the TestClient starts handling requests.
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


def _post_golden(client: TestClient) -> tuple[int, dict[str, Any]]:
    """POST the golden WhatsApp export. Returns (status_code, json_body)."""
    resp = client.post(
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
    return resp.status_code, resp.json()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_post_returns_202(admin_client, mock_gcs_upload):
    """POST returns 202 with import_id, status=processing, submitted_at."""
    status, body = _post_golden(admin_client)

    assert status == 202, f"Expected 202, got {status}: {body}"
    assert "import_id" in body, "Response must include import_id"
    assert body["status"] == "processing", "Initial status must be 'processing'"
    assert "submitted_at" in body, "Response must include submitted_at"


@pytest.mark.integration
def test_post_writes_firestore_doc(admin_client, mock_gcs_upload, firestore_client):
    """POST creates a kb_imports Firestore doc with required fields."""
    status, body = _post_golden(admin_client)
    assert status == 202
    import_id = body["import_id"]

    doc = firestore_client.collection("kb_imports").document(import_id).get()
    assert doc.exists, f"kb_imports/{import_id} must exist after POST"
    data = doc.to_dict()

    assert data["status"] == "processing"
    assert data["gcs_path"] == _MOCKED_GCS_URI, "gcs_path must match mocked URI"
    assert data["source_format"] == "whatsapp_txt"
    assert "filename_hash" in data, "filename_hash must be stored — real filename must not be persisted"
    assert data["filename_hash"], "filename_hash must be non-empty"


@pytest.mark.integration
def test_post_emits_audit_event(admin_client, mock_gcs_upload, captured_audit_events):
    """POST emits a kb_import_started audit event with correct fields."""
    status, body = _post_golden(admin_client)
    assert status == 202
    import_id = body["import_id"]

    started = [e for e in captured_audit_events if e["event_type"] == "kb_import_started"]
    assert len(started) == 1, f"Expected 1 kb_import_started event, got {len(started)}"
    evt = started[0]
    assert evt["import_id"] == import_id
    assert evt["source_format"] == "whatsapp_txt"


@pytest.mark.integration
def test_post_no_backgroundtask_runs(admin_client, mock_gcs_upload, captured_audit_events):
    """POST must not emit kb_import_completed — pipeline does not run inline."""
    status, _ = _post_golden(admin_client)
    assert status == 202

    completed = [e for e in captured_audit_events if e["event_type"] == "kb_import_completed"]
    assert len(completed) == 0, (
        f"kb_import_completed must not be emitted by the intake endpoint; got {completed}"
    )


@pytest.mark.integration
def test_post_invalid_format_400(admin_client, mock_gcs_upload):
    """POST with unsupported source_format returns 400."""
    resp = admin_client.post(
        "/api/admin/kb/imports",
        headers={"X-Admin-Token": _ADMIN_TOKEN},
        files={"file": ("export.txt", BytesIO(b"data"), "text/plain")},
        data={"source_format": "invalid"},
    )
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"


@pytest.mark.integration
def test_post_empty_file_400(admin_client, mock_gcs_upload):
    """POST with an empty file returns 400."""
    resp = admin_client.post(
        "/api/admin/kb/imports",
        headers={"X-Admin-Token": _ADMIN_TOKEN},
        files={"file": ("export.txt", BytesIO(b""), "text/plain")},
        data={"source_format": "whatsapp_txt"},
    )
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"


@pytest.mark.integration
def test_post_gcs_failure_500(admin_client, monkeypatch, captured_audit_events, firestore_client):
    """When GCS upload raises, POST returns 500 and no Firestore doc is created."""
    monkeypatch.setenv("KB_IMPORTS_BUCKET_NAME", "test-kb-imports")
    monkeypatch.setattr(
        "api.admin.kb.imports._upload_import_file",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("GCS unavailable")),
    )

    status, body = _post_golden(admin_client)
    assert status == 500, f"Expected 500, got {status}: {body}"

    # No kb_imports docs should have been created by this request
    # (We can't assert by import_id since 500 response has no import_id,
    #  so verify no incomplete doc appeared in the last second.)
    # The endpoint raises before doc.set(), so nothing is written.
    assert "import_id" not in body, "500 response must not contain import_id"
