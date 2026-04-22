"""JWT authentication middleware for VQMS.

Implemented as pure ASGI middleware (NOT BaseHTTPMiddleware).

Why pure ASGI?
    BaseHTTPMiddleware has a known Starlette design flaw: when
    `dispatch()` returns a Response directly (e.g. a 401 on auth
    failure), it short-circuits the middleware stack. Outer
    middleware — including CORSMiddleware — never runs, so the
    browser sees the 401 as a CORS error instead of an auth error.

    A pure ASGI middleware sends its response via the raw `send`
    callable. CORS is still outermost, so CORS headers always get
    wrapped around every response — 200, 401, or 5xx alike.

Behavior (unchanged from the BaseHTTPMiddleware version):
    - Decodes JWT from Authorization header.
    - Sets scope["state"] so downstream handlers can read
      `request.state.username`, `request.state.role`,
      `request.state.tenant`, `request.state.is_authenticated`.
    - Adds X-New-Token response header when the token is near
      expiry (auto-refresh).

Skip paths: /health, /auth/login, /docs, /openapi.json, /redoc, /webhooks/
"""

from __future__ import annotations

from typing import Any

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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


class AuthMiddleware:
    """Pure ASGI JWT authentication middleware.

    Short-circuits with 401 JSON on missing/invalid tokens without
    breaking the outer middleware stack. CORS headers remain intact
    on every response.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        # Pass lifespan / websocket scopes through untouched.
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method: str = scope["method"]
        path: str = scope["path"]

        # Defense-in-depth: CORS preflight (OPTIONS) never carries an
        # Authorization header. CORSMiddleware handles OPTIONS at the
        # outer layer; this guard protects against accidental reordering.
        if method == "OPTIONS":
            await self.app(scope, receive, send)
            return

        # Starlette's Request.state lazily creates scope["state"]
        # on first access. We set it up here so downstream routes
        # and tests can read request.state.* consistently.
        state: dict[str, Any] = scope.setdefault("state", {})

        if _should_skip_auth(path):
            state["username"] = None
            state["role"] = None
            state["tenant"] = None
            state["is_authenticated"] = False
            await self.app(scope, receive, send)
            return

        auth_header = _get_header(scope, b"authorization")
        if auth_header is None or not auth_header.startswith("Bearer "):
            await _send_json_401(send, "Not authenticated")
            return

        token = auth_header[7:]

        payload = await validate_token(token)
        if payload is None:
            await _send_json_401(send, "Invalid or expired token")
            return

        state["username"] = payload.sub
        state["role"] = payload.role
        state["tenant"] = payload.tenant
        state["is_authenticated"] = True

        # Decide on token refresh before calling downstream. The
        # refresh decision is a pure function of the JWT exp claim —
        # order relative to the handler doesn't change semantics.
        new_token = await refresh_token_if_expiring(payload)

        if new_token is None:
            await self.app(scope, receive, send)
            return

        # Wrap `send` so the X-New-Token header is injected into the
        # http.response.start message. This preserves the header
        # even if downstream raises and the framework sends its own
        # error response.
        async def send_with_refresh_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append(
                    (b"x-new-token", new_token.encode("latin-1"))
                )
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_refresh_header)


def _should_skip_auth(path: str) -> bool:
    """Check if the path should bypass authentication."""
    for skip_path in SKIP_PATHS:
        if path == skip_path or path.startswith(skip_path):
            return True
    return False


def _get_header(scope: Scope, name: bytes) -> str | None:
    """Return the first matching header value (case-insensitive) or None.

    ASGI headers are a list of (name_bytes, value_bytes) tuples.
    Names are always lowercase in ASGI scope.
    """
    for raw_name, raw_value in scope.get("headers", []):
        if raw_name == name:
            try:
                return raw_value.decode("latin-1")
            except UnicodeDecodeError:
                return None
    return None


async def _send_json_401(send: Send, detail: str) -> None:
    """Send a 401 JSON response via the raw ASGI `send` callable.

    We build the response bytes directly instead of using
    JSONResponse because we want to stay purely inside the ASGI
    protocol — no Starlette Response short-circuit semantics.
    """
    # Minimal, safe JSON — `detail` values are fixed literals in this
    # module so no escaping is needed. If detail ever becomes
    # dynamic, switch to json.dumps.
    body = f'{{"detail":"{detail}"}}'.encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("latin-1")),
            ],
        }
    )
    await send(
        {
            "type": "http.response.body",
            "body": body,
        }
    )
