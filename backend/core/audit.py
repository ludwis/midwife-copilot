"""Audit event writer: dual-write to Cloud Logging + GCS JSONL.

Every knowledge-management event (extraction, staging, promotion, discard)
is written here to maintain an append-only audit trail per FR-007/FR-008.

GCS path: gs://{AUDIT_BUCKET_NAME}/{YYYY}/{MM}/{DD}/audit.jsonl

Env vars:
    AUDIT_BUCKET_NAME  — GCS bucket name (e.g. midwife-bot-audit-dev).
                         If absent, GCS writes are skipped without error.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from google.cloud import logging as cloud_logging
from google.cloud import storage

logger = logging.getLogger(__name__)

_LOGGER_NAME = "stilla-audit"

# Module-level singletons — populated on first call, never replaced.
_gcs_client: storage.Client | None = None
_cloud_logger: cloud_logging.logger.Logger | None = None


def _get_gcs_client() -> storage.Client | None:
    """Return module-level GCS client; initialize on first call when bucket is configured."""
    global _gcs_client
    if _gcs_client is None and os.environ.get("AUDIT_BUCKET_NAME"):
        _gcs_client = storage.Client()
    return _gcs_client


def _get_cloud_logger() -> cloud_logging.logger.Logger | None:
    """Return module-level Cloud Logging logger; initialize on first call."""
    global _cloud_logger
    if _cloud_logger is None:
        try:
            client = cloud_logging.Client()
            _cloud_logger = client.logger(_LOGGER_NAME)
        except Exception:  # noqa: BLE001
            logger.debug("Cloud Logging unavailable; structured log skipped.")
    return _cloud_logger


def write_event(event_type: str, actor: str, **fields: object) -> None:
    """Serialize and dual-write an audit event to Cloud Logging and GCS JSONL.

    Args:
        event_type: Audit event name (e.g. "kb_import_started").
        actor:      Identity of the operator triggering the event.
        **fields:   Additional structured fields for the event.
    """
    now = datetime.now(timezone.utc)
    entry: dict[str, object] = {
        "event_type": event_type,
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z",
        "actor": actor,
        **fields,
    }
    line = json.dumps(entry, ensure_ascii=False)

    # 1 — Cloud Logging structured entry
    cloud_log = _get_cloud_logger()
    if cloud_log is not None:
        try:
            cloud_log.log_struct(entry)
        except Exception:  # noqa: BLE001
            logger.warning("Cloud Logging write failed for event_type=%s", event_type)

    # 2 — GCS JSONL append
    bucket_name = os.environ.get("AUDIT_BUCKET_NAME", "")
    if not bucket_name:
        return

    gcs = _get_gcs_client()
    if gcs is None:
        return

    blob_path = f"{now.year}/{now.month:02d}/{now.day:02d}/audit.jsonl"
    try:
        bucket = gcs.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        existing = blob.download_as_text(encoding="utf-8") if blob.exists() else ""
        blob.upload_from_string(
            existing + line + "\n",
            content_type="application/x-ndjson",
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "GCS audit write failed: bucket=%s path=%s event_type=%s",
            bucket_name,
            blob_path,
            event_type,
        )
