"""OIDC token validation for internal Cloud Workflow routes."""
import os

import google.auth.transport.requests
import google.oauth2.id_token
from fastapi import HTTPException, Request


def require_tasks_oidc(request: Request) -> None:
    """Validate the Google-signed OIDC JWT issued by Cloud Workflows."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=403, detail="Missing OIDC token")
    token = auth_header[len("Bearer "):]

    # Read at request time so Cloud Run env var updates take effect without
    # requiring a redeployment.
    audience = os.environ.get("CLOUD_RUN_SERVICE_URL", "")
    expected_email = os.environ.get("WORKFLOW_SA_EMAIL", "")

    try:
        idinfo = google.oauth2.id_token.verify_oauth2_token(
            token,
            google.auth.transport.requests.Request(),
            audience=audience,
        )
    except Exception as exc:
        raise HTTPException(status_code=403, detail=f"Invalid OIDC token: {exc}") from exc

    import logging
    logging.getLogger(__name__).info("OIDC token email: %s", idinfo.get("email"))
    if expected_email and idinfo.get("email") != expected_email:
        raise HTTPException(
            status_code=403,
            detail=f"Token email mismatch: got '{idinfo.get('email')}', expected '{expected_email}'",
        )
