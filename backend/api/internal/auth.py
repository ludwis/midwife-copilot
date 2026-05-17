"""OIDC token validation for internal Cloud Tasks routes."""
import os

import google.auth.transport.requests
import google.oauth2.id_token
from fastapi import HTTPException, Request

CLOUD_RUN_SERVICE_URL = os.environ.get("CLOUD_RUN_SERVICE_URL", "")
TASKS_SA_EMAIL = os.environ.get("TASKS_SA_EMAIL", "")


def require_tasks_oidc(request: Request) -> None:
    """Validate the Google-signed OIDC JWT issued by Cloud Tasks."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=403, detail="Missing OIDC token")
    token = auth_header[len("Bearer "):]
    try:
        idinfo = google.oauth2.id_token.verify_oauth2_token(
            token,
            google.auth.transport.requests.Request(),
            audience=CLOUD_RUN_SERVICE_URL,
        )
    except Exception as exc:
        raise HTTPException(status_code=403, detail=f"Invalid OIDC token: {exc}") from exc
    if idinfo.get("email") != TASKS_SA_EMAIL:
        raise HTTPException(status_code=403, detail="Token email does not match expected SA")
