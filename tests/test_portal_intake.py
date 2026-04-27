"""Tests for PortalIntakeService.

All connectors are mocked via AsyncMock fixtures from conftest.
Tests verify query submission, idempotency, and non-critical
step failure handling.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from services.portal_submission import PortalIntakeService
from models.query import QuerySubmission, UnifiedQueryPayload
from utils.exceptions import DuplicateQueryError


@pytest.fixture
def mock_sqs_connector() -> AsyncMock:
    """Mock SQS connector."""
    mock = AsyncMock()
    mock.send_message.return_value = "mock-message-id"
    return mock


@pytest.fixture
def mock_eventbridge_connector() -> AsyncMock:
    """Mock EventBridge connector."""
    mock = AsyncMock()
    mock.publish_event.return_value = "mock-event-id"
    return mock


@pytest.fixture
def portal_service(
    mock_postgres,
    mock_sqs_connector,
    mock_eventbridge_connector,
    mock_settings,
) -> PortalIntakeService:
    """Create a PortalIntakeService with all connectors mocked."""
    return PortalIntakeService(
        postgres=mock_postgres,
        sqs=mock_sqs_connector,
        eventbridge=mock_eventbridge_connector,
        settings=mock_settings,
    )


@pytest.fixture
def valid_submission() -> QuerySubmission:
    """Valid QuerySubmission for testing."""
    return QuerySubmission(
        subject="Invoice discrepancy for PO-2026-1234",
        description=(
            "We noticed a discrepancy between the invoice amount "
            "and the purchase order total. Invoice #INV-5678 shows "
            "$15,000 but PO-2026-1234 was approved for $12,500. "
            "Please review and advise."
        ),
        query_type="INVOICE_PAYMENT",
        priority="HIGH",
        reference_number="PO-2026-1234",
    )


class TestSubmitQueryHappyPath:
    """Tests for successful portal query submission."""

    async def test_returns_unified_payload(
        self, portal_service, valid_submission
    ) -> None:
        """submit_query returns a UnifiedQueryPayload with correct fields."""
        result = await portal_service.submit_query(
            valid_submission,
            vendor_id="V-001",
            correlation_id="test-corr-200",
        )

        assert isinstance(result, UnifiedQueryPayload)
        assert result.source == "portal"
        assert result.vendor_id == "V-001"
        assert result.subject == valid_submission.subject
        assert result.body == valid_submission.description
        assert result.priority == "HIGH"
        assert result.thread_status == "NEW"
        assert result.metadata["query_type"] == "INVOICE_PAYMENT"
        assert result.metadata["reference_number"] == "PO-2026-1234"

    async def test_query_id_generated(
        self, portal_service, valid_submission
    ) -> None:
        """Generated query_id follows VQ-YYYY-XXXX format."""
        result = await portal_service.submit_query(
            valid_submission, vendor_id="V-001"
        )

        assert result.query_id.startswith("VQ-")
        parts = result.query_id.split("-")
        assert len(parts) == 3
        assert len(parts[2]) == 4  # 4-digit sequence

    async def test_sqs_message_sent(
        self, portal_service, valid_submission, mock_sqs_connector
    ) -> None:
        """SQS send_message is called with the payload."""
        await portal_service.submit_query(
            valid_submission, vendor_id="V-001"
        )

        mock_sqs_connector.send_message.assert_called_once()
        call_args = mock_sqs_connector.send_message.call_args
        body = call_args.args[1]
        assert body["source"] == "portal"
        assert body["vendor_id"] == "V-001"

    async def test_db_write_called(
        self, portal_service, valid_submission, mock_postgres
    ) -> None:
        """Database execute is called for the case_execution insert.

        The full flow makes three writes — case_execution, portal_queries,
        and the extracted_entities update — so we just check the
        case_execution row is among them.
        """
        await portal_service.submit_query(
            valid_submission, vendor_id="V-001"
        )

        sql_statements = [
            call.args[0] for call in mock_postgres.execute.call_args_list
        ]
        assert any(
            "workflow.case_execution" in sql for sql in sql_statements
        )

    async def test_eventbridge_event_published(
        self, portal_service, valid_submission, mock_eventbridge_connector
    ) -> None:
        """EventBridge QueryReceived event is published."""
        await portal_service.submit_query(
            valid_submission, vendor_id="V-001"
        )

        mock_eventbridge_connector.publish_event.assert_called_once()
        call_args = mock_eventbridge_connector.publish_event.call_args
        assert call_args.args[0] == "QueryReceived"


class TestSubmitQueryDuplicate:
    """Tests for idempotency (duplicate detection)."""

    async def test_duplicate_raises_error(
        self, portal_service, valid_submission, mock_postgres
    ) -> None:
        """Duplicate submission raises DuplicateQueryError."""
        mock_postgres.check_idempotency.return_value = False

        with pytest.raises(DuplicateQueryError):
            await portal_service.submit_query(
                valid_submission, vendor_id="V-001"
            )

    async def test_duplicate_does_not_write_to_db(
        self, portal_service, valid_submission, mock_postgres
    ) -> None:
        """Duplicate submission doesn't write to database."""
        mock_postgres.check_idempotency.return_value = False

        with pytest.raises(DuplicateQueryError):
            await portal_service.submit_query(
                valid_submission, vendor_id="V-001"
            )

        mock_postgres.execute.assert_not_called()


class TestSubmitQueryNonCriticalFailures:
    """Tests that non-critical step failures don't block submission."""

    async def test_eventbridge_failure_does_not_block(
        self, portal_service, valid_submission, mock_eventbridge_connector, mock_sqs_connector
    ) -> None:
        """EventBridge failure doesn't prevent SQS enqueue."""
        mock_eventbridge_connector.publish_event.side_effect = Exception("EB down")

        result = await portal_service.submit_query(
            valid_submission, vendor_id="V-001"
        )

        assert result is not None
        mock_sqs_connector.send_message.assert_called_once()


class TestIdempotencyKey:
    """Tests for idempotency key generation."""

    async def test_idempotency_key_includes_vendor_id(
        self, portal_service, valid_submission, mock_postgres
    ) -> None:
        """Idempotency key is a SHA-256 hash that includes vendor_id."""
        await portal_service.submit_query(
            valid_submission, vendor_id="V-001"
        )

        # check_idempotency was called with a hash string
        call_args = mock_postgres.check_idempotency.call_args
        key = call_args.args[0]
        # SHA-256 hex digest is 64 characters
        assert len(key) == 64
        assert call_args.args[1] == "portal"

    async def test_different_vendor_produces_different_key(
        self, portal_service, valid_submission, mock_postgres
    ) -> None:
        """Different vendor_id produces a different idempotency key."""
        await portal_service.submit_query(
            valid_submission, vendor_id="V-001"
        )
        key_1 = mock_postgres.check_idempotency.call_args.args[0]

        await portal_service.submit_query(
            valid_submission, vendor_id="V-002"
        )
        key_2 = mock_postgres.check_idempotency.call_args.args[0]

        assert key_1 != key_2


class TestVendorIdFromParameter:
    """Verify vendor_id comes from the function parameter, not the submission."""

    async def test_vendor_id_from_parameter(
        self, portal_service, valid_submission
    ) -> None:
        """vendor_id in the result comes from the parameter, not the submission body."""
        result = await portal_service.submit_query(
            valid_submission, vendor_id="V-999"
        )

        assert result.vendor_id == "V-999"
