"""Integration tests for the Firebase Cloud Function extract_kb_import (stub).

The function was refactored in Phase 2 to only enqueue a Cloud Tasks task;
the full pipeline now lives in the /internal/kb/process-import endpoint.

Tests call the handler directly (no Firebase runtime required). Firebase
packages (firebase_admin, firebase_functions) are stubbed in sys.modules
before import so the test suite runs without installing them.

The Firestore emulator is used to pre-seed realistic docs; the function
itself never reads Firestore — it only calls Cloud Tasks.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Firebase stubs — MUST be registered in sys.modules before importing
# functions.main, because main.py calls firebase_admin.initialize_app()
# and uses @firestore_fn.on_document_created at module level.
# ---------------------------------------------------------------------------
import sys
from unittest.mock import MagicMock, patch

_firestore_fn_stub = MagicMock()
# Make the decorator a passthrough so extract_kb_import stays unwrapped.
_firestore_fn_stub.on_document_created.return_value = lambda fn: fn

_firebase_admin_stub = MagicMock()
_firebase_admin_firestore_stub = MagicMock()
_firebase_functions_stub = MagicMock()
_firebase_functions_stub.firestore_fn = _firestore_fn_stub

for _name, _stub in [
    ("firebase_admin", _firebase_admin_stub),
    ("firebase_admin.firestore", _firebase_admin_firestore_stub),
    ("firebase_functions", _firebase_functions_stub),
    ("firebase_functions.firestore_fn", _firestore_fn_stub),
]:
    sys.modules.setdefault(_name, _stub)

# ---------------------------------------------------------------------------
# Standard imports (after stubs are in place)
# ---------------------------------------------------------------------------
import uuid
from datetime import datetime, timezone

import google.auth.credentials
import pytest
from google.cloud import firestore

# Import the function under test (stubs above prevent ImportError).
from functions.main import extract_kb_import  # noqa: E402
import functions.main as _fm  # module reference for patching module-level vars


# ---------------------------------------------------------------------------
# Credential stub — prevents any OAuth2 token refresh during tests.
# ---------------------------------------------------------------------------

class _StaticCredentials(google.auth.credentials.Credentials):
    """Always-valid static credentials for testing."""

    def __init__(self) -> None:
        super().__init__()
        self.token = "fake-extract-test-token"
        self.expiry = None  # Never expires

    def refresh(self, request: object) -> None:  # type: ignore[override]
        pass  # No-op — static token never needs refreshing


@pytest.fixture(autouse=True)
def _stub_gcp_auth(monkeypatch):
    """Patch google.auth.default so no OAuth2 calls are made."""
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    creds = _StaticCredentials()
    with patch("google.auth.default", return_value=(creds, "test-project")):
        yield


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_ID = "test-project"
_CLOUD_TASKS_QUEUE = (
    "projects/test-project/locations/europe-west1/queues/kb-pipeline"
)
_CLOUD_RUN_URL = "https://stilla-test.run.app"
_TASKS_SA_EMAIL = "tasks-sa@test.iam.gserviceaccount.com"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def import_id() -> str:
    """Unique import ID per test to prevent Firestore state pollution."""
    return f"test-extract-{uuid.uuid4().hex[:12]}"


@pytest.fixture()
def mock_event(import_id: str):
    """Fake firestore_fn.Event with params containing the importId."""
    event = MagicMock()
    event.params = {"importId": import_id}
    return event


def _seed_processing_doc(
    firestore_client: firestore.Client,
    import_id: str,
    gcs_path: str = "gs://test-bucket/imports/test.txt",
    source_format: str = "whatsapp_txt",
) -> None:
    """Pre-seed a kb_imports doc in processing state."""
    firestore_client.collection("kb_imports").document(import_id).set(
        {
            "status": "processing",
            "gcs_path": gcs_path,
            "source_format": source_format,
            "submitted_at": datetime.now(timezone.utc),
            "submitted_by": "midwife",
            "filename_hash": "abc123",
        }
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_stub_enqueues_cloud_task(
    firestore_client: firestore.Client,
    import_id: str,
    mock_event,
    monkeypatch,
):
    """Stub enqueues exactly one Cloud Tasks task with the correct URL and deadline.

    Why: the function's sole responsibility is to hand off work to Cloud Tasks.
    We verify: (1) exactly one task is created, (2) the task URL targets the
    internal pipeline endpoint for this import, (3) dispatch_deadline is 3600s
    so Cloud Run has the full hour to process large exports.
    """
    _seed_processing_doc(firestore_client, import_id)

    # Patch module-level vars — these are read at import time, not call time,
    # so monkeypatch.setenv alone would not affect them.
    monkeypatch.setattr(_fm, "CLOUD_TASKS_QUEUE", _CLOUD_TASKS_QUEUE)
    monkeypatch.setattr(_fm, "CLOUD_RUN_SERVICE_URL", _CLOUD_RUN_URL)
    monkeypatch.setattr(_fm, "TASKS_SA_EMAIL", _TASKS_SA_EMAIL)

    mock_tasks_client = MagicMock()
    with patch("functions.main.tasks_v2.CloudTasksClient", return_value=mock_tasks_client):
        extract_kb_import(mock_event)

    assert mock_tasks_client.create_task.call_count == 1

    task = mock_tasks_client.create_task.call_args[1]["task"]
    assert f"/internal/kb/process-import/{import_id}" in task.http_request.url
    assert task.dispatch_deadline.seconds == 3600


@pytest.mark.integration
def test_stub_idempotency_not_needed(
    import_id: str,
    mock_event,
    monkeypatch,
):
    """The stub does NOT check Firestore status before enqueuing.

    Idempotency is handled downstream by the /internal/kb/process-import
    endpoint, which uses a Firestore transaction to atomically claim the
    import document. The stub intentionally enqueues even when no Firestore
    document exists — the endpoint will skip the job if it was already
    processed or never existed.

    This is by design: keeping the stub stateless makes it simpler and
    eliminates a race condition where a doc might not yet be visible to the
    function when the event fires.
    """
    monkeypatch.setattr(_fm, "CLOUD_TASKS_QUEUE", _CLOUD_TASKS_QUEUE)
    monkeypatch.setattr(_fm, "CLOUD_RUN_SERVICE_URL", _CLOUD_RUN_URL)
    monkeypatch.setattr(_fm, "TASKS_SA_EMAIL", _TASKS_SA_EMAIL)

    mock_tasks_client = MagicMock()
    # No Firestore doc pre-seeded — the stub still enqueues the task.
    with patch("functions.main.tasks_v2.CloudTasksClient", return_value=mock_tasks_client):
        extract_kb_import(mock_event)

    assert mock_tasks_client.create_task.call_count == 1
