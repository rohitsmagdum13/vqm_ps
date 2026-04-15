"""Tests for ServiceNowConnector.

All tests mock the httpx.AsyncClient. No real ServiceNow
API calls are made.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from adapters.servicenow import (
    ServiceNowConnector,
    ServiceNowConnectorError,
    _state_to_status,
    _status_to_state,
)
from models.ticket import TicketCreateRequest


# ===========================
# Fixtures
# ===========================


@pytest.fixture
def snow_connector(mock_settings) -> ServiceNowConnector:
    """Create a ServiceNowConnector with a mocked httpx client."""
    connector = ServiceNowConnector(mock_settings)

    # Create a mock httpx AsyncClient and pre-set base URL
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    connector._client = mock_client
    connector._base_url = "https://test.service-now.com"
    return connector


@pytest.fixture
def sample_ticket_request() -> TicketCreateRequest:
    """A valid TicketCreateRequest for testing."""
    return TicketCreateRequest(
        query_id="VQ-2026-0001",
        correlation_id="test-corr-001",
        subject="Invoice discrepancy for PO-2026-1234",
        description="Vendor reports mismatch between invoice and PO amounts.",
        priority="HIGH",
        assigned_team="finance-ops",
        vendor_id="V-001",
        vendor_name="TechNova Solutions",
        category="billing",
        sla_hours=4,
    )


def _mock_post_response(record: dict) -> MagicMock:
    """Build a mock httpx Response for POST /table/incident."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = 201
    response.json.return_value = {"result": record}
    response.raise_for_status = MagicMock()
    return response


def _mock_get_response(results: list[dict]) -> MagicMock:
    """Build a mock httpx Response for GET /table/incident."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = {"result": results}
    response.raise_for_status = MagicMock()
    return response


def _sample_incident_record(overrides: dict | None = None) -> dict:
    """Build a realistic ServiceNow incident record."""
    record = {
        "number": "INC-0000001",
        "sys_id": "abc123def456",
        "state": "1",
        "short_description": "Invoice discrepancy for PO-2026-1234",
        "description": "Vendor reports mismatch.",
        "work_notes": "Checked with accounting. Amount confirmed correct.",
        "assigned_to": "",
        "assignment_group": "finance-ops",
        "priority": "2",
    }
    if overrides:
        record.update(overrides)
    return record


# ===========================
# Tests: create_ticket
# ===========================


class TestCreateTicket:
    """Tests for create_ticket method."""

    async def test_creates_ticket_and_returns_ticket_info(
        self, snow_connector, sample_ticket_request
    ) -> None:
        """Successful creation returns TicketInfo with INC number."""
        snow_connector._client.post.return_value = _mock_post_response(
            _sample_incident_record()
        )

        result = await snow_connector.create_ticket(
            sample_ticket_request, correlation_id="test-001"
        )

        assert result.ticket_id == "INC-0000001"
        assert result.query_id == "VQ-2026-0001"
        assert result.status == "New"
        assert result.assigned_team == "finance-ops"
        assert result.sla_deadline > result.created_at

    async def test_maps_priority_to_servicenow_value(
        self, snow_connector, sample_ticket_request
    ) -> None:
        """VQMS priority string is mapped to ServiceNow numeric priority."""
        snow_connector._client.post.return_value = _mock_post_response(
            _sample_incident_record()
        )

        await snow_connector.create_ticket(
            sample_ticket_request, correlation_id="test-002"
        )

        # Verify the payload sent to ServiceNow has numeric priority "2" for HIGH
        call_args = snow_connector._client.post.call_args
        payload = call_args.kwargs.get("json", {})
        assert payload["priority"] == "2"

    async def test_creation_failure_raises_error(
        self, snow_connector, sample_ticket_request
    ) -> None:
        """ServiceNow API error raises ServiceNowConnectorError."""
        snow_connector._client.post.side_effect = httpx.HTTPStatusError(
            "Server Error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )

        with pytest.raises(ServiceNowConnectorError, match="Failed to create"):
            await snow_connector.create_ticket(
                sample_ticket_request, correlation_id="test-003"
            )

    async def test_includes_custom_fields_in_payload(
        self, snow_connector, sample_ticket_request
    ) -> None:
        """Custom VQMS fields (query_id, vendor_id) are sent to ServiceNow."""
        snow_connector._client.post.return_value = _mock_post_response(
            _sample_incident_record()
        )

        await snow_connector.create_ticket(
            sample_ticket_request, correlation_id="test-004"
        )

        call_args = snow_connector._client.post.call_args
        payload = call_args.kwargs.get("json", {})
        assert payload["u_query_id"] == "VQ-2026-0001"
        assert payload["u_vendor_id"] == "V-001"
        assert payload["u_vendor_name"] == "TechNova Solutions"

    async def test_posts_to_correct_url(
        self, snow_connector, sample_ticket_request
    ) -> None:
        """POST request targets the correct ServiceNow Table API URL."""
        snow_connector._client.post.return_value = _mock_post_response(
            _sample_incident_record()
        )

        await snow_connector.create_ticket(
            sample_ticket_request, correlation_id="test-005"
        )

        call_args = snow_connector._client.post.call_args
        assert call_args.args[0] == "https://test.service-now.com/api/now/table/incident"


# ===========================
# Tests: update_ticket_status
# ===========================


class TestUpdateTicketStatus:
    """Tests for update_ticket_status method."""

    async def test_updates_status_successfully(self, snow_connector) -> None:
        """Status update returns success dict."""
        # Mock GET to find sys_id
        snow_connector._client.get.return_value = _mock_get_response(
            [{"sys_id": "abc123"}]
        )
        # Mock PATCH to update
        patch_response = MagicMock(spec=httpx.Response)
        patch_response.status_code = 200
        patch_response.raise_for_status = MagicMock()
        snow_connector._client.patch.return_value = patch_response

        result = await snow_connector.update_ticket_status(
            "INC-0000001", "Resolved", work_notes="Fixed.",
            correlation_id="test-006",
        )

        assert result["ticket_id"] == "INC-0000001"
        assert result["status"] == "Resolved"

    async def test_update_sends_correct_state(self, snow_connector) -> None:
        """Status string is mapped to ServiceNow state code in PATCH body."""
        snow_connector._client.get.return_value = _mock_get_response(
            [{"sys_id": "abc123"}]
        )
        patch_response = MagicMock(spec=httpx.Response)
        patch_response.raise_for_status = MagicMock()
        snow_connector._client.patch.return_value = patch_response

        await snow_connector.update_ticket_status(
            "INC-0000001", "In Progress", correlation_id="test-007"
        )

        call_args = snow_connector._client.patch.call_args
        payload = call_args.kwargs.get("json", {})
        assert payload["state"] == "2"  # In Progress = 2

    async def test_update_not_found_raises_error(self, snow_connector) -> None:
        """Updating a non-existent ticket raises ServiceNowConnectorError."""
        snow_connector._client.get.return_value = _mock_get_response([])

        with pytest.raises(ServiceNowConnectorError, match="not found"):
            await snow_connector.update_ticket_status(
                "INC-9999999", "Resolved", correlation_id="test-008"
            )

    async def test_update_api_failure_raises_error(self, snow_connector) -> None:
        """PATCH failure raises ServiceNowConnectorError."""
        snow_connector._client.get.return_value = _mock_get_response(
            [{"sys_id": "abc123"}]
        )
        snow_connector._client.patch.side_effect = httpx.ConnectError("Timeout")

        with pytest.raises(ServiceNowConnectorError, match="Failed to update"):
            await snow_connector.update_ticket_status(
                "INC-0000001", "Resolved", correlation_id="test-009"
            )


# ===========================
# Tests: get_ticket
# ===========================


class TestGetTicket:
    """Tests for get_ticket method."""

    async def test_found_returns_ticket_dict(self, snow_connector) -> None:
        """Existing ticket returns a dict with mapped fields."""
        snow_connector._client.get.return_value = _mock_get_response(
            [_sample_incident_record()]
        )

        result = await snow_connector.get_ticket(
            "INC-0000001", correlation_id="test-010"
        )

        assert result is not None
        assert result["ticket_id"] == "INC-0000001"
        assert result["status"] == "New"
        assert result["sys_id"] == "abc123def456"

    async def test_not_found_returns_none(self, snow_connector) -> None:
        """Non-existent ticket returns None."""
        snow_connector._client.get.return_value = _mock_get_response([])

        result = await snow_connector.get_ticket(
            "INC-9999999", correlation_id="test-011"
        )
        assert result is None

    async def test_api_error_returns_none(self, snow_connector) -> None:
        """API exception returns None (non-critical)."""
        snow_connector._client.get.side_effect = httpx.ConnectError("API down")

        result = await snow_connector.get_ticket(
            "INC-0000001", correlation_id="test-012"
        )
        assert result is None


# ===========================
# Tests: get_work_notes
# ===========================


class TestGetWorkNotes:
    """Tests for get_work_notes method."""

    async def test_returns_work_notes_text(self, snow_connector) -> None:
        """Work notes are extracted from the ticket record."""
        snow_connector._client.get.return_value = _mock_get_response(
            [_sample_incident_record()]
        )

        result = await snow_connector.get_work_notes(
            "INC-0000001", correlation_id="test-013"
        )
        assert "Checked with accounting" in result

    async def test_missing_ticket_returns_empty_string(self, snow_connector) -> None:
        """Non-existent ticket returns empty string."""
        snow_connector._client.get.return_value = _mock_get_response([])

        result = await snow_connector.get_work_notes(
            "INC-9999999", correlation_id="test-014"
        )
        assert result == ""


# ===========================
# Tests: Helper Functions
# ===========================


class TestHelperFunctions:
    """Tests for status/state mapping helpers."""

    def test_status_to_state_known_values(self) -> None:
        """Known statuses map to correct ServiceNow state codes."""
        assert _status_to_state("New") == "1"
        assert _status_to_state("In Progress") == "2"
        assert _status_to_state("On Hold") == "3"
        assert _status_to_state("Resolved") == "6"
        assert _status_to_state("Closed") == "7"

    def test_status_to_state_unknown_defaults_to_new(self) -> None:
        """Unknown status defaults to state 1 (New)."""
        assert _status_to_state("SomeOtherStatus") == "1"

    def test_state_to_status_known_values(self) -> None:
        """Known state codes map to correct human-readable statuses."""
        assert _state_to_status("1") == "New"
        assert _state_to_status("2") == "In Progress"
        assert _state_to_status("6") == "Resolved"
        assert _state_to_status("7") == "Closed"

    def test_state_to_status_unknown_defaults_to_new(self) -> None:
        """Unknown state code defaults to 'New'."""
        assert _state_to_status("99") == "New"


# ===========================
# Tests: Lazy Initialization
# ===========================


class TestLazyInit:
    """Tests for lazy client initialization."""

    def test_client_not_created_on_init(self, mock_settings) -> None:
        """httpx client is not created during __init__."""
        connector = ServiceNowConnector(mock_settings)
        assert connector._client is None

    def test_missing_instance_url_raises(self, mock_settings) -> None:
        """Missing SERVICENOW_INSTANCE_URL raises ServiceNowConnectorError."""
        mock_settings.servicenow_instance_url = None
        connector = ServiceNowConnector(mock_settings)

        with pytest.raises(ServiceNowConnectorError, match="SERVICENOW_INSTANCE_URL"):
            connector._get_client()

    def test_missing_credentials_raises(self, mock_settings) -> None:
        """Missing username/password raises ServiceNowConnectorError."""
        mock_settings.servicenow_username = None
        mock_settings.servicenow_password = None
        connector = ServiceNowConnector(mock_settings)

        with pytest.raises(ServiceNowConnectorError, match="SERVICENOW_USERNAME"):
            connector._get_client()
