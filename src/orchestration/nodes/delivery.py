"""Module: orchestration/nodes/delivery.py

Delivery Node — Step 12 in the VQMS pipeline.

The final pipeline node. Creates a ServiceNow incident ticket,
replaces the "PENDING" placeholder in the email draft with the
real INC-XXXXXXX ticket number, then sends the email to the
vendor via Microsoft Graph API.

Execution order:
1. Create ServiceNow ticket → get INC-XXXXXXX
2. Replace "PENDING" with INC-XXXXXXX in subject and body
3. Send email via Graph API
4. Update status to RESOLVED (Path A) or AWAITING_RESOLUTION (Path B)

Path differences:
- Path A (RESOLUTION): Ticket for monitoring. Status → RESOLVED.
- Path B (ACKNOWLEDGMENT): Ticket for investigation. Status → AWAITING_RESOLUTION.

Corresponds to Step 12 in the VQMS Architecture Document.
"""

from __future__ import annotations

import structlog

from adapters.graph_api import GraphAPIConnector
from adapters.servicenow import ServiceNowConnector, ServiceNowConnectorError
from config.settings import Settings
from models.ticket import TicketCreateRequest
from models.workflow import PipelineState
from utils.exceptions import GraphAPIError
from utils.helpers import TimeHelper

logger = structlog.get_logger(__name__)

# Placeholder used in draft emails before ticket creation
TICKET_PLACEHOLDER = "PENDING"


class DeliveryNode:
    """Creates ServiceNow ticket and sends email to vendor (Step 12).

    Two-phase delivery:
    1. ServiceNow ticket creation → real INC-XXXXXXX number
    2. Graph API email send → PENDING replaced with INC number
    """

    def __init__(
        self,
        servicenow: ServiceNowConnector,
        graph_api: GraphAPIConnector,
        settings: Settings,
    ) -> None:
        """Initialize with connectors and settings.

        Args:
            servicenow: ServiceNow connector for ticket creation.
            graph_api: Graph API connector for email delivery.
            settings: Application settings.
        """
        self._servicenow = servicenow
        self._graph_api = graph_api
        self._settings = settings

    async def execute(self, state: PipelineState) -> PipelineState:
        """Create ticket, replace placeholder, send email.

        Args:
            state: Current pipeline state with draft_response,
                   routing_decision, and vendor context.

        Returns:
            Updated state with ticket_info and final status.
        """
        correlation_id = state.get("correlation_id", "")
        query_id = state.get("query_id", "")
        processing_path = state.get("processing_path", "A")
        draft = state.get("draft_response") or {}
        routing = state.get("routing_decision") or {}
        vendor_context = state.get("vendor_context") or {}
        payload = state.get("unified_payload") or {}
        vendor_profile = vendor_context.get("vendor_profile", {})

        logger.info(
            "Delivery started",
            step="delivery",
            query_id=query_id,
            processing_path=processing_path,
            correlation_id=correlation_id,
        )

        # ----- Phase 1: Create ServiceNow ticket -----
        ticket_info = await self._create_ticket(
            query_id=query_id,
            correlation_id=correlation_id,
            subject=payload.get("subject", "Vendor Query"),
            description=payload.get("body", ""),
            priority=routing.get("priority", "MEDIUM"),
            assigned_team=routing.get("assigned_team", "general-support"),
            vendor_id=vendor_profile.get("vendor_id"),
            vendor_name=vendor_profile.get("vendor_name"),
            category=routing.get("category", "general"),
            sla_hours=routing.get("sla_target", {}).get("total_hours", 24),
        )

        if ticket_info is None:
            # Ticket creation failed — cannot deliver
            logger.error(
                "Delivery failed — ticket creation unsuccessful",
                step="delivery",
                query_id=query_id,
                correlation_id=correlation_id,
            )
            return {
                "ticket_info": None,
                "status": "DELIVERY_FAILED",
                "error": "ServiceNow ticket creation failed",
                "updated_at": TimeHelper.ist_now().isoformat(),
            }

        ticket_id = ticket_info["ticket_id"]

        # ----- Phase 2: Replace PENDING with real ticket number -----
        final_subject = draft.get("subject", "").replace(TICKET_PLACEHOLDER, ticket_id)
        final_body = draft.get("body", "").replace(TICKET_PLACEHOLDER, ticket_id)

        # ----- Phase 3: Send email via Graph API -----
        sender_email = payload.get("sender_email", "")
        reply_to_id = payload.get("message_id")

        email_sent = await self._send_email(
            to=sender_email,
            subject=final_subject,
            body_html=final_body,
            reply_to_message_id=reply_to_id,
            correlation_id=correlation_id,
            query_id=query_id,
        )

        if not email_sent:
            logger.error(
                "Delivery failed — email send unsuccessful",
                step="delivery",
                query_id=query_id,
                ticket_id=ticket_id,
                correlation_id=correlation_id,
            )
            return {
                "ticket_info": ticket_info,
                "status": "DELIVERY_FAILED",
                "error": "Graph API email send failed",
                "updated_at": TimeHelper.ist_now().isoformat(),
            }

        # ----- Phase 4: Set final status -----
        # Path A: AI resolved, ticket for monitoring → RESOLVED
        # Path B: Human must investigate → AWAITING_RESOLUTION
        final_status = "RESOLVED" if processing_path == "A" else "AWAITING_RESOLUTION"

        logger.info(
            "Delivery complete",
            step="delivery",
            query_id=query_id,
            ticket_id=ticket_id,
            processing_path=processing_path,
            final_status=final_status,
            email_sent=True,
            correlation_id=correlation_id,
        )

        return {
            "ticket_info": ticket_info,
            "status": final_status,
            "updated_at": TimeHelper.ist_now().isoformat(),
        }

    async def _create_ticket(
        self,
        *,
        query_id: str,
        correlation_id: str,
        subject: str,
        description: str,
        priority: str,
        assigned_team: str,
        vendor_id: str | None,
        vendor_name: str | None,
        category: str,
        sla_hours: int,
    ) -> dict | None:
        """Create a ServiceNow incident ticket.

        Returns:
            Dict with ticket_id, query_id, status, created_at,
            assigned_team, sla_deadline. None on failure.
        """
        try:
            request = TicketCreateRequest(
                query_id=query_id,
                correlation_id=correlation_id,
                subject=subject,
                description=description,
                priority=priority,
                assigned_team=assigned_team,
                vendor_id=vendor_id,
                vendor_name=vendor_name,
                category=category,
                sla_hours=sla_hours,
            )
            ticket = await self._servicenow.create_ticket(
                request, correlation_id=correlation_id
            )
            return ticket.model_dump()
        except ServiceNowConnectorError as exc:
            logger.error(
                "ServiceNow ticket creation failed",
                step="delivery",
                query_id=query_id,
                error=str(exc),
                correlation_id=correlation_id,
            )
            return None

    async def _send_email(
        self,
        *,
        to: str,
        subject: str,
        body_html: str,
        reply_to_message_id: str | None,
        correlation_id: str,
        query_id: str,
    ) -> bool:
        """Send email via Graph API.

        Returns True on success, False on failure.
        """
        if not to:
            logger.warning(
                "No recipient email — skipping email send",
                step="delivery",
                query_id=query_id,
                correlation_id=correlation_id,
            )
            # Still return True: ticket was created, email just has no recipient
            # This happens for portal submissions that don't have a sender email
            return True

        try:
            await self._graph_api.send_email(
                to=to,
                subject=subject,
                body_html=body_html,
                reply_to_message_id=reply_to_message_id,
                correlation_id=correlation_id,
            )
            return True
        except GraphAPIError as exc:
            logger.error(
                "Graph API email send failed",
                step="delivery",
                query_id=query_id,
                recipient=to,
                error=str(exc),
                correlation_id=correlation_id,
            )
            return False
