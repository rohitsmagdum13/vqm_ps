"""Module: app/middleware.py

Middleware registration for the VQMS FastAPI application.

Registers CORS middleware, auth middleware, and security headers.
"""

from __future__ import annotations

import secrets

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from api.middleware.auth_middleware import AuthMiddleware


def register_middleware(application: FastAPI) -> None:
    """Register all middleware on the FastAPI application.

    Middleware execution order: last registered runs FIRST on requests.
    So register AuthMiddleware first, CORSMiddleware second.
    Request flow: CORSMiddleware (handles OPTIONS preflight) -> AuthMiddleware -> route handler.
    """
    application.add_middleware(AuthMiddleware)

    application.add_middleware(
        CORSMiddleware,
        # Dev mode: allow all localhost origins (Angular may pick random ports)
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-New-Token"],
    )

    @application.middleware("http")
    async def add_security_headers(request: Request, call_next):
        """Add security headers to every HTTP response."""
        response = await call_next(request)

        # Skip CSP for Swagger UI paths — Swagger loads scripts from
        # a CDN (cdn.jsdelivr.net) and uses inline JS to render the
        # interactive docs. Our strict CSP blocks both of these,
        # causing a blank white screen. API endpoints still get
        # full CSP protection.
        docs_paths = ("/docs", "/redoc", "/openapi.json")
        is_docs_page = request.url.path in docs_paths

        if not is_docs_page:
            # CSP: Only allow resources from our own domain.
            # Nonce-based script policy blocks injected scripts.
            nonce = secrets.token_urlsafe(16)
            response.headers["Content-Security-Policy"] = (
                f"default-src 'self'; "
                f"script-src 'self' 'nonce-{nonce}'; "
                f"style-src 'self' 'unsafe-inline'; "
                f"img-src 'self' data:; "
                f"connect-src 'self'; "
                f"font-src 'self'; "
                f"child-src 'none'; "
                f"frame-ancestors 'none'"
            )

        # Hide server identity (default is "uvicorn")
        response.headers["Server"] = "hidden"

        # Prevent browser from guessing file types
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Legacy XSS filter for older browsers
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Prevent our app from being embedded in iframes (clickjacking)
        response.headers["X-Frame-Options"] = "DENY"

        # Force HTTPS for 1 year (only effective in production behind TLS)
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )

        # Don't leak URLs when navigating away from our site
        response.headers["Referrer-Policy"] = "no-referrer"

        # Restrict browser APIs we don't use
        response.headers["Permissions-Policy"] = (
            "geolocation=(), camera=(), microphone=()"
        )

        # Never cache API responses (sensitive vendor/email data)
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, proxy-revalidate"
        )
        response.headers["Pragma"] = "no-cache"

        return response
