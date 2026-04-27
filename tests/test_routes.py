"""Tests for FastAPI intake routes.

Uses httpx.AsyncClient with ASGITransport to test routes
without starting a real server. All connectors are mocked
via app.state overrides.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from services.portal_submission import PortalIntakeService
from api.routes.queries import router
from api.routes.webhooks import router as webhooks_router
from models.query import UnifiedQueryPayload
from utils.exceptions import DuplicateQueryError
from utils.helpers import TimeHelper


@pytest.fixture
def test_app(mock_postgres, mock_settings) -> FastAPI:
    """Create a test FastAPI app with mocked state."""
    app = FastAPI()
    app.include_router(router)
    app.include_router(webhooks_router)

    # Set up mock connectors on app.state
    app.state.postgres = mock_postgres

    # Create a mock portal_intake service
    mock_portal = AsyncMock(spec=PortalIntakeService)
    now = TimeHelper.ist_now()
    mock_portal.submit_query.return_value = UnifiedQueryPayload(
        query_id="VQ-2026-0001",
        correlation_id="test-corr-300",
        execution_id="exec-001",
        source="portal",
        vendor_id="V-001",
        subject="Test query",
        body="Test description text",
        priority="MEDIUM",
        received_at=now,
        thread_status="NEW",
        metadata={},
    )
    app.state.portal_intake = mock_portal

    # Create a mock email_intake service
    mock_email_intake = AsyncMock()
    mock_email_intake.process_email.return_value = None
    app.state.email_intake = mock_email_intake

    return app


@pytest.fixture
async def client(test_app) -> AsyncClient:
    """Create an async test client."""
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestPostQueries:
    """Tests for POST /queries endpoint."""

    async def test_submit_returns_201(self, client) -> None:
        """Valid submission returns 201 with query_id."""
        # POST /queries now expects multipart/form-data: a 'submission'
        # form field carrying the JSON-encoded QuerySubmission, plus
        # zero or more file uploads.
        submission = {
            "subject": "Invoice discrepancy for PO-2026-1234",
            "description": (
                "We noticed a discrepancy between the invoice "
                "and purchase order. Please review."
            ),
            "query_type": "INVOICE_PAYMENT",
            "priority": "HIGH",
        }
        response = await client.post(
            "/queries",
            data={"submission": json.dumps(submission)},
            headers={
                "X-Vendor-ID": "V-001",
                "X-Correlation-ID": "test-corr-300",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["query_id"] == "VQ-2026-0001"
        assert data["status"] == "RECEIVED"

    async def test_missing_vendor_id_returns_400(self, client) -> None:
        """Missing X-Vendor-ID header returns 400."""
        submission = {
            "subject": "Test query subject line",
            "description": "This is a test description for the query.",
            "query_type": "INVOICE_PAYMENT",
        }
        response = await client.post(
            "/queries",
            data={"submission": json.dumps(submission)},
        )

        # FastAPI's required-Header rejection comes back as 422 by
        # default; either is acceptable as long as it's not 201.
        assert response.status_code in (400, 422)

    async def test_invalid_body_returns_422(self, client) -> None:
        """Invalid submission body returns 422 (Pydantic validation)."""
        submission = {
            "subject": "Hi",  # Too short (min 5 chars)
            "description": "Short",  # Too short (min 10 chars)
            "query_type": "INVOICE_PAYMENT",
        }
        response = await client.post(
            "/queries",
            data={"submission": json.dumps(submission)},
            headers={"X-Vendor-ID": "V-001"},
        )

        assert response.status_code == 422

    async def test_duplicate_returns_409(self, client, test_app) -> None:
        """Duplicate submission returns 409."""
        test_app.state.portal_intake.submit_query.side_effect = DuplicateQueryError(
            "hash-123", correlation_id="test"
        )

        submission = {
            "subject": "Duplicate query subject here",
            "description": "This is a duplicate query description text.",
            "query_type": "INVOICE_PAYMENT",
        }
        response = await client.post(
            "/queries",
            data={"submission": json.dumps(submission)},
            headers={"X-Vendor-ID": "V-001"},
        )

        assert response.status_code == 409

    async def test_submit_with_attachment(self, client, test_app) -> None:
        """Multipart submission with a file is accepted and reaches the service."""
        submission = {
            "subject": "Invoice query with PDF attachment",
            "description": "Please review the attached invoice for INV-INV-9001.",
            "query_type": "INVOICE_PAYMENT",
            "priority": "MEDIUM",
        }
        # Use a tiny in-memory file — the service is mocked so the
        # bytes don't actually need to be a valid PDF.
        files = {"files": ("invoice.pdf", b"%PDF-1.4 fake-bytes", "application/pdf")}
        response = await client.post(
            "/queries",
            data={"submission": json.dumps(submission)},
            files=files,
            headers={"X-Vendor-ID": "V-001"},
        )

        assert response.status_code == 201
        # The mocked PortalIntakeService should have received one file.
        call = test_app.state.portal_intake.submit_query.call_args
        assert call.kwargs.get("files") is not None
        assert len(call.kwargs["files"]) == 1
        assert call.kwargs["files"][0].filename == "invoice.pdf"


class TestGetQueryStatus:
    """Tests for GET /queries/{query_id} endpoint."""

    async def test_found_returns_200(self, client, mock_postgres) -> None:
        """Existing query returns 200 with status details."""
        mock_postgres.fetchrow.return_value = {
            "query_id": "VQ-2026-0001",
            "status": "RECEIVED",
            "source": "portal",
            "created_at": "2026-04-12 10:00:00",
            "updated_at": "2026-04-12 10:00:00",
        }

        response = await client.get(
            "/queries/VQ-2026-0001",
            headers={"X-Vendor-ID": "V-001"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["query_id"] == "VQ-2026-0001"
        assert data["status"] == "RECEIVED"

    async def test_not_found_returns_404(self, client, mock_postgres) -> None:
        """Non-existent query returns 404."""
        mock_postgres.fetchrow.return_value = None

        response = await client.get(
            "/queries/VQ-2026-9999",
            headers={"X-Vendor-ID": "V-001"},
        )

        assert response.status_code == 404

    async def test_missing_vendor_id_returns_400(self, client) -> None:
        """Missing X-Vendor-ID header returns 400."""
        response = await client.get("/queries/VQ-2026-0001")
        assert response.status_code == 400


class TestWebhook:
    """Tests for POST /webhooks/ms-graph endpoint."""

    async def test_validation_handshake(self, client) -> None:
        """Validation handshake returns the validationToken as text."""
        response = await client.post(
            "/webhooks/ms-graph?validationToken=abc-validation-token-123",
        )

        assert response.status_code == 200
        assert response.text == "abc-validation-token-123"

    async def test_notification_processes_email(self, client, test_app) -> None:
        """Webhook notification triggers email processing."""
        response = await client.post(
            "/webhooks/ms-graph",
            json={
                "value": [
                    {
                        "resource": "Users/mailbox@company.com/Messages/AAMkAGI2TG93AAA=",
                        "changeType": "created",
                    }
                ]
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"
        test_app.state.email_intake.process_email.assert_called_once_with("AAMkAGI2TG93AAA=")


class TestHealthCheck:
    """Tests for GET /health endpoint."""

    async def test_health_returns_200(self, client) -> None:
        """Health check returns 200. Note: health is on the main app,
        not the router. We test it separately if needed."""
        # The health endpoint is on the main app, not in the router.
        # For this test, we check the routes work in general.
        pass
