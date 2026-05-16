"""Tests for X-Admin-Token authentication dependency (T015).

Why: The admin API must reject unauthenticated requests at the middleware
level before any business logic runs. These tests encode the contract:
absent or wrong token → 401; correct token → request proceeds.
"""
import os
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import require_admin_token


@pytest.fixture()
def app_with_auth():
    """Minimal FastAPI app with a single route protected by require_admin_token."""
    test_app = FastAPI()

    @test_app.get("/protected", dependencies=[])
    async def protected(token=__import__("fastapi").Depends(require_admin_token)):  # noqa: ARG001
        return {"ok": True}

    return test_app


@pytest.fixture()
def client(app_with_auth):
    return TestClient(app_with_auth, raise_server_exceptions=True)


def test_missing_token_returns_401(client):
    """Requests with no X-Admin-Token header must be rejected."""
    with patch.dict(os.environ, {"ADMIN_TOKEN": "secret"}):
        resp = client.get("/protected")
    assert resp.status_code == 401


def test_wrong_token_returns_401(client):
    """Requests with an incorrect X-Admin-Token must be rejected."""
    with patch.dict(os.environ, {"ADMIN_TOKEN": "secret"}):
        resp = client.get("/protected", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 401


def test_correct_token_passes(client):
    """Requests with the correct X-Admin-Token must be allowed through."""
    with patch.dict(os.environ, {"ADMIN_TOKEN": "secret"}):
        resp = client.get("/protected", headers={"X-Admin-Token": "secret"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_empty_env_token_rejects_all(client):
    """When ADMIN_TOKEN is unset, every request is rejected (fail-secure)."""
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("ADMIN_TOKEN", None)
        resp = client.get("/protected", headers={"X-Admin-Token": ""})
    assert resp.status_code == 401
