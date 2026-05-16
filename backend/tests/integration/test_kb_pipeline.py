"""Acceptance test for the golden dataset end-to-end pipeline (T038).

TDD: Written before cassette recording (T039–T042). Tests will be RED until
the full pipeline runs against the golden VCR cassette.

Contract encoded by this test:
  1. Upload golden_whatsapp_export.txt via POST /api/admin/kb/imports
  2. Full pipeline runs: parse → PII strip → Gemini extract (VCR replay) → stage
  3. Staged chunk count equals golden_expected_chunks.json count
  4. Every expected question from golden_expected_chunks.json is present in staged chunks
  5. No digit sequence >6 consecutive digits appears in any staged chunk question or answer

Requirements to run:
  FIRESTORE_EMULATOR_HOST=localhost:8080  (Firestore emulator must be running)
  VCR cassette at cassettes/test_kb_pipeline/test_golden_dataset.yaml
    (replays Gemini generateContent HTTPS response; record_mode=none)
"""
from __future__ import annotations

import json
import os
import re
import time
from io import BytesIO
from pathlib import Path
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
_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"

# Regex for PII check: no digit sequence longer than 6 digits must appear
# in any staged chunk's question or answer after PII stripping.
_LONG_DIGIT_RE = re.compile(r"\d{7,}")


# ---------------------------------------------------------------------------
# Fixtures (same pattern as test_import_flow.py)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def firestore_client():
    """Firestore client pointed at the local emulator."""
    host = os.environ.get("FIRESTORE_EMULATOR_HOST", "localhost:8080")
    os.environ["FIRESTORE_EMULATOR_HOST"] = host
    client = firestore.Client(project=_PROJECT_ID)
    yield client


@pytest.fixture()
def captured_audit_events() -> list[dict[str, Any]]:
    """Capture core.audit.write_event calls without hitting GCS/Cloud Logging."""
    events: list[dict[str, Any]] = []

    def _capture(event_type: str, **kwargs: Any) -> None:
        events.append({"event_type": event_type, **kwargs})

    with patch("core.audit.write_event", side_effect=_capture):
        yield events


@pytest.fixture()
def admin_client(monkeypatch, captured_audit_events):  # noqa: ARG001
    """FastAPI TestClient with admin token and emulator env vars set."""
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
    """Poll GET /api/admin/kb/imports/{import_id} until terminal status."""
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
def test_golden_dataset(
    admin_client: TestClient,
    firestore_client: firestore.Client,
    captured_audit_events: list[dict[str, Any]],  # noqa: ARG001 — activates audit patch
):
    """E2E pipeline: golden WhatsApp export → staged chunks match golden_expected_chunks.json.

    Why each assertion matters:
    - chunk count == expected count: pipeline extracted all Q&A pairs from the cassette
    - every expected question present: content fidelity end-to-end (parse→PII strip→Gemini→stage)
    - no digit sequence >6 digits: GDPR/RODO PII stripping compliance requirement (SC-003)
    """
    golden_export = (_FIXTURE_DIR / "golden_whatsapp_export.txt").read_text(encoding="utf-8")
    golden_expected: list[dict[str, str]] = json.loads(
        (_FIXTURE_DIR / "golden_expected_chunks.json").read_text(encoding="utf-8")
    )

    # ── POST: upload the golden WhatsApp export ──────────────────────────────
    resp = admin_client.post(
        "/api/admin/kb/imports",
        headers={"X-Admin-Token": _ADMIN_TOKEN},
        files={
            "file": (
                "golden_export.txt",
                BytesIO(golden_export.encode("utf-8")),
                "text/plain",
            )
        },
        data={"source_format": "whatsapp_txt"},
    )
    assert resp.status_code == 202, (
        f"Expected 202 Accepted, got {resp.status_code}: {resp.text}"
    )
    import_id: str = resp.json()["import_id"]

    # ── POLL: wait for terminal status ────────────────────────────────────────
    final = _poll_import(admin_client, import_id)
    assert final["status"] == "completed", (
        f"Pipeline ended with status={final['status']!r}; "
        f"error_message={final.get('error_message')!r}"
    )
    assert final.get("chunks_extracted", 0) == len(golden_expected), (
        f"chunks_extracted={final.get('chunks_extracted', 0)!r} "
        f"does not match golden expected count={len(golden_expected)}"
    )

    # ── FIRESTORE: verify staged chunks ──────────────────────────────────────
    staged_chunks = list(
        firestore_client.collection("kb_chunks")
        .where("import_id", "==", import_id)
        .where("status", "==", "staged")
        .stream()
    )
    assert len(staged_chunks) == len(golden_expected), (
        f"Firestore has {len(staged_chunks)} staged chunks, "
        f"expected {len(golden_expected)}"
    )

    chunk_dicts = [c.to_dict() for c in staged_chunks]

    # ── PII CHECK: no digit sequence >6 digits in any question or answer ─────
    for chunk in chunk_dicts:
        combined = chunk["question"] + " " + chunk["answer"]
        assert not _LONG_DIGIT_RE.search(combined), (
            f"Digit sequence >6 digits (PII leak) found in chunk: {combined[:120]!r}"
        )

    # ── CONTENT: every expected question is present in staged chunks ──────────
    staged_questions = {c["question"] for c in chunk_dicts}
    for expected in golden_expected:
        assert expected["question"] in staged_questions, (
            f"Expected question not found in staged chunks: {expected['question']!r}\n"
            f"Staged questions: {staged_questions!r}"
        )
