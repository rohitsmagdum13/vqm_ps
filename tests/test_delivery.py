"""Tests for DeliveryNode (Step 12).

All tests mock ServiceNow and Graph API connectors.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from adapters.servicenow import ServiceNowConnectorError
from models.ticket import TicketInfo
from orchestration.nodes.delivery import DeliveryNode
from utils.exceptions import GraphAPIError


# ===========================
# Fixtures
# ===========================


@pytest.fixture
def mock_servicenow() -> AsyncMock:
    """Mock ServiceNow connector that returns a valid ticket."""
    snow = AsyncMock()
    snow.create_ticket.return_value = TicketInfo(
        ticket_id="INC-0000001",
        query_id="VQ-2026-0001",
        status="New",
        created_at=datetime(2026, 4, 15, 10, 30, 0),
        assigned_team="finance-ops",
        sla_deadline=datetime(2026, 4, 15, 14, 30, 0),
    )
    return snow


@pytest.fixture
def mock_graph() -> AsyncMock:
    """Mock Graph API connector that succeeds on send."""
    graph = AsyncMock()
    graph.send_email.return_value = None
    return graph


@pytest.fixture
def delivery_node(mock_servicenow, mock_graph, mock_settings) -> DeliveryNode:
    """DeliveryNode with mocked connectors."""
    return DeliveryNode(mock_servicenow, mock_graph, mock_settings)


@pytest.fixture
def pipeline_state_delivering() -> dict:
    """Pipeline state ready for delivery (quality gate passed)."""
    return {
        "query_id": "VQ-2026-0001",
        "correlation_id": "test-corr-001",
        "execution_id": "exec-001",
        "source": "email",
        "unified_payload": {
            "subject": "Invoice discrepancy for PO-2026-1234",
            "body": "Vendor reports mismatch.",
            "sender_email": "rajesh.kumar@technova.com",
            "message_id": "AAMkAGI2TG93AAA=",
        },
        "vendor_context": {
            "vendor_profile": {
                "vendor_id": "V-001",
                "vendor_name": "TechNova Solutions",
                "tier": {"tier_name": "GOLD"},
            },
        },
        "analysis_result": {
            "intent_classification": "invoice_inquiry",
            "urgency_level": "HIGH",
            "confidence_score": 0.92,
        },
        "routing_decision": {
            "assigned_team": "finance-ops",
            "category": "billing",
            "priority": "HIGH",
            "sla_target": {"total_hours": 4},
        },
        "draft_response": {
            "draft_type": "RESOLUTION",
            "subject": "Re: Invoice discrepancy [PENDING]",
            "body": "<p>Dear TechNova, your ticket PENDING is being processed.</p>",
            "confidence": 0.89,
            "sources": ["KB-001"],
        },
        "processing_path": "A",
        "status": "DELIVERING",
    }


# ===========================
# Tests: Successful Delivery
# ===========================


class TestDeliverySuccess:
    """Tests for successful ticket creation. Path A halts for admin
    approval (no email send by Delivery), Path B sends the
    acknowledgment automatically."""

    async def test_path_a_creates_ticket_does_not_send_email(
        self, delivery_node, pipeline_state_delivering, mock_servicenow, mock_graph
    ) -> None:
        """Path A: ticket created, but email is held until admin approves."""
        result = await delivery_node.execute(pipeline_state_delivering)

        assert result["ticket_info"] is not None
        assert result["ticket_info"]["ticket_id"] == "INC-0000001"
        mock_servicenow.create_ticket.assert_called_once()
        # Path A halts at PENDING_APPROVAL — DraftApprovalService sends
        # the email later. Delivery itself must not send.
        mock_graph.send_email.assert_not_called()

    async def test_path_a_status_pending_approval(
        self, delivery_node, pipeline_state_delivering
    ) -> None:
        """Path A delivery parks the case at PENDING_APPROVAL."""
        result = await delivery_node.execute(pipeline_state_delivering)
        assert result["status"] == "PENDING_APPROVAL"

    async def test_path_a_persists_draft_with_recipient(
        self, delivery_node, pipeline_state_delivering
    ) -> None:
        """Path A returns draft_response stash with recipient + reply-to.

        DraftApprovalService.approve() reads `_recipient_email` and
        `_reply_to_message_id` to send the approved email, so the
        Delivery node must include them.
        """
        result = await delivery_node.execute(pipeline_state_delivering)

        draft = result["draft_response"]
        assert draft is not None
        assert draft["_recipient_email"] == "rajesh.kumar@technova.com"
        assert draft["_reply_to_message_id"] == "AAMkAGI2TG93AAA="
        # PENDING placeholder must be stamped with the real INC.
        assert "INC-0000001" in draft["subject"]
        assert "PENDING" not in draft["subject"]
        assert "INC-0000001" in draft["body"]

    async def test_path_b_status_awaiting(
        self, delivery_node, pipeline_state_delivering
    ) -> None:
        """Path B delivery sets status to AWAITING_RESOLUTION."""
        pipeline_state_delivering["processing_path"] = "B"
        pipeline_state_delivering["draft_response"]["draft_type"] = "ACKNOWLEDGMENT"

        result = await delivery_node.execute(pipeline_state_delivering)
        assert result["status"] == "AWAITING_RESOLUTION"

    async def test_path_b_sends_email(
        self, delivery_node, pipeline_state_delivering, mock_graph
    ) -> None:
        """Path B sends the acknowledgment automatically."""
        pipeline_state_delivering["processing_path"] = "B"

        await delivery_node.execute(pipeline_state_delivering)

        mock_graph.send_email.assert_called_once()

    async def test_path_b_pending_replaced_in_subject(
        self, delivery_node, pipeline_state_delivering, mock_graph
    ) -> None:
        """PENDING placeholder replaced with real INC number in subject (Path B)."""
        pipeline_state_delivering["processing_path"] = "B"

        await delivery_node.execute(pipeline_state_delivering)

        call_args = mock_graph.send_email.call_args
        assert "INC-0000001" in call_args.kwargs["subject"]
        assert "PENDING" not in call_args.kwargs["subject"]

    async def test_path_b_pending_replaced_in_body(
        self, delivery_node, pipeline_state_delivering, mock_graph
    ) -> None:
        """PENDING placeholder replaced with real INC number in body (Path B)."""
        pipeline_state_delivering["processing_path"] = "B"

        await delivery_node.execute(pipeline_state_delivering)

        call_args = mock_graph.send_email.call_args
        assert "INC-0000001" in call_args.kwargs["body_html"]
        assert "PENDING" not in call_args.kwargs["body_html"]

    async def test_path_b_email_sent_to_sender(
        self, delivery_node, pipeline_state_delivering, mock_graph
    ) -> None:
        """Email sent to the original sender's email address (Path B)."""
        pipeline_state_delivering["processing_path"] = "B"

        await delivery_node.execute(pipeline_state_delivering)

        call_args = mock_graph.send_email.call_args
        assert call_args.kwargs["to"] == "rajesh.kumar@technova.com"

    async def test_path_b_reply_to_message_id_passed(
        self, delivery_node, pipeline_state_delivering, mock_graph
    ) -> None:
        """reply_to_message_id from payload passed to Graph API (Path B)."""
        pipeline_state_delivering["processing_path"] = "B"

        await delivery_node.execute(pipeline_state_delivering)

        call_args = mock_graph.send_email.call_args
        assert call_args.kwargs["reply_to_message_id"] == "AAMkAGI2TG93AAA="


# ===========================
# Tests: Ticket Creation Failure
# ===========================


class TestTicketCreationFailure:
    """Tests for ServiceNow ticket creation failures."""

    async def test_ticket_failure_returns_delivery_failed(
        self, delivery_node, pipeline_state_delivering, mock_servicenow, mock_graph
    ) -> None:
        """ServiceNow error results in DELIVERY_FAILED status."""
        mock_servicenow.create_ticket.side_effect = ServiceNowConnectorError(
            "ServiceNow API down"
        )

        result = await delivery_node.execute(pipeline_state_delivering)

        assert result["status"] == "DELIVERY_FAILED"
        assert result["ticket_info"] is None
        # Email should NOT be sent if ticket creation fails
        mock_graph.send_email.assert_not_called()


# ===========================
# Tests: Email Send Failure
# ===========================


class TestEmailSendFailure:
    """Tests for Graph API email send failures.

    Only Path B (and resolution-mode) actually sends from the Delivery
    node — Path A holds the email for admin approval, so an email
    failure isn't reachable on that path here. We exercise Path B.
    """

    async def test_email_failure_returns_delivery_failed(
        self, delivery_node, pipeline_state_delivering, mock_graph
    ) -> None:
        """Graph API error results in DELIVERY_FAILED (ticket still created)."""
        pipeline_state_delivering["processing_path"] = "B"
        mock_graph.send_email.side_effect = GraphAPIError("/sendMail", 500)

        result = await delivery_node.execute(pipeline_state_delivering)

        assert result["status"] == "DELIVERY_FAILED"
        # Ticket was created before email failed
        assert result["ticket_info"] is not None
        assert result["ticket_info"]["ticket_id"] == "INC-0000001"


# ===========================
# Tests: Edge Cases
# ===========================


class TestDeliveryEdgeCases:
    """Tests for edge cases."""

    async def test_portal_no_sender_email_skips_send(
        self, delivery_node, pipeline_state_delivering, mock_graph
    ) -> None:
        """Path B portal submissions without sender_email skip email send.

        The vendor_profile in this fixture also has no email_address,
        so there's nothing to send to. Delivery treats that as a
        non-fatal skip — ticket is still created, status flips to
        AWAITING_RESOLUTION, and no Graph API call is made.
        """
        pipeline_state_delivering["processing_path"] = "B"
        pipeline_state_delivering["unified_payload"]["sender_email"] = ""

        result = await delivery_node.execute(pipeline_state_delivering)

        assert result["status"] == "AWAITING_RESOLUTION"
        mock_graph.send_email.assert_not_called()

    async def test_ticket_request_uses_routing_data(
        self, delivery_node, pipeline_state_delivering, mock_servicenow
    ) -> None:
        """Ticket creation uses routing decision fields."""
        await delivery_node.execute(pipeline_state_delivering)

        call_args = mock_servicenow.create_ticket.call_args
        request = call_args.args[0]
        assert request.assigned_team == "finance-ops"
        assert request.category == "billing"
        assert request.priority == "HIGH"
        assert request.sla_hours == 4
