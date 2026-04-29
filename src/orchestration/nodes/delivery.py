"""Module: orchestration/nodes/delivery.py

Delivery Node — Step 12 in the VQMS pipeline.

The final pipeline node. Creates a ServiceNow incident ticket,
replaces the "PENDING" placeholder in the email draft with the
real ServiceNow incident number (e.g. INC0010001), then sends
the email to the vendor via Microsoft Graph API.

Execution order:
1. Create ServiceNow ticket → get real incident number (INC0010001)
2. Replace "PENDING" with the incident number in subject and body
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
from events.eventbridge import EventBridgeConnector
from models.ticket import TicketCreateRequest
from models.workflow import PipelineState
from utils.exceptions import GraphAPIError
from utils.helpers import TimeHelper
from utils.trail import record_node

logger = structlog.get_logger(__name__)

# Placeholder used in draft emails before ticket creation
TICKET_PLACEHOLDER = "PENDING"


class DeliveryNode:
    """Creates ServiceNow ticket and sends email to vendor (Step 12).

    Two-phase delivery:
    1. ServiceNow ticket creation → real incident number (e.g. INC0010001)
    2. Graph API email send → PENDING replaced with the real number
    """

    def __init__(
        self,
        servicenow: ServiceNowConnector,
        graph_api: GraphAPIConnector,
        settings: Settings,
        eventbridge: EventBridgeConnector | None = None,
        closure_service=None,
    ) -> None:
        """Initialize with connectors and settings.

        Args:
            servicenow: ServiceNow connector for ticket creation / status updates.
            graph_api: Graph API connector for email delivery.
            settings: Application settings.
            eventbridge: Optional EventBridge connector. When present and the
                delivery is resolution-mode, publishes ResolutionPrepared.
            closure_service: Optional Phase 6 ClosureService. When present,
                register_resolution_sent is called after a successful send so
                the auto-close timer starts.
        """
        self._servicenow = servicenow
        self._graph_api = graph_api
        self._settings = settings
        self._eventbridge = eventbridge
        self._closure_service = closure_service

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
        resolution_mode = bool(state.get("resolution_mode"))

        logger.info(
            "Delivery started",
            step="delivery",
            query_id=query_id,
            processing_path=processing_path,
            resolution_mode=resolution_mode,
            correlation_id=correlation_id,
        )

        if resolution_mode:
            return await self._deliver_resolution_mode(
                state=state,
                correlation_id=correlation_id,
                query_id=query_id,
                draft=draft,
                vendor_context=vendor_context,
                payload=payload,
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
            await record_node(
                query_id=query_id,
                correlation_id=correlation_id,
                step_name="delivery",
                status="failed",
                details={
                    "processing_path": processing_path,
                    "error_type": "ticket_creation_failed",
                },
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

        # Resolve recipient + reply-to once. Used either to send (Path B)
        # or stashed on the draft for the admin approval service to send
        # later (Path A). Three sources, in order:
        #   1. Vendor's official contact email from Salesforce profile
        #   2. payload.sender_email (top-level — older payload shape)
        #   3. payload.metadata.sender_email (where EmailIntakeService
        #      actually puts it today — UnifiedQueryPayload.metadata is
        #      a free-form dict, sender_email is nested there)
        metadata = payload.get("metadata") or {}
        recipient = (
            vendor_profile.get("primary_contact_email")
            or payload.get("sender_email", "")
            or metadata.get("sender_email", "")
        )
        reply_to_id = (
            payload.get("message_id")
            or metadata.get("message_id")
        )
        cc_list = self._build_cc_list(metadata=metadata, recipient=recipient)

        # Build the persisted draft snapshot. The leading-underscore
        # fields are stripped before the admin UI sees them; the
        # DraftApprovalService reads `_recipient_email` /
        # `_reply_to_message_id` / `_cc_emails` when sending an approved
        # draft.
        draft_snapshot = {
            **draft,
            "subject": final_subject,
            "body": final_body,
            "_recipient_email": recipient,
            "_reply_to_message_id": reply_to_id,
            "_cc_emails": cc_list,
        }

        # ----- Path A: halt at PENDING_APPROVAL, do NOT send -----
        # Per VQMS_Logic_Flow.md, Path A drafts a full reply that an
        # admin must approve before it leaves the building. The email
        # is sent later by DraftApprovalService.approve(). The draft
        # snapshot above carries the recipient + reply-to it needs.
        if processing_path == "A":
            logger.info(
                "Path A draft parked for admin approval",
                step="delivery",
                query_id=query_id,
                ticket_id=ticket_id,
                recipient_present=bool(recipient),
                correlation_id=correlation_id,
            )
            await record_node(
                query_id=query_id,
                correlation_id=correlation_id,
                step_name="delivery",
                status="success",
                details={
                    "processing_path": "A",
                    "ticket_id": ticket_id,
                    "final_status": "PENDING_APPROVAL",
                    "email_sent": False,
                    "halted_for_approval": True,
                },
            )
            return {
                "ticket_info": ticket_info,
                "draft_response": draft_snapshot,
                "status": "PENDING_APPROVAL",
                "updated_at": TimeHelper.ist_now().isoformat(),
            }

        # ----- Path B: send acknowledgment automatically -----
        email_sent = await self._send_email(
            to=recipient,
            subject=final_subject,
            body_html=final_body,
            cc=cc_list,
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
            await record_node(
                query_id=query_id,
                correlation_id=correlation_id,
                step_name="delivery",
                status="failed",
                details={
                    "processing_path": processing_path,
                    "ticket_id": ticket_id,
                    "error_type": "email_send_failed",
                },
            )
            return {
                "ticket_info": ticket_info,
                "draft_response": draft_snapshot,
                "status": "DELIVERY_FAILED",
                "error": "Graph API email send failed",
                "updated_at": TimeHelper.ist_now().isoformat(),
            }

        # `email_sent=True` from `_send_email` collapses two outcomes:
        # actually sent vs skipped because no recipient was on file.
        # Surface the distinction on the timeline so admins can tell.
        email_skipped_no_recipient = not bool(recipient)
        final_status = "AWAITING_RESOLUTION"
        logger.info(
            "Delivery complete",
            step="delivery",
            query_id=query_id,
            ticket_id=ticket_id,
            processing_path=processing_path,
            final_status=final_status,
            email_sent=not email_skipped_no_recipient,
            email_skipped_no_recipient=email_skipped_no_recipient,
            correlation_id=correlation_id,
        )

        await record_node(
            query_id=query_id,
            correlation_id=correlation_id,
            step_name="delivery",
            status="success",
            details={
                "processing_path": processing_path,
                "ticket_id": ticket_id,
                "final_status": final_status,
                "email_sent": not email_skipped_no_recipient,
                "email_skipped_no_recipient": email_skipped_no_recipient,
            },
        )

        return {
            "ticket_info": ticket_info,
            "draft_response": draft_snapshot,
            "status": final_status,
            "updated_at": TimeHelper.ist_now().isoformat(),
        }

    async def _deliver_resolution_mode(
        self,
        *,
        state: PipelineState,
        correlation_id: str,
        query_id: str,
        draft: dict,
        vendor_context: dict,
        payload: dict,
    ) -> PipelineState:
        """Phase 6 Step 15 delivery — reuse existing ticket, skip creation.

        The acknowledgment-email delivery earlier in the pipeline already
        created the ServiceNow incident. Now we just:
          1. Pull the existing ticket_info from state.
          2. Send the drafted resolution email via Graph API.
          3. Update ServiceNow status to AWAITING_VENDOR_CONFIRMATION.
          4. Publish ResolutionPrepared (non-critical).
          5. Register with ClosureService so the auto-close timer starts.
        """
        ticket_info = state.get("ticket_info") or {}
        ticket_id = ticket_info.get("ticket_number") or ticket_info.get("ticket_id", "")
        if not ticket_id:
            logger.error(
                "Resolution-mode delivery missing ticket_number",
                step="delivery",
                query_id=query_id,
                correlation_id=correlation_id,
            )
            await record_node(
                query_id=query_id,
                correlation_id=correlation_id,
                step_name="delivery",
                action="resolution_mode",
                status="failed",
                details={
                    "processing_path": "B",
                    "error_type": "missing_ticket_number",
                },
            )
            return {
                "status": "DELIVERY_FAILED",
                "error": "ticket_number missing in resolution_mode",
                "updated_at": TimeHelper.ist_now().isoformat(),
            }

        final_subject = draft.get("subject", "").replace(TICKET_PLACEHOLDER, ticket_id)
        final_body = draft.get("body", "").replace(TICKET_PLACEHOLDER, ticket_id)

        vendor_profile = vendor_context.get("vendor_profile", {})
        # Same three-source resolution as the main delivery path —
        # vendor profile, top-level payload, then metadata.
        metadata = payload.get("metadata") or {}
        recipient = (
            vendor_profile.get("primary_contact_email")
            or payload.get("sender_email", "")
            or metadata.get("sender_email", "")
        )
        reply_to_id = (
            payload.get("message_id")
            or metadata.get("message_id")
        )
        cc_list = self._build_cc_list(metadata=metadata, recipient=recipient)

        email_sent = await self._send_email(
            to=recipient,
            subject=final_subject,
            body_html=final_body,
            cc=cc_list,
            reply_to_message_id=reply_to_id,
            correlation_id=correlation_id,
            query_id=query_id,
        )
        if not email_sent:
            await record_node(
                query_id=query_id,
                correlation_id=correlation_id,
                step_name="delivery",
                action="resolution_mode",
                status="failed",
                details={
                    "processing_path": "B",
                    "ticket_id": ticket_id,
                    "error_type": "email_send_failed",
                },
            )
            return {
                "status": "DELIVERY_FAILED",
                "error": "Resolution-mode email send failed",
                "updated_at": TimeHelper.ist_now().isoformat(),
            }

        # Update ServiceNow status — non-critical, log and continue on failure
        try:
            await self._servicenow.update_ticket_status(
                ticket_id,
                "AWAITING_VENDOR_CONFIRMATION",
                work_notes="Resolution email sent to vendor",
                correlation_id=correlation_id,
            )
        except Exception:
            logger.warning(
                "Failed to update ServiceNow status to AWAITING_VENDOR_CONFIRMATION",
                step="delivery",
                ticket_id=ticket_id,
                correlation_id=correlation_id,
            )

        # Publish ResolutionPrepared — non-critical, log and continue
        if self._eventbridge is not None:
            try:
                await self._eventbridge.publish_event(
                    "ResolutionPrepared",
                    {
                        "query_id": query_id,
                        "ticket_id": ticket_id,
                    },
                    correlation_id=correlation_id,
                )
            except Exception:
                logger.warning(
                    "Failed to publish ResolutionPrepared event",
                    step="delivery",
                    query_id=query_id,
                    correlation_id=correlation_id,
                )

        await self._register_resolution_sent(query_id, correlation_id)

        email_skipped_no_recipient = not bool(recipient)
        logger.info(
            "Resolution-mode delivery complete",
            step="delivery",
            query_id=query_id,
            ticket_id=ticket_id,
            email_sent=not email_skipped_no_recipient,
            email_skipped_no_recipient=email_skipped_no_recipient,
            correlation_id=correlation_id,
        )
        await record_node(
            query_id=query_id,
            correlation_id=correlation_id,
            step_name="delivery",
            action="resolution_mode",
            status="success",
            details={
                "processing_path": "B",
                "ticket_id": ticket_id,
                "final_status": "RESOLVED",
                "email_sent": not email_skipped_no_recipient,
                "email_skipped_no_recipient": email_skipped_no_recipient,
            },
        )
        return {
            "status": "RESOLVED",
            "updated_at": TimeHelper.ist_now().isoformat(),
        }

    async def _register_resolution_sent(
        self, query_id: str, correlation_id: str
    ) -> None:
        """Call ClosureService.register_resolution_sent if available.

        Non-critical: logs and continues on failure so closure tracking
        issues cannot roll back a successful delivery.
        """
        if self._closure_service is None or not query_id:
            return
        try:
            await self._closure_service.register_resolution_sent(
                query_id=query_id, correlation_id=correlation_id
            )
        except Exception:
            logger.warning(
                "Failed to register resolution_sent with ClosureService",
                step="delivery",
                query_id=query_id,
                correlation_id=correlation_id,
            )

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
        cc: list[str] | None = None,
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
                cc=cc or None,
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

    def _build_cc_list(
        self, *, metadata: dict, recipient: str
    ) -> list[str]:
        """Build the CC list for the outbound reply.

        Combines the original CC list with any "extra" To recipients
        (i.e. anyone in To: besides the vendor's own address and our
        shared mailbox), de-duplicates case-insensitively, and drops
        the primary recipient + the shared mailbox so the reply does
        not bounce back to itself or duplicate the To: line.

        BCC is not handled here — Graph never returns bccRecipients on
        inbound mail, so there is nothing to replicate.
        """
        cc_emails = list(metadata.get("cc_emails", []) or [])
        extra_to_emails = list(metadata.get("extra_to_emails", []) or [])

        # Anyone who was on the original To: line (besides the vendor and
        # our own mailbox) becomes a CC on the reply. This keeps internal
        # collaborators looped in without elevating them to the To: line.
        own_mailbox = (self._settings.graph_api_mailbox or "").lower()
        recipient_lc = (recipient or "").lower()

        seen: set[str] = set()
        result: list[str] = []
        for addr in cc_emails + extra_to_emails:
            if not addr:
                continue
            lower = addr.lower()
            if lower in (recipient_lc, own_mailbox):
                continue
            if lower in seen:
                continue
            seen.add(lower)
            result.append(addr)
        return result
