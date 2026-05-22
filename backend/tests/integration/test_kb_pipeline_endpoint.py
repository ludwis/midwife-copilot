"""Integration tests for POST /internal/kb/process-import/{import_id}.

Tests exercise the full FastAPI endpoint via TestClient. The Firestore
emulator is used for real Firestore reads/writes. GCS, Gemini (extract_qa_pairs_async),
and Google OIDC token validation are mocked.

The endpoint's key contracts under test:
- Happy path: full pipeline completes, Firestore doc updated, kb_chunks created
- Idempotency: requests for already-completed/extracting imports are skipped
- Transient errors: return 503 and reset status=processing for Cloud Tasks retry
- Fatal errors: return 200 and write status=failed (no retry)
- Auth: 403 on missing or wrong OIDC token

Requirements:
  FIRESTORE_EMULATOR_HOST=localhost:8080  (Firestore emulator must be running)
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from google.cloud import firestore

from api.main import app
from bot.kb.extractor import ChunkDraft

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_ID = "test-project"
_TASKS_SA_EMAIL = "tasks-sa@test.iam.gserviceaccount.com"
_CLOUD_RUN_URL = "https://stilla-test.run.app"

# Minimal WhatsApp export with parseable content
_GOLDEN_WHATSAPP = (
    "[15/05/2026, 09:00:00] - Anna K: Czy ból w okolicy miednicy jest normalny"
    " w 36. tygodniu?\n"
    "[15/05/2026, 09:01:30] - Położna: Tak, ból miednicy w 36. tygodniu jest"
    " typowy. Dziecko opuszcza się ku dołowi.\n"
    "[15/05/2026, 09:02:00] - Anna K: Dziękuję bardzo.\n"
    "[15/05/2026, 09:02:30] - Położna: Proszę, do dyspozycji.\n"
    "Messages and calls are end-to-end encrypted.\n"
)

_MOCK_CHUNKS = [
    ChunkDraft(
        question=f"Pytanie testowe {i}",
        answer=f"Odpowiedź testowa {i}",
        language="pl",
    )
    for i in range(3)
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_import_doc(
    db: firestore.Client,
    import_id: str,
    status: str = "processing",
) -> None:
    """Write a kb_imports document into the Firestore emulator."""
    db.collection("kb_imports").document(import_id).set(
        {
            "status": status,
            "gcs_path": f"gs://test-bucket/imports/{import_id}/export.txt",
            "source_format": "whatsapp_txt",
            "submitted_at": datetime.now(timezone.utc),
            "submitted_by": "midwife",
            "filename_hash": "abc123",
        }
    )


def _make_gcs_mock(content_bytes: bytes) -> MagicMock:
    """Return a mock for storage.Client() that yields *content_bytes* on download."""
    mock_blob = MagicMock()
    mock_blob.download_as_bytes.return_value = content_bytes
    mock_gcs = MagicMock()
    mock_gcs.return_value.bucket.return_value.list_blobs.return_value = [mock_blob]
    return mock_gcs


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def import_id() -> str:
    """Unique import ID per test — prevents Firestore state pollution."""
    return f"test-ep-{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def _patch_firestore_singletons(monkeypatch, firestore_client: firestore.Client):
    """Override the lazy Firestore singletons in kb_pipeline and staging.

    Without this, _get_db() and _get_firestore() would try to create real
    google.cloud.Firestore clients, which require GCP credentials.
    Monkeypatch restores the original (None) after each test automatically.
    """
    import api.internal.kb_pipeline as _kb
    import bot.kb.staging as _staging

    monkeypatch.setattr(_kb, "_db", firestore_client)
    monkeypatch.setattr(_staging, "_firestore_client", firestore_client)


@pytest.fixture()
def internal_client(monkeypatch, captured_audit_events: list[dict[str, Any]]):  # noqa: ARG001
    """TestClient with OIDC auth mocked to accept a fake token.

    - TASKS_SA_EMAIL is set so require_tasks_oidc validates correctly.
    - google.oauth2.id_token.verify_oauth2_token is replaced with a stub
      that returns a valid idinfo dict without calling Google's servers.
    - All requests include Authorization: Bearer fake-oidc-token by default.
    - captured_audit_events fixture (from conftest.py) is included as a
      dependency to ensure core.audit.write_event is patched during the test.
    """
    monkeypatch.setenv("TASKS_SA_EMAIL", _TASKS_SA_EMAIL)
    monkeypatch.setenv("CLOUD_RUN_SERVICE_URL", _CLOUD_RUN_URL)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", _PROJECT_ID)

    # Patch module-level vars in auth.py (read at import time, not request time).
    import api.internal.auth as _auth
    monkeypatch.setattr(_auth, "TASKS_SA_EMAIL", _TASKS_SA_EMAIL)
    monkeypatch.setattr(_auth, "CLOUD_RUN_SERVICE_URL", _CLOUD_RUN_URL)

    with patch(
        "google.oauth2.id_token.verify_oauth2_token",
        return_value={"email": _TASKS_SA_EMAIL},
    ):
        client = TestClient(app, raise_server_exceptions=False)
        client.headers.update({"Authorization": "Bearer fake-oidc-token"})
        yield client


# ---------------------------------------------------------------------------
# Tests — happy path
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_process_import_success(
    internal_client: TestClient,
    firestore_client: firestore.Client,
    import_id: str,
):
    """Full pipeline: 3 mock chunks extracted → 3 kb_chunks docs staged in Firestore.

    Why each assertion matters:
    - HTTP 200 with status=completed: endpoint signalled success to Cloud Tasks
    - Firestore doc status=completed: import is terminal; idempotency guard blocks replays
    - chunks_extracted=3: metadata matches the number of chunks actually written
    - 3 staged kb_chunks: the staging writer persisted all extracted pairs
    """
    _seed_import_doc(firestore_client, import_id)

    with (
        patch(
            "api.internal.kb_pipeline.storage.Client",
            _make_gcs_mock(_GOLDEN_WHATSAPP.encode("utf-8")),
        ),
        patch(
            "api.internal.kb_pipeline.extract_qa_pairs_async",
            new=AsyncMock(return_value=_MOCK_CHUNKS),
        ),
    ):
        resp = internal_client.post(f"/internal/kb/process-import/{import_id}")

    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"

    doc = firestore_client.collection("kb_imports").document(import_id).get().to_dict()
    assert doc["status"] == "completed"
    assert doc["chunks_extracted"] == 3

    chunks = list(
        firestore_client.collection("kb_chunks")
        .where("import_id", "==", import_id)
        .where("status", "==", "staged")
        .stream()
    )
    assert len(chunks) == 3


# ---------------------------------------------------------------------------
# Tests — idempotency
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_process_import_idempotency_already_completed(
    internal_client: TestClient,
    firestore_client: firestore.Client,
    import_id: str,
):
    """Endpoint returns skipped when the import is already completed.

    Why: Cloud Tasks may retry a successful request. The endpoint must not
    run the pipeline again for a completed import.
    """
    _seed_import_doc(firestore_client, import_id, status="completed")

    resp = internal_client.post(f"/internal/kb/process-import/{import_id}")

    assert resp.status_code == 200
    assert resp.json()["status"] == "skipped"

    # Verify: no kb_chunks were created as a side effect of the skipped request.
    chunks = list(
        firestore_client.collection("kb_chunks")
        .where("import_id", "==", import_id)
        .stream()
    )
    assert len(chunks) == 0


@pytest.mark.integration
def test_process_import_idempotency_extracting(
    internal_client: TestClient,
    firestore_client: firestore.Client,
    import_id: str,
):
    """Endpoint returns skipped when another worker has already claimed the import.

    Why: status=extracting means a concurrent Cloud Tasks delivery beat this one.
    The endpoint must not double-run the pipeline.
    """
    _seed_import_doc(firestore_client, import_id, status="extracting")

    resp = internal_client.post(f"/internal/kb/process-import/{import_id}")

    assert resp.status_code == 200
    assert resp.json()["status"] == "skipped"


# ---------------------------------------------------------------------------
# Tests — edge cases
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_process_import_no_pairs_found(
    internal_client: TestClient,
    firestore_client: firestore.Client,
    import_id: str,
):
    """Endpoint transitions to no_pairs_found when Gemini returns an empty list."""
    _seed_import_doc(firestore_client, import_id)

    with (
        patch(
            "api.internal.kb_pipeline.storage.Client",
            _make_gcs_mock(_GOLDEN_WHATSAPP.encode("utf-8")),
        ),
        patch(
            "api.internal.kb_pipeline.extract_qa_pairs_async",
            new=AsyncMock(return_value=[]),
        ),
    ):
        resp = internal_client.post(f"/internal/kb/process-import/{import_id}")

    assert resp.status_code == 200
    doc = firestore_client.collection("kb_imports").document(import_id).get().to_dict()
    assert doc["status"] == "no_pairs_found"


# ---------------------------------------------------------------------------
# Tests — error handling
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_process_import_transient_gemini_error(
    internal_client: TestClient,
    firestore_client: firestore.Client,
    import_id: str,
):
    """503 on ServiceUnavailable; Firestore status reset to processing for retry.

    Why status must be reset: when the endpoint claims the import it sets
    status=extracting. If it then returns 503, Cloud Tasks retries — but the
    idempotency guard sees status=extracting and skips. By resetting to
    status=processing, we allow the retry to claim and run the pipeline.
    """
    import google.api_core.exceptions

    _seed_import_doc(firestore_client, import_id)

    with (
        patch(
            "api.internal.kb_pipeline.storage.Client",
            _make_gcs_mock(_GOLDEN_WHATSAPP.encode("utf-8")),
        ),
        patch(
            "api.internal.kb_pipeline.extract_qa_pairs_async",
            side_effect=google.api_core.exceptions.ServiceUnavailable("quota exceeded"),
        ),
    ):
        resp = internal_client.post(f"/internal/kb/process-import/{import_id}")

    assert resp.status_code == 503

    doc = firestore_client.collection("kb_imports").document(import_id).get().to_dict()
    # Must be processing (not extracting or failed) so the next Cloud Tasks attempt
    # can claim the import and re-run the pipeline.
    assert doc["status"] == "processing"


@pytest.mark.integration
def test_process_import_fatal_error(
    internal_client: TestClient,
    firestore_client: firestore.Client,
    import_id: str,
):
    """HTTP 200 and status=failed on non-transient errors (no Cloud Tasks retry).

    Why 200: returning a non-2xx to Cloud Tasks would trigger a retry that
    cannot succeed (e.g. the GCS bucket doesn't exist). Fatal errors must
    be acknowledged so the task is not retried indefinitely.
    """
    _seed_import_doc(firestore_client, import_id)

    with patch(
        "api.internal.kb_pipeline.storage.Client",
        side_effect=RuntimeError("bucket not found"),
    ):
        resp = internal_client.post(f"/internal/kb/process-import/{import_id}")

    assert resp.status_code == 200
    doc = firestore_client.collection("kb_imports").document(import_id).get().to_dict()
    assert doc["status"] == "failed"
    assert "bucket not found" in doc.get("error_message", "")


# ---------------------------------------------------------------------------
# Tests — authentication
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_process_import_missing_oidc_token(
    monkeypatch,
    import_id: str,
):
    """403 when no Authorization header is present.

    Do not use the internal_client fixture — it pre-sets the Bearer token.
    """
    monkeypatch.setenv("TASKS_SA_EMAIL", _TASKS_SA_EMAIL)
    monkeypatch.setenv("CLOUD_RUN_SERVICE_URL", _CLOUD_RUN_URL)
    import api.internal.auth as _auth
    monkeypatch.setattr(_auth, "TASKS_SA_EMAIL", _TASKS_SA_EMAIL)
    monkeypatch.setattr(_auth, "CLOUD_RUN_SERVICE_URL", _CLOUD_RUN_URL)

    client = TestClient(app, raise_server_exceptions=False)
    # No Authorization header — endpoint must reject with 403.
    resp = client.post(f"/internal/kb/process-import/{import_id}")
    assert resp.status_code == 403


@pytest.mark.integration
def test_process_import_wrong_sa_email(
    monkeypatch,
    import_id: str,
):
    """403 when the OIDC token belongs to the wrong service account.

    Why: Cloud Tasks tokens are verified against TASKS_SA_EMAIL. A token from
    a different account must be rejected even if the JWT itself is valid.
    """
    monkeypatch.setenv("TASKS_SA_EMAIL", _TASKS_SA_EMAIL)
    monkeypatch.setenv("CLOUD_RUN_SERVICE_URL", _CLOUD_RUN_URL)
    import api.internal.auth as _auth
    monkeypatch.setattr(_auth, "TASKS_SA_EMAIL", _TASKS_SA_EMAIL)
    monkeypatch.setattr(_auth, "CLOUD_RUN_SERVICE_URL", _CLOUD_RUN_URL)

    with patch(
        "google.oauth2.id_token.verify_oauth2_token",
        return_value={"email": "wrong@other.iam.gserviceaccount.com"},
    ):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            f"/internal/kb/process-import/{import_id}",
            headers={"Authorization": "Bearer fake-token"},
        )

    assert resp.status_code == 403
