"""Integration tests for the Firebase Cloud Function extract_kb_import.

Tests call the handler directly (no Firebase runtime required). Firebase
packages (firebase_admin, firebase_functions) are stubbed in sys.modules
before import so the test suite runs without installing them.

The Firestore emulator is used for real document read/write assertions.
GCS is mocked to return the golden WhatsApp export bytes.
Gemini calls are replayed via VCR cassettes.

Requirements to run:
  FIRESTORE_EMULATOR_HOST=localhost:8080  (Firestore emulator must be running)
  VCR cassettes in cassettes/test_extract_function/

Fixtures `firestore_client` and `captured_audit_events` come from conftest.py.
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
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import google.auth.credentials
import pytest
from google.cloud import firestore

# Import the function under test (stubs above prevent ImportError).
from functions.main import extract_kb_import  # noqa: E402


# ---------------------------------------------------------------------------
# Credential stub — prevents genai.Client(vertexai=True) from refreshing
# OAuth2 tokens via oauth2.googleapis.com, which VCR would block.
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
    """Patch google.auth.default so genai.Client never makes OAuth2 calls.

    Also sets GOOGLE_CLOUD_PROJECT and GCP_PROJECT_ID so that both the
    staging module's lazy firestore.Client() and the extractor use the same
    test-project namespace as the firestore_client fixture.
    """
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    creds = _StaticCredentials()
    with patch("google.auth.default", return_value=(creds, "test-project")):
        yield

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_ID = "test-project"

_PII_PATTERNS = [
    re.compile(r"\+?\d[\d\s\-]{7,}\d"),
    re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"),
    re.compile(r"\b\d{11}\b"),
]

_GOLDEN_WHATSAPP_EXPORT = """\
[15/05/2026, 09:00:00] - Anna Kowalska: Czy ból w okolicy miednicy jest normalny w 36. tygodniu?
[15/05/2026, 09:01:30] - Położna: Tak, ból miednicy w 36. tygodniu jest typowy. Dziecko opuszcza się ku dołowi.
[15/05/2026, 09:01:45] - Położna: Mój numer to +48 601 234 567 jeśli będziesz potrzebować pomocy.
[15/05/2026, 09:02:00] - Anna Kowalska: Dziękuję bardzo. Napiszę na anna.kowalska@gmail.com
Messages and calls are end-to-end encrypted. No one outside of this chat, not even WhatsApp, can read or listen to them.
"""

_ONLY_SYSTEM_MESSAGES = """\
[15/05/2026, 09:00:00] - Messages and calls are end-to-end encrypted.
Messages and calls are end-to-end encrypted. No one outside of this chat, not even WhatsApp, can read or listen to them.
"""


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


@pytest.fixture()
def mock_gcs_download(monkeypatch, import_id: str):
    """Patch storage.Client so GCS download returns the golden export bytes."""
    mock_blob = MagicMock()
    mock_blob.download_as_bytes.return_value = _GOLDEN_WHATSAPP_EXPORT.encode("utf-8")
    mock_client = MagicMock()
    mock_client.bucket.return_value.blob.return_value = mock_blob

    import functions.main as _fm  # already imported; get the module reference
    monkeypatch.setattr(_fm.storage, "Client", lambda: mock_client)


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


@pytest.mark.vcr
@pytest.mark.integration
def test_extract_function_success(
    firestore_client: firestore.Client,
    import_id: str,
    mock_event,
    mock_gcs_download,
    captured_audit_events: list[dict[str, Any]],
):
    """Function runs the full pipeline and transitions the doc to status=completed."""
    _seed_processing_doc(firestore_client, import_id)

    with patch("functions.main.admin_firestore") as mock_afs:
        mock_afs.client.return_value = firestore_client
        extract_kb_import(mock_event)

    doc = firestore_client.collection("kb_imports").document(import_id).get()
    assert doc.exists
    data = doc.to_dict()
    assert data["status"] == "completed", (
        f"Expected status=completed, got {data['status']!r}; "
        f"error_message={data.get('error_message')!r}"
    )
    assert data.get("chunks_extracted", 0) > 0, "At least one Q&A pair must be extracted"
    assert "completed_at" in data


@pytest.mark.vcr
@pytest.mark.integration
def test_extract_function_creates_chunks(
    firestore_client: firestore.Client,
    import_id: str,
    mock_event,
    mock_gcs_download,
    captured_audit_events: list[dict[str, Any]],
):
    """kb_chunks docs are created with status=staged and no PII in question/answer."""
    _seed_processing_doc(firestore_client, import_id)

    with patch("functions.main.admin_firestore") as mock_afs:
        mock_afs.client.return_value = firestore_client
        extract_kb_import(mock_event)

    staged_chunks = list(
        firestore_client.collection("kb_chunks")
        .where("import_id", "==", import_id)
        .where("status", "==", "staged")
        .stream()
    )
    assert len(staged_chunks) > 0, f"Expected staged kb_chunks for import_id={import_id!r}"

    for chunk_doc in staged_chunks:
        chunk = chunk_doc.to_dict()
        assert chunk.get("question"), f"chunk {chunk_doc.id}: question must be non-empty"
        assert chunk.get("answer"), f"chunk {chunk_doc.id}: answer must be non-empty"
        assert "content_hash" in chunk, f"chunk {chunk_doc.id}: content_hash must be set"
        assert chunk.get("status") == "staged"

        combined = chunk["question"] + " " + chunk["answer"]
        for pattern in _PII_PATTERNS:
            assert not pattern.search(combined), (
                f"PII pattern {pattern.pattern!r} found in chunk {chunk_doc.id}: "
                f"{combined[:120]!r}"
            )


@pytest.mark.vcr
@pytest.mark.integration
def test_extract_function_emits_audit_events(
    firestore_client: firestore.Client,
    import_id: str,
    mock_event,
    mock_gcs_download,
    captured_audit_events: list[dict[str, Any]],
):
    """Function emits kb_import_completed and kb_chunk_staged audit events."""
    _seed_processing_doc(firestore_client, import_id)

    with patch("functions.main.admin_firestore") as mock_afs:
        mock_afs.client.return_value = firestore_client
        extract_kb_import(mock_event)

    completed_events = [e for e in captured_audit_events if e["event_type"] == "kb_import_completed"]
    assert len(completed_events) == 1, (
        f"Expected 1 kb_import_completed event, got {len(completed_events)}"
    )
    assert completed_events[0]["import_id"] == import_id
    assert completed_events[0]["status"] == "completed"

    staged_events = [e for e in captured_audit_events if e["event_type"] == "kb_chunk_staged"]
    assert len(staged_events) > 0, "Expected at least one kb_chunk_staged audit event"
    for evt in staged_events:
        assert "chunk_id" in evt, "kb_chunk_staged event must include chunk_id"
        assert evt["import_id"] == import_id
        assert "content_hash" in evt, "kb_chunk_staged event must include content_hash"


@pytest.mark.integration
def test_extract_function_idempotency(
    firestore_client: firestore.Client,
    import_id: str,
    mock_event,
    captured_audit_events: list[dict[str, Any]],
):
    """Function skips processing if doc status is already completed."""
    # Pre-seed with completed status.
    firestore_client.collection("kb_imports").document(import_id).set(
        {
            "status": "completed",
            "gcs_path": "gs://test-bucket/test.txt",
            "source_format": "whatsapp_txt",
            "submitted_at": datetime.now(timezone.utc),
            "completed_at": datetime.now(timezone.utc),
            "chunks_extracted": 1,
            "chunks_flagged_duplicate": 0,
        }
    )

    with patch("functions.main.admin_firestore") as mock_afs:
        mock_afs.client.return_value = firestore_client
        extract_kb_import(mock_event)

    # Doc must be unchanged.
    doc = firestore_client.collection("kb_imports").document(import_id).get()
    assert doc.get("status") == "completed"
    # No audit events should have been emitted (function returned early).
    assert len(captured_audit_events) == 0, (
        f"No audit events expected for idempotent call; got {captured_audit_events}"
    )


@pytest.mark.integration
def test_extract_function_no_pairs(
    firestore_client: firestore.Client,
    import_id: str,
    mock_event,
    captured_audit_events: list[dict[str, Any]],
):
    """Function transitions to no_pairs_found when extract_qa_pairs returns []."""
    _seed_processing_doc(firestore_client, import_id)

    # Mock GCS to return content, mock extractor to return no pairs.
    mock_blob = MagicMock()
    mock_blob.download_as_bytes.return_value = _ONLY_SYSTEM_MESSAGES.encode("utf-8")
    mock_client = MagicMock()
    mock_client.bucket.return_value.blob.return_value = mock_blob

    import functions.main as _fm

    with patch("functions.main.admin_firestore") as mock_afs, \
         patch.object(_fm.storage, "Client", lambda: mock_client), \
         patch("functions.main.extract_qa_pairs", return_value=[]):
        mock_afs.client.return_value = firestore_client
        extract_kb_import(mock_event)

    doc = firestore_client.collection("kb_imports").document(import_id).get()
    assert doc.get("status") == "no_pairs_found", (
        f"Expected no_pairs_found, got {doc.get('status')!r}"
    )

    completed_events = [e for e in captured_audit_events if e["event_type"] == "kb_import_completed"]
    assert len(completed_events) == 1
    assert completed_events[0]["status"] == "no_pairs_found"
