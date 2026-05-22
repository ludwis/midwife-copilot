"""Tests for audit event writer (T016).

Why: Every knowledge-management event must be durably written to both
Cloud Logging and GCS JSONL. These tests encode the contract: correct
field serialization, ISO-8601 UTC timestamp, dual-write path, append
behavior on existing blobs, and graceful degradation when GCS is absent.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

import core.audit as audit_mod
from core.audit import write_event


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset module-level singletons between tests to prevent state leakage."""
    audit_mod._gcs_client = None
    audit_mod._cloud_logger = None
    yield
    audit_mod._gcs_client = None
    audit_mod._cloud_logger = None


@pytest.fixture()
def mock_blob():
    blob = MagicMock()
    blob.exists.return_value = False
    blob.download_as_text.return_value = ""
    return blob


@pytest.fixture()
def mock_bucket(mock_blob):
    bucket = MagicMock()
    bucket.blob.return_value = mock_blob
    return bucket


@pytest.fixture()
def mock_gcs(mock_bucket):
    client = MagicMock()
    client.bucket.return_value = mock_bucket
    return client


@pytest.fixture()
def mock_cloud_logger():
    return MagicMock()


# ---------------------------------------------------------------------------
# Field serialization
# ---------------------------------------------------------------------------


def test_write_event_jsonl_has_required_base_fields(mock_gcs, mock_blob, mock_cloud_logger):
    """write_event must produce a JSONL line with event_type, timestamp, actor, and extra fields."""
    with (
        patch("core.audit.storage.Client", return_value=mock_gcs),
        patch.object(audit_mod, "_cloud_logger", mock_cloud_logger),
        patch.dict(os.environ, {"AUDIT_BUCKET_NAME": "midwife-bot-audit-dev"}),
    ):
        write_event("kb_import_started", actor="midwife", import_id="imp_001")

    uploaded: str = mock_blob.upload_from_string.call_args[0][0]
    entry = json.loads(uploaded.strip())

    assert entry["event_type"] == "kb_import_started"
    assert entry["actor"] == "midwife"
    assert entry["import_id"] == "imp_001"
    assert "timestamp" in entry


def test_write_event_timestamp_is_iso8601_utc(mock_gcs, mock_blob, mock_cloud_logger):
    """Timestamp must be ISO-8601 with millisecond precision ending in Z."""
    with (
        patch("core.audit.storage.Client", return_value=mock_gcs),
        patch.object(audit_mod, "_cloud_logger", mock_cloud_logger),
        patch.dict(os.environ, {"AUDIT_BUCKET_NAME": "midwife-bot-audit-dev"}),
    ):
        write_event("kb_chunk_staged", actor="midwife", chunk_id="chk_001")

    uploaded: str = mock_blob.upload_from_string.call_args[0][0]
    ts = json.loads(uploaded.strip())["timestamp"]

    assert ts.endswith("Z"), f"timestamp must end with Z, got: {ts}"
    # Must be parseable as UTC datetime
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# Append behavior
# ---------------------------------------------------------------------------


def test_write_event_appends_after_existing_content(mock_gcs, mock_blob, mock_cloud_logger):
    """When the blob already exists, the new line must be appended after existing content."""
    existing = '{"event_type":"kb_import_started","timestamp":"2026-05-01T00:00:00.000Z","actor":"midwife"}\n'
    mock_blob.exists.return_value = True
    mock_blob.download_as_text.return_value = existing

    with (
        patch("core.audit.storage.Client", return_value=mock_gcs),
        patch.object(audit_mod, "_cloud_logger", mock_cloud_logger),
        patch.dict(os.environ, {"AUDIT_BUCKET_NAME": "midwife-bot-audit-dev"}),
    ):
        write_event("kb_chunk_approved", actor="midwife", chunk_id="chk_002")

    uploaded: str = mock_blob.upload_from_string.call_args[0][0]
    lines = [ln for ln in uploaded.splitlines() if ln]
    assert len(lines) == 2
    assert json.loads(lines[0])["event_type"] == "kb_import_started"
    assert json.loads(lines[1])["event_type"] == "kb_chunk_approved"


def test_write_event_gcs_blob_path_uses_utc_date(mock_gcs, mock_blob, mock_cloud_logger):
    """GCS blob path must follow {YYYY}/{MM}/{DD}/audit.jsonl pattern."""
    with (
        patch("core.audit.storage.Client", return_value=mock_gcs),
        patch.object(audit_mod, "_cloud_logger", mock_cloud_logger),
        patch.dict(os.environ, {"AUDIT_BUCKET_NAME": "midwife-bot-audit-dev"}),
    ):
        write_event("kb_chunk_discarded", actor="midwife", chunk_id="chk_003")

    bucket_call = mock_gcs.bucket.call_args[0][0]
    blob_call = mock_gcs.bucket.return_value.blob.call_args[0][0]

    assert bucket_call == "midwife-bot-audit-dev"
    # Path must match YYYY/MM/DD/audit.jsonl
    import re
    assert re.match(r"^\d{4}/\d{2}/\d{2}/audit\.jsonl$", blob_call), f"Unexpected blob path: {blob_call}"


# ---------------------------------------------------------------------------
# Cloud Logging dual-write
# ---------------------------------------------------------------------------


def test_write_event_sends_structured_entry_to_cloud_logging(mock_gcs, mock_blob, mock_cloud_logger):
    """write_event must call log_struct on the Cloud Logging logger with the event dict."""
    with (
        patch("core.audit.storage.Client", return_value=mock_gcs),
        patch.object(audit_mod, "_cloud_logger", mock_cloud_logger),
        patch.dict(os.environ, {"AUDIT_BUCKET_NAME": "midwife-bot-audit-dev"}),
    ):
        write_event("kb_chunk_promoted", actor="midwife", chunk_id="chk_004")

    mock_cloud_logger.log_struct.assert_called_once()
    logged = mock_cloud_logger.log_struct.call_args[0][0]
    assert logged["event_type"] == "kb_chunk_promoted"
    assert logged["actor"] == "midwife"


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


def test_write_event_no_bucket_skips_gcs_without_error(mock_cloud_logger):
    """When AUDIT_BUCKET_NAME is unset, GCS write is silently skipped."""
    with (
        patch.object(audit_mod, "_cloud_logger", mock_cloud_logger),
        patch.dict(os.environ, {}, clear=True),
    ):
        os.environ.pop("AUDIT_BUCKET_NAME", None)
        write_event("kb_import_started", actor="midwife", import_id="imp_no_gcs")

    # Cloud Logging still receives the event
    mock_cloud_logger.log_struct.assert_called_once()


def test_write_event_gcs_error_does_not_propagate(mock_gcs, mock_blob, mock_cloud_logger):
    """GCS upload failures must be caught and logged — never raised to callers."""
    mock_blob.upload_from_string.side_effect = Exception("network timeout")

    with (
        patch("core.audit.storage.Client", return_value=mock_gcs),
        patch.object(audit_mod, "_cloud_logger", mock_cloud_logger),
        patch.dict(os.environ, {"AUDIT_BUCKET_NAME": "midwife-bot-audit-dev"}),
    ):
        write_event("kb_chunk_staged", actor="midwife", chunk_id="chk_fail")
        # Must complete without raising


def test_write_event_cloud_logging_error_does_not_propagate(mock_gcs, mock_blob, mock_cloud_logger):
    """Cloud Logging failures must be caught — the GCS write should still proceed."""
    mock_cloud_logger.log_struct.side_effect = Exception("logging service unavailable")

    with (
        patch("core.audit.storage.Client", return_value=mock_gcs),
        patch.object(audit_mod, "_cloud_logger", mock_cloud_logger),
        patch.dict(os.environ, {"AUDIT_BUCKET_NAME": "midwife-bot-audit-dev"}),
    ):
        write_event("kb_import_started", actor="midwife", import_id="imp_logging_fail")

    # GCS write still happened despite Cloud Logging failure
    mock_blob.upload_from_string.assert_called_once()
