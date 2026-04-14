"""JWT authentication middleware for VQMS.

Intercepts all incoming requests, decodes the JWT from the
Authorization header, and sets user context on request.state.
Also handles automatic token refresh when the JWT is about
to expire (adds X-New-Token response header).

Skip paths: /health, /auth/login, /docs, /openapi.json, /webhooks/
"""

from __future__ import annotations

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from services.auth import refresh_token_if_expiring, validate_token

logger = structlog.get_logger(__name__)

SKIP_PATHS: tuple[str, ...] = (
    "/health",
    "/auth/login",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/webhooks/",
)


class AuthMiddleware(BaseHTTPMiddleware):
    """JWT authentication and user context middleware."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        path = request.url.path
        if _should_skip_auth(path):
            request.state.username = None
            request.state.role = None
            request.state.tenant = None
            request.state.is_authenticated = False
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Not authenticated"},
            )

        token = auth_header[7:]

        payload = await validate_token(token)
        if payload is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token"},
            )

        request.state.username = payload.sub
        request.state.role = payload.role
        request.state.tenant = payload.tenant
        request.state.is_authenticated = True

        response = await call_next(request)

        new_token = await refresh_token_if_expiring(payload)
        if new_token is not None:
            response.headers["X-New-Token"] = new_token

        return response


def _should_skip_auth(path: str) -> bool:
    """Check if the path should bypass authentication."""
    for skip_path in SKIP_PATHS:
        if path == skip_path or path.startswith(skip_path):
            return True
    return False
