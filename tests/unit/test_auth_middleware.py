"""Tests for the JWT authentication middleware."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from api.middleware.auth_middleware import AuthMiddleware
from services.auth import create_access_token, init_auth_service


@pytest.fixture(autouse=True)
def _mock_settings(monkeypatch):
    """Provide test JWT settings."""
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-for-unit-tests")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("SESSION_TIMEOUT_SECONDS", "1800")
    monkeypatch.setenv("TOKEN_REFRESH_THRESHOLD_SECONDS", "300")
    import config.settings as settings_module

    settings_module._settings = None
    yield
    settings_module._settings = None


@pytest.fixture
def mock_pg():
    """Mock PostgresConnector for auth service."""
    pg = AsyncMock()
    init_auth_service(pg)
    return pg


@pytest.fixture
def test_app(mock_pg):
    """Create a test FastAPI app with auth middleware."""
    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/auth/login")
    async def login():
        return {"status": "login page"}

    @app.get("/docs")
    async def docs():
        return {"status": "docs"}

    @app.get("/protected")
    async def protected(request: Request):
        return {
            "username": request.state.username,
            "role": request.state.role,
            "tenant": request.state.tenant,
            "is_authenticated": request.state.is_authenticated,
        }

    return app


@pytest.fixture
def client(test_app):
    return TestClient(test_app)


class TestSkipPaths:
    """Tests for paths that skip authentication."""

    def test_health_skips_auth(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_auth_login_skips_auth(self, client):
        resp = client.get("/auth/login")
        assert resp.status_code == 200

    def test_docs_skips_auth(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200


class TestAuthRequired:
    """Tests for paths that require authentication."""

    def test_missing_authorization_header(self, client):
        resp = client.get("/protected")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Not authenticated"

    def test_invalid_token(self, client):
        resp = client.get(
            "/protected",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid or expired token"

    def test_valid_token_populates_state(self, client, mock_pg):
        # Mock blacklist check to return not-blacklisted
        mock_pg.fetchrow.return_value = None

        token = create_access_token("rajesh", "VENDOR", "TechNova")
        resp = client.get(
            "/protected",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "rajesh"
        assert data["role"] == "VENDOR"
        assert data["tenant"] == "TechNova"
        assert data["is_authenticated"] is True


class TestTokenRefresh:
    """Tests for automatic token refresh."""

    def test_near_expiry_token_gets_refresh_header(self, client, mock_pg):
        """Token about to expire -> X-New-Token header added."""
        mock_pg.fetchrow.return_value = None

        from jose import jwt

        from config.settings import get_settings

        settings = get_settings()

        # Create a token that expires in 60 seconds (within 300s threshold)
        claims = {
            "sub": "rajesh",
            "role": "VENDOR",
            "tenant": "TechNova",
            "exp": time.time() + 60,
            "iat": time.time() - 1740,
            "jti": "old-jti",
        }
        token = jwt.encode(claims, settings.jwt_secret_key, algorithm="HS256")

        resp = client.get(
            "/protected",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert "X-New-Token" in resp.headers
