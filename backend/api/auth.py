"""Authentication dependencies for the Stilla admin API.

Two strategies are provided:
  - require_firebase_token  — verifies a Firebase ID token from the
                              Authorization: Bearer header (used by the
                              frontend / end-user facing routes).
  - require_admin_token     — legacy X-Admin-Token static secret (kept as
                              a fallback for server-to-server scripts).
"""
from __future__ import annotations

import logging
import os
import secrets

import firebase_admin.auth
from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Firebase ID-token auth (frontend users)
# ---------------------------------------------------------------------------

_bearer_scheme = HTTPBearer(auto_error=False)


async def require_firebase_token(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
) -> firebase_admin.auth.UserRecord:
    """Verify the Firebase ID token supplied as 'Authorization: Bearer <token>'.

    Returns the decoded token dict on success.
    Raises HTTP 401 on missing / invalid tokens.
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    try:
        decoded = firebase_admin.auth.verify_id_token(credentials.credentials)
    except firebase_admin.auth.ExpiredIdTokenError:
        raise HTTPException(status_code=401, detail="Token expired")
    except firebase_admin.auth.InvalidIdTokenError as exc:
        logger.warning("Invalid Firebase ID token: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Firebase token verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Token verification failed")

    return decoded


# ---------------------------------------------------------------------------
# Legacy X-Admin-Token auth (server-to-server scripts / CLI)
# ---------------------------------------------------------------------------

_header_scheme = APIKeyHeader(name="X-Admin-Token", auto_error=False)


async def require_admin_token(
    x_admin_token: str | None = Security(_header_scheme),
) -> None:
    """Raise HTTP 401 when the X-Admin-Token header is absent or incorrect."""
    expected = os.environ.get("ADMIN_TOKEN", "")
    if not x_admin_token or not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")
