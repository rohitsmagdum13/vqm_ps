"""Tests for POST /webhooks/servicenow (Phase 6 Step 15 resume path).

Covers:
- status=RESOLVED with a linked ticket → SQS enqueue with
  resume_context.action=prepare_resolution
- status!=RESOLVED → ignored (no DB lookup, no SQS enqueue)
- ticket_id with no ticket_link row → ignored (no SQS enqueue)
- query_id exists in ticket_link but no case_execution → ignored
- missing sqs_query_intake_queue_url on settings → error return
- SQS enqueue failure → error return, does not raise
- Invalid payload (missing ticket_id) → 422 from Pydantic validation
- Payload validation: ticket_id and status are required
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.routes.webhooks import router as webhooks_router


# ===========================
# Fixtures
# ===========================


@pytest.fixture
def mock_sqs_adapter() -> AsyncMock:
    """AsyncMock of SQSConnector with send_message."""
    sqs = AsyncMock()
    sqs.send_message.return_value = None
    return sqs


@pytest.fixture
def webhook_app(mock_postgres, mock_sqs_adapter, mock_settings) -> FastAPI:
    """FastAPI app wired for ServiceNow webhook tests."""
    app = FastAPI()
    app.include_router(webhooks_router)
    app.state.postgres = mock_postgres
    app.state.sqs = mock_sqs_adapter
    app.state.settings = mock_settings
    return app


@pytest.fixture
async def client(webhook_app) -> AsyncClient:
    """Async test client for the webhook app."""
    transport = ASGITransport(app=webhook_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _link_row() -> dict:
    return {"query_id": "VQ-2026-0001"}


def _case_row() -> dict:
    return {
        "query_id": "VQ-2026-0001",
        "correlation_id": "orig-corr-001",
        "execution_id": "exec-001",
        "source": "email",
        "analysis_result": {"intent_classification": "invoice_discrepancy"},
        "vendor_id": "V-001",
    }


# ===========================
# Tests: Happy path — status=RESOLVED enqueues resume message
# ===========================


class TestServiceNowWebhookResolved:
    """RESOLVED + linked ticket re-enters the pipeline."""

    async def test_resolved_enqueues_to_sqs(
        self, client, webhook_app, mock_postgres, mock_sqs_adapter
    ) -> None:
        """Ticket marked RESOLVED → send_message called on query_intake queue."""
        mock_postgres.fetchrow.side_effect = [_link_row(), _case_row()]

        response = await client.post(
            "/webhooks/servicenow",
            json={"ticket_id": "INC1234567", "status": "RESOLVED"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "enqueued"
        assert data["query_id"] == "VQ-2026-0001"
        mock_sqs_adapter.send_message.assert_awaited_once()

    async def test_resume_message_has_prepare_resolution_action(
        self, client, mock_postgres, mock_sqs_adapter
    ) -> None:
        """The enqueued SQS message carries resume_context.action=prepare_resolution."""
        mock_postgres.fetchrow.side_effect = [_link_row(), _case_row()]

        await client.post(
            "/webhooks/servicenow",
            json={"ticket_id": "INC1234567", "status": "RESOLVED"},
        )

        call = mock_sqs_adapter.send_message.await_args
        # send_message(queue_url, message, correlation_id=...)
        queue_url, message = call.args[0], call.args[1]
        assert queue_url.endswith("test-query-intake")
        assert message["resume_context"]["action"] == "prepare_resolution"
        assert message["resume_context"]["from_servicenow"] is True
        assert message["resume_context"]["ticket_id"] == "INC1234567"

    async def test_resume_message_carries_original_correlation_id(
        self, client, mock_postgres, mock_sqs_adapter
    ) -> None:
        """Original case correlation_id is preserved so traces stay linked."""
        mock_postgres.fetchrow.side_effect = [_link_row(), _case_row()]

        await client.post(
            "/webhooks/servicenow",
            json={
                "ticket_id": "INC1234567",
                "status": "RESOLVED",
                "correlation_id": "webhook-corr-999",
            },
        )

        message = mock_sqs_adapter.send_message.await_args.args[1]
        # case_row.correlation_id takes precedence over payload correlation_id
        assert message["correlation_id"] == "orig-corr-001"

    async def test_lowercase_resolved_is_normalized(
        self, client, mock_postgres, mock_sqs_adapter
    ) -> None:
        """Webhook uppercases status — 'resolved' is treated as RESOLVED."""
        mock_postgres.fetchrow.side_effect = [_link_row(), _case_row()]

        response = await client.post(
            "/webhooks/servicenow",
            json={"ticket_id": "INC1234567", "status": "resolved"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "enqueued"


# ===========================
# Tests: Non-RESOLVED is ignored
# ===========================


class TestServiceNowWebhookIgnored:
    """Non-actionable statuses and orphan tickets short-circuit."""

    async def test_non_resolved_status_is_ignored(
        self, client, mock_postgres, mock_sqs_adapter
    ) -> None:
        """Status=IN_PROGRESS → ignored, no DB lookup, no SQS enqueue."""
        response = await client.post(
            "/webhooks/servicenow",
            json={"ticket_id": "INC1234567", "status": "IN_PROGRESS"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ignored"
        mock_postgres.fetchrow.assert_not_called()
        mock_sqs_adapter.send_message.assert_not_called()

    async def test_no_ticket_link_row_is_ignored(
        self, client, mock_postgres, mock_sqs_adapter
    ) -> None:
        """RESOLVED ticket with no workflow.ticket_link row → ignored."""
        mock_postgres.fetchrow.return_value = None

        response = await client.post(
            "/webhooks/servicenow",
            json={"ticket_id": "INC-UNKNOWN", "status": "RESOLVED"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ignored"
        mock_sqs_adapter.send_message.assert_not_called()

    async def test_no_case_execution_row_is_ignored(
        self, client, mock_postgres, mock_sqs_adapter
    ) -> None:
        """ticket_link exists but case_execution missing → ignored."""
        # First fetchrow returns link; second (case_execution) returns None
        mock_postgres.fetchrow.side_effect = [_link_row(), None]

        response = await client.post(
            "/webhooks/servicenow",
            json={"ticket_id": "INC1234567", "status": "RESOLVED"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ignored"
        mock_sqs_adapter.send_message.assert_not_called()


# ===========================
# Tests: Error paths
# ===========================


class TestServiceNowWebhookErrors:
    """Config and SQS failures return {"status": "error"} without raising."""

    async def test_missing_queue_url_returns_error(
        self, webhook_app, client, mock_postgres, mock_sqs_adapter
    ) -> None:
        """No sqs_query_intake_queue_url on settings → error, no enqueue."""
        mock_postgres.fetchrow.side_effect = [_link_row(), _case_row()]
        # Replace settings with an object whose queue URL is empty
        webhook_app.state.settings.sqs_query_intake_queue_url = ""

        response = await client.post(
            "/webhooks/servicenow",
            json={"ticket_id": "INC1234567", "status": "RESOLVED"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "error"
        mock_sqs_adapter.send_message.assert_not_called()

    async def test_sqs_enqueue_failure_returns_error(
        self, client, mock_postgres, mock_sqs_adapter
    ) -> None:
        """SQS send_message raises → webhook returns {status: error}, no 500."""
        mock_postgres.fetchrow.side_effect = [_link_row(), _case_row()]
        mock_sqs_adapter.send_message.side_effect = RuntimeError("sqs down")

        response = await client.post(
            "/webhooks/servicenow",
            json={"ticket_id": "INC1234567", "status": "RESOLVED"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "error"


# ===========================
# Tests: Payload validation
# ===========================


class TestServiceNowWebhookPayloadValidation:
    """Pydantic validation enforces required fields."""

    async def test_missing_ticket_id_returns_422(self, client) -> None:
        """Missing ticket_id → 422 from Pydantic."""
        response = await client.post(
            "/webhooks/servicenow",
            json={"status": "RESOLVED"},
        )
        assert response.status_code == 422

    async def test_missing_status_returns_422(self, client) -> None:
        """Missing status → 422 from Pydantic."""
        response = await client.post(
            "/webhooks/servicenow",
            json={"ticket_id": "INC1234567"},
        )
        assert response.status_code == 422

    async def test_correlation_id_is_optional(
        self, client, mock_postgres, mock_sqs_adapter
    ) -> None:
        """Missing correlation_id is accepted — webhook generates one."""
        mock_postgres.fetchrow.side_effect = [_link_row(), _case_row()]

        response = await client.post(
            "/webhooks/servicenow",
            json={"ticket_id": "INC1234567", "status": "RESOLVED"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "enqueued"
