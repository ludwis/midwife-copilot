"""X-Admin-Token authentication dependency.

T015 provides the authoritative implementation; this file is created here
so that main.py can import it without circular issues. T015 will verify
and may extend this module.
"""
import os
import secrets

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

_header_scheme = APIKeyHeader(name="X-Admin-Token", auto_error=False)


async def require_admin_token(
    x_admin_token: str | None = Security(_header_scheme),
) -> None:
    """Raise HTTP 401 when the X-Admin-Token header is absent or incorrect."""
    expected = os.environ.get("ADMIN_TOKEN", "")
    if not x_admin_token or not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")
