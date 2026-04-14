"""Tests for vendor management routes (full CRUD + admin-only).

Tests cover:
- GET /vendors          (list all active vendors)
- POST /vendors         (create new vendor with auto V-XXX)
- PUT /vendors/{id}     (update vendor fields)
- DELETE /vendors/{id}  (delete vendor)
- Admin-only access     (403 for non-admin roles)
- Auth required         (401 without token)
"""

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
def admin_headers(mock_pg):
    """Valid Bearer token headers for ADMIN role."""
    mock_pg.fetchrow.return_value = None
    token = create_access_token("admin_user", "ADMIN", "hexaware")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def vendor_headers(mock_pg):
    """Valid Bearer token headers for VENDOR role (non-admin)."""
    mock_pg.fetchrow.return_value = None
    token = create_access_token("vendor_user", "VENDOR", "hexaware")
    return {"Authorization": f"Bearer {token}"}


# Keep backward compat — some old tests use "auth_headers"
@pytest.fixture
def auth_headers(admin_headers):
    """Alias for admin_headers (backward compatibility)."""
    return admin_headers


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


# ---------------------------------------------------------------
# GET /vendors
# ---------------------------------------------------------------

class TestGetAllVendors:
    """Tests for GET /vendors."""

    def test_returns_vendor_list(self, client, admin_headers, mock_salesforce):
        mock_salesforce.get_all_active_vendors.return_value = SAMPLE_VENDORS

        resp = client.get("/vendors", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "TechNova Solutions"
        assert data[0]["vendor_id"] == "V-001"

    def test_salesforce_failure_returns_502(self, client, admin_headers, mock_salesforce):
        mock_salesforce.get_all_active_vendors.side_effect = SalesforceConnectorError(
            "Connection failed"
        )

        resp = client.get("/vendors", headers=admin_headers)
        assert resp.status_code == 502
        assert "Salesforce query failed" in resp.json()["detail"]

    def test_requires_authentication(self, client):
        resp = client.get("/vendors")
        assert resp.status_code == 401

    def test_requires_admin_role(self, client, vendor_headers):
        """VENDOR role should get 403 Forbidden."""
        resp = client.get("/vendors", headers=vendor_headers)
        assert resp.status_code == 403
        assert "Admin access required" in resp.json()["detail"]


# ---------------------------------------------------------------
# POST /vendors (create)
# ---------------------------------------------------------------

class TestCreateVendor:
    """Tests for POST /vendors."""

    def test_create_vendor_success(self, client, admin_headers, mock_salesforce):
        mock_salesforce.create_vendor_account.return_value = {
            "success": True,
            "salesforce_id": "001NEW123",
            "vendor_id": "V-026",
            "name": "New Vendor Corp",
        }

        resp = client.post(
            "/vendors",
            headers=admin_headers,
            json={"name": "New Vendor Corp", "vendor_tier": "Silver"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["success"] is True
        assert data["salesforce_id"] == "001NEW123"
        assert data["vendor_id"] == "V-026"
        assert data["name"] == "New Vendor Corp"
        assert "V-026" in data["message"]

    def test_create_vendor_requires_name(self, client, admin_headers):
        """Name is required — empty body should fail validation."""
        resp = client.post(
            "/vendors",
            headers=admin_headers,
            json={},
        )
        assert resp.status_code == 422

    def test_create_vendor_salesforce_error(self, client, admin_headers, mock_salesforce):
        mock_salesforce.create_vendor_account.side_effect = SalesforceConnectorError(
            "Vendor_Account__c creation failed"
        )

        resp = client.post(
            "/vendors",
            headers=admin_headers,
            json={"name": "Will Fail"},
        )
        assert resp.status_code == 502
        assert "Salesforce create failed" in resp.json()["detail"]

    def test_create_requires_authentication(self, client):
        resp = client.post("/vendors", json={"name": "No Auth"})
        assert resp.status_code == 401

    def test_create_requires_admin_role(self, client, vendor_headers):
        """VENDOR role should get 403 Forbidden."""
        resp = client.post(
            "/vendors",
            headers=vendor_headers,
            json={"name": "Not Admin"},
        )
        assert resp.status_code == 403
        assert "Admin access required" in resp.json()["detail"]


# ---------------------------------------------------------------
# PUT /vendors/{vendor_id} (update)
# ---------------------------------------------------------------

class TestUpdateVendor:
    """Tests for PUT /vendors/{vendor_id}."""

    def test_valid_update(self, client, admin_headers, mock_salesforce):
        mock_salesforce.update_vendor_account.return_value = {
            "success": True,
            "vendor_id": "V-001",
            "updated_fields": ["Website", "Vendor_Tier__c"],
        }

        resp = client.put(
            "/vendors/V-001",
            headers=admin_headers,
            json={"website": "https://new.technova.com", "vendor_tier": "PLATINUM"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["vendor_id"] == "V-001"
        assert len(data["updated_fields"]) == 2

    def test_empty_body_returns_422(self, client, admin_headers):
        resp = client.put(
            "/vendors/V-001",
            headers=admin_headers,
            json={},
        )
        assert resp.status_code == 422

    def test_salesforce_failure_returns_502(self, client, admin_headers, mock_salesforce):
        mock_salesforce.update_vendor_account.side_effect = SalesforceConnectorError(
            "Update failed"
        )

        resp = client.put(
            "/vendors/V-001",
            headers=admin_headers,
            json={"website": "https://new.com"},
        )
        assert resp.status_code == 502

    def test_requires_authentication(self, client):
        resp = client.put("/vendors/V-001", json={"website": "https://new.com"})
        assert resp.status_code == 401

    def test_requires_admin_role(self, client, vendor_headers):
        """VENDOR role should get 403 Forbidden."""
        resp = client.put(
            "/vendors/V-001",
            headers=vendor_headers,
            json={"website": "https://new.com"},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------
# DELETE /vendors/{vendor_id}
# ---------------------------------------------------------------

class TestDeleteVendor:
    """Tests for DELETE /vendors/{vendor_id}."""

    def test_delete_vendor_success(self, client, admin_headers, mock_salesforce):
        mock_salesforce.delete_vendor_account.return_value = {
            "success": True,
            "vendor_id": "V-025",
            "record_id": "001DEL456",
        }

        resp = client.delete("/vendors/V-025", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["vendor_id"] == "V-025"
        assert "deleted successfully" in data["message"]

    def test_delete_by_account_id(self, client, admin_headers, mock_salesforce):
        mock_salesforce.delete_vendor_account.return_value = {
            "success": True,
            "vendor_id": "001al00002Ie1zjAAB",
            "record_id": "001al00002Ie1zjAAB",
        }

        resp = client.delete("/vendors/001al00002Ie1zjAAB", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_delete_salesforce_error(self, client, admin_headers, mock_salesforce):
        mock_salesforce.delete_vendor_account.side_effect = SalesforceConnectorError(
            "Vendor_Account__c deletion failed"
        )

        resp = client.delete("/vendors/V-099", headers=admin_headers)
        assert resp.status_code == 502
        assert "Salesforce delete failed" in resp.json()["detail"]

    def test_delete_requires_authentication(self, client):
        resp = client.delete("/vendors/V-001")
        assert resp.status_code == 401

    def test_delete_requires_admin_role(self, client, vendor_headers):
        """VENDOR role should get 403 Forbidden."""
        resp = client.delete("/vendors/V-001", headers=vendor_headers)
        assert resp.status_code == 403
        assert "Admin access required" in resp.json()["detail"]
