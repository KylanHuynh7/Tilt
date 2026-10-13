"""Admin guard for endpoints that do expensive work (data refreshes, forced sims).

They are disabled unless the ADMIN_TOKEN environment variable is set, and then
require a matching `X-Admin-Token` header. Production (Cloud Run) leaves it
unset: the nightly deploy refreshes data, so nothing needs these publicly, and
leaving them open would let anyone burn CPU against the $1/month budget.

    ADMIN_TOKEN=secret uv run uvicorn app.main:app
    curl -X POST -H 'X-Admin-Token: secret' localhost:8000/admin/refresh
"""

from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException


def is_admin(token: str | None) -> bool:
    expected = os.environ.get("ADMIN_TOKEN")
    return bool(expected) and token is not None and hmac.compare_digest(token, expected)


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    if not os.environ.get("ADMIN_TOKEN"):
        raise HTTPException(403, "admin endpoints are disabled on this deployment (data refreshes run nightly)")
    if not is_admin(x_admin_token):
        raise HTTPException(401, "missing or invalid X-Admin-Token")
