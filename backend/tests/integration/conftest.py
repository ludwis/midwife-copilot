"""Shared fixtures for integration tests.

VCR configuration: cassettes use method+host matching so the cassette
remains valid across project-ID or model-name changes in the Vertex AI URI.
record_mode="none" prevents accidental real API calls — cassettes must be
pre-recorded before running integration tests.
"""
import pytest


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
