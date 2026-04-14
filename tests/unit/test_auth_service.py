"""Tests for the authentication service."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

from models.auth import TokenPayload
from services.auth import (
    AuthenticationError,
    authenticate_user,
    blacklist_token,
    create_access_token,
    init_auth_service,
    validate_token,
)


@pytest.fixture(autouse=True)
def _mock_settings(monkeypatch):
    """Provide test JWT settings for all tests in this module."""
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-for-unit-tests")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("SESSION_TIMEOUT_SECONDS", "1800")
    monkeypatch.setenv("TOKEN_REFRESH_THRESHOLD_SECONDS", "300")
    # Clear the cached settings singleton so new env vars take effect
    import config.settings as settings_module

    settings_module._settings = None
    yield
    settings_module._settings = None


@pytest.fixture
def mock_pg():
    """Mock PostgresConnector with async methods."""
    pg = AsyncMock()
    init_auth_service(pg)
    return pg


# --- authenticate_user tests ---


class TestAuthenticateUser:
    """Tests for authenticate_user()."""

    async def test_happy_path(self, mock_pg):
        """User found, password valid, role exists -> LoginResponse."""
        mock_pg.fetchrow.side_effect = [
            # First call: user lookup
            {
                "id": 1,
                "user_name": "rajesh",
                "email_id": "rajesh@technova.com",
                "tenant": "TechNova",
                "password": "pbkdf2:sha256:260000$test$hash",
                "status": "ACTIVE",
                "security_q1": None,
                "security_a1": None,
                "security_q2": None,
                "security_a2": None,
                "security_q3": None,
                "security_a3": None,
            },
            # Second call: role lookup
            {
                "slno": 1,
                "first_name": "Rajesh",
                "last_name": "Kumar",
                "email_id": "rajesh@technova.com",
                "user_name": "rajesh",
                "tenant": "TechNova",
                "role": "VENDOR",
            },
        ]

        with patch("services.auth.check_password_hash", return_value=True):
            result = await authenticate_user(
                "rajesh", "password123", correlation_id="test-corr"
            )

        assert result.user_name == "rajesh"
        assert result.email == "rajesh@technova.com"
        assert result.role == "VENDOR"
        assert result.tenant == "TechNova"
        assert result.token  # JWT string should be non-empty

    async def test_user_not_found(self, mock_pg):
        """User not found -> AuthenticationError."""
        mock_pg.fetchrow.return_value = None

        with pytest.raises(AuthenticationError, match="Invalid credentials"):
            await authenticate_user("nobody", "password", correlation_id="test")

    async def test_inactive_account(self, mock_pg):
        """Inactive account -> AuthenticationError."""
        mock_pg.fetchrow.return_value = {
            "id": 1,
            "user_name": "rajesh",
            "email_id": "rajesh@technova.com",
            "tenant": "TechNova",
            "password": "hash",
            "status": "INACTIVE",
            "security_q1": None,
            "security_a1": None,
            "security_q2": None,
            "security_a2": None,
            "security_q3": None,
            "security_a3": None,
        }

        with pytest.raises(AuthenticationError, match="Account is inactive"):
            await authenticate_user("rajesh", "password", correlation_id="test")

    async def test_wrong_password(self, mock_pg):
        """Wrong password -> AuthenticationError."""
        mock_pg.fetchrow.return_value = {
            "id": 1,
            "user_name": "rajesh",
            "email_id": "rajesh@technova.com",
            "tenant": "TechNova",
            "password": "pbkdf2:sha256:260000$test$hash",
            "status": "ACTIVE",
            "security_q1": None,
            "security_a1": None,
            "security_q2": None,
            "security_a2": None,
            "security_q3": None,
            "security_a3": None,
        }

        with patch("services.auth.check_password_hash", return_value=False):
            with pytest.raises(AuthenticationError, match="Invalid credentials"):
                await authenticate_user("rajesh", "wrong", correlation_id="test")

    async def test_no_role_assigned(self, mock_pg):
        """User exists but no role -> AuthenticationError."""
        mock_pg.fetchrow.side_effect = [
            {
                "id": 1,
                "user_name": "rajesh",
                "email_id": "rajesh@technova.com",
                "tenant": "TechNova",
                "password": "hash",
                "status": "ACTIVE",
                "security_q1": None,
                "security_a1": None,
                "security_q2": None,
                "security_a2": None,
                "security_q3": None,
                "security_a3": None,
            },
            None,  # No role found
        ]

        with patch("services.auth.check_password_hash", return_value=True):
            with pytest.raises(AuthenticationError, match="No role assigned"):
                await authenticate_user("rajesh", "password", correlation_id="test")


# --- Token tests ---


class TestCreateAccessToken:
    """Tests for create_access_token()."""

    def test_returns_valid_jwt_string(self):
        token = create_access_token(
            user_name="rajesh",
            role="VENDOR",
            tenant="TechNova",
        )
        assert isinstance(token, str)
        # JWT has 3 parts separated by dots
        parts = token.split(".")
        assert len(parts) == 3


class TestValidateToken:
    """Tests for validate_token()."""

    async def test_valid_token(self, mock_pg):
        """Valid token -> TokenPayload."""
        # Mock blacklist check to return not-blacklisted
        mock_pg.fetchrow.return_value = None

        token = create_access_token("rajesh", "VENDOR", "TechNova")
        result = await validate_token(token)

        assert result is not None
        assert isinstance(result, TokenPayload)
        assert result.sub == "rajesh"
        assert result.role == "VENDOR"
        assert result.tenant == "TechNova"

    async def test_expired_token(self, mock_pg):
        """Expired token -> None."""
        from jose import jwt

        from config.settings import get_settings

        settings = get_settings()
        claims = {
            "sub": "rajesh",
            "role": "VENDOR",
            "tenant": "TechNova",
            "exp": time.time() - 100,  # Already expired
            "iat": time.time() - 1900,
            "jti": "test-jti",
        }
        token = jwt.encode(claims, settings.jwt_secret_key, algorithm="HS256")

        result = await validate_token(token)
        assert result is None

    async def test_blacklisted_token(self, mock_pg):
        """Blacklisted JTI -> None."""
        # Mock blacklist check to return a row (blacklisted)
        mock_pg.fetchrow.return_value = {"1": 1}

        token = create_access_token("rajesh", "VENDOR", "TechNova")
        result = await validate_token(token)

        assert result is None


class TestBlacklistToken:
    """Tests for blacklist_token()."""

    async def test_stores_jti_in_cache(self, mock_pg):
        """Blacklisting stores the JTI key in cache."""
        token = create_access_token("rajesh", "VENDOR", "TechNova")

        await blacklist_token(token, correlation_id="test")

        # Verify pg.execute was called to store the blacklist entry
        mock_pg.execute.assert_called_once()
        call_args = mock_pg.execute.call_args
        assert "cache.kv_store" in call_args[0][0]
        assert "vqms:auth:blacklist:" in call_args[0][1]

    async def test_invalid_token_raises(self, mock_pg):
        """Invalid token -> AuthenticationError."""
        with pytest.raises(AuthenticationError, match="Cannot decode"):
            await blacklist_token("not-a-valid-jwt", correlation_id="test")
