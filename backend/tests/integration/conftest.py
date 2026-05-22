"""Shared fixtures for integration tests.

VCR configuration: cassettes use method+host matching so the cassette
remains valid across project-ID or model-name changes in the Vertex AI URI.
record_mode="none" prevents accidental real API calls — cassettes must be
pre-recorded before running integration tests.
"""
import os
from typing import Any
from unittest.mock import patch

import pytest
import google.auth.credentials
from google.cloud import firestore

_ADMIN_TOKEN = "integration-test-token"
_PROJECT_ID = "test-project"


class _StaticCredentials(google.auth.credentials.Credentials):
    """Always-valid credentials with a static token — for testing only.

    Prevents the vertexai SDK from calling oauth2.googleapis.com or the
    Cloud Resource Manager API to resolve project credentials.  The static
    token is used in Authorization headers; VCR cassettes match on method+host
    so the token value is irrelevant.
    """

    def __init__(self) -> None:
        super().__init__()
        self.token = "fake-integration-test-token"
        self.expiry = None  # None means "never expires"

    def refresh(self, request: object) -> None:  # type: ignore[override]
        pass  # Static token — nothing to refresh


@pytest.fixture(scope="module", autouse=True)
def vertexai_init() -> None:
    """Pre-initialise vertexai with fake credentials and the test project.

    This prevents the SDK from making OAuth2 token-refresh or Cloud Resource
    Manager gRPC calls during integration tests.  Must be module-scoped so it
    runs before any test in this package creates a GenerativeModel.
    """
    import vertexai  # type: ignore[import]

    vertexai.init(
        project="test-project",
        location="europe-west1",
        credentials=_StaticCredentials(),
        api_transport="rest",
    )


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
    """Capture every call to core.audit.write_event and return as a list.

    Why: integration tests must verify audit events without hitting real
    GCS/Cloud Logging. Patching at the source module intercepts any caller
    that uses ``core.audit.write_event(...)`` directly.
    """
    events: list[dict[str, Any]] = []

    def _capture(event_type: str, **kwargs: Any) -> None:
        events.append({"event_type": event_type, **kwargs})

    with patch("core.audit.write_event", side_effect=_capture):
        yield events


@pytest.fixture(scope="module")
def vcr_config():
    """Configure vcrpy for integration tests.

    match_on=[method, host]: broad enough to survive URI changes in Vertex AI
    endpoints (project ID, region, model name) without re-recording.
    record_mode=none: prevent real network calls; cassette must exist.
    """
    return {
        "match_on": ["method", "host"],
        "record_mode": "none",
        "decode_compressed_response": True,
    }
