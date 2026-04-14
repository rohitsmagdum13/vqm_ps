"""Tests for vendor management routes."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.middleware.auth_middleware import AuthMiddleware
from api.routes.vendors import router as vendors_router
from adapters.salesforce import SalesforceConnectorError
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
def mock_salesforce():
    """Mock SalesforceConnector."""
    sf = AsyncMock()
    return sf


@pytest.fixture
def test_app(mock_pg, mock_salesforce):
    """Create test FastAPI app with vendor routes."""
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(vendors_router)

    # Store mock salesforce on app.state
    app.state.salesforce = mock_salesforce

    return app


@pytest.fixture
def client(test_app):
    return TestClient(test_app)


@pytest.fixture
def auth_headers(mock_pg):
    """Valid Bearer token headers for authenticated requests."""
    # Mock blacklist check to return not-blacklisted
    mock_pg.fetchrow.return_value = None
    token = create_access_token("admin", "ADMIN", "Hexaware")
    return {"Authorization": f"Bearer {token}"}


SAMPLE_VENDORS = [
    {
        "id": "001ABC",
        "name": "TechNova Solutions",
        "vendor_id": "V-001",
        "website": "https://technova.com",
        "vendor_tier": "GOLD",
        "category": "IT Services",
        "payment_terms": "Net 30",
        "annual_revenue": 5000000.0,
        "sla_response_hours": 4.0,
        "sla_resolution_days": 5.0,
        "vendor_status": "Active",
        "onboarded_date": "2024-01-15",
        "billing_city": "Mumbai",
        "billing_state": "Maharashtra",
        "billing_country": "India",
    },
]


class TestGetAllVendors:
    """Tests for GET /vendors."""

    def test_returns_vendor_list(self, client, auth_headers, mock_salesforce):
        mock_salesforce.get_all_active_vendors.return_value = SAMPLE_VENDORS

        resp = client.get("/vendors", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "TechNova Solutions"
        assert data[0]["vendor_id"] == "V-001"

    def test_salesforce_failure_returns_502(self, client, auth_headers, mock_salesforce):
        mock_salesforce.get_all_active_vendors.side_effect = SalesforceConnectorError(
            "Connection failed"
        )

        resp = client.get("/vendors", headers=auth_headers)
        assert resp.status_code == 502
        assert "Salesforce query failed" in resp.json()["detail"]

    def test_requires_authentication(self, client):
        resp = client.get("/vendors")
        assert resp.status_code == 401


class TestUpdateVendor:
    """Tests for PUT /vendors/{vendor_id}."""

    def test_valid_update(self, client, auth_headers, mock_salesforce):
        mock_salesforce.update_vendor_account.return_value = {
            "success": True,
            "vendor_id": "V-001",
            "updated_fields": ["Website", "Vendor_Tier__c"],
        }

        resp = client.put(
            "/vendors/V-001",
            headers=auth_headers,
            json={"website": "https://new.technova.com", "vendor_tier": "PLATINUM"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["vendor_id"] == "V-001"
        assert len(data["updated_fields"]) == 2

    def test_empty_body_returns_422(self, client, auth_headers):
        resp = client.put(
            "/vendors/V-001",
            headers=auth_headers,
            json={},
        )
        assert resp.status_code == 422

    def test_salesforce_failure_returns_502(self, client, auth_headers, mock_salesforce):
        mock_salesforce.update_vendor_account.side_effect = SalesforceConnectorError(
            "Update failed"
        )

        resp = client.put(
            "/vendors/V-001",
            headers=auth_headers,
            json={"website": "https://new.com"},
        )
        assert resp.status_code == 502

    def test_requires_authentication(self, client):
        resp = client.put("/vendors/V-001", json={"website": "https://new.com"})
        assert resp.status_code == 401
