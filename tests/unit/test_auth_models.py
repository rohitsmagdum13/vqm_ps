"""Tests for auth Pydantic models."""

from __future__ import annotations

import pytest

from models.auth import LoginRequest, LoginResponse, TokenPayload, UserRecord, UserRoleRecord


class TestUserRecord:
    """Tests for UserRecord model."""

    def test_validates_with_all_fields(self):
        user = UserRecord(
            id=1,
            user_name="rajesh",
            email_id="rajesh@technova.com",
            tenant="TechNova",
            status="ACTIVE",
            security_q1="Favorite color?",
            security_a1="Blue",
            security_q2="Pet name?",
            security_a2="Max",
            security_q3="City?",
            security_a3="Mumbai",
        )
        assert user.id == 1
        assert user.user_name == "rajesh"
        assert user.email_id == "rajesh@technova.com"
        assert user.tenant == "TechNova"
        assert user.status == "ACTIVE"
        assert user.security_q1 == "Favorite color?"

    def test_validates_with_required_fields_only(self):
        user = UserRecord(
            id=2,
            user_name="admin",
            email_id="admin@company.com",
            tenant="Hexaware",
        )
        assert user.status == "ACTIVE"
        assert user.security_q1 is None
        assert user.security_a1 is None
        assert user.security_q2 is None
        assert user.security_a2 is None
        assert user.security_q3 is None
        assert user.security_a3 is None


class TestUserRoleRecord:
    """Tests for UserRoleRecord model."""

    def test_validates_with_all_fields(self):
        role = UserRoleRecord(
            slno=1,
            first_name="Rajesh",
            last_name="Kumar",
            email_id="rajesh@technova.com",
            user_name="rajesh",
            tenant="TechNova",
            role="VENDOR",
            created_by="admin",
        )
        assert role.role == "VENDOR"
        assert role.created_by == "admin"
        assert role.modified_by is None


class TestLoginRequest:
    """Tests for LoginRequest model."""

    def test_requires_both_fields(self):
        req = LoginRequest(
            username_or_email="rajesh",
            password="secret123",
        )
        assert req.username_or_email == "rajesh"
        assert req.password == "secret123"

    def test_missing_password_raises(self):
        with pytest.raises(Exception):
            LoginRequest(username_or_email="rajesh")

    def test_missing_username_raises(self):
        with pytest.raises(Exception):
            LoginRequest(password="secret123")


class TestLoginResponse:
    """Tests for LoginResponse model."""

    def test_includes_all_fields(self):
        resp = LoginResponse(
            token="eyJhbGciOiJIUzI1NiJ9.test.sig",
            user_name="rajesh",
            email="rajesh@technova.com",
            role="VENDOR",
            tenant="TechNova",
            vendor_id="V-001",
        )
        assert resp.token.startswith("eyJ")
        assert resp.user_name == "rajesh"
        assert resp.email == "rajesh@technova.com"
        assert resp.role == "VENDOR"
        assert resp.tenant == "TechNova"
        assert resp.vendor_id == "V-001"

    def test_vendor_id_optional(self):
        resp = LoginResponse(
            token="token",
            user_name="admin",
            email="admin@company.com",
            role="ADMIN",
            tenant="Hexaware",
        )
        assert resp.vendor_id is None


class TestTokenPayload:
    """Tests for TokenPayload model."""

    def test_includes_all_jwt_claims(self):
        payload = TokenPayload(
            sub="rajesh",
            role="VENDOR",
            tenant="TechNova",
            exp=1700000000.0,
            iat=1699998200.0,
            jti="550e8400-e29b-41d4-a716-446655440000",
        )
        assert payload.sub == "rajesh"
        assert payload.role == "VENDOR"
        assert payload.tenant == "TechNova"
        assert payload.exp == 1700000000.0
        assert payload.iat == 1699998200.0
        assert payload.jti == "550e8400-e29b-41d4-a716-446655440000"
