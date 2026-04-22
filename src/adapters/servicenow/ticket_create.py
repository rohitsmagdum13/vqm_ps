"""Module: adapters/servicenow/ticket_create.py

Ticket creation via the ServiceNow Table API.

Handles creating new incident records in ServiceNow with
VQMS field mapping. Used by the Delivery node (Step 12)
to create tickets for both Path A and Path B.
"""

from __future__ import annotations

import structlog

from adapters.servicenow.client import (
    IMPACT_URGENCY_MAP,
    PRIORITY_MAP,
    SERVICENOW_DATETIME_FORMAT,
    ServiceNowConnectorError,
)
from models.ticket import TicketCreateRequest, TicketInfo
from utils.decorators import log_service_call
from utils.helpers import TimeHelper

logger = structlog.get_logger(__name__)


class TicketCreateMixin:
    """Ticket creation methods for the ServiceNow connector.

    Mixed into ServiceNowConnector. Expects self._get_client()
    and self._base_url from ServiceNowClient.
    """

    @log_service_call
    async def create_ticket(
        self,
        request: TicketCreateRequest,
        *,
        correlation_id: str = "",
    ) -> TicketInfo:
        """Create a new incident ticket in ServiceNow.

        POST /api/now/table/incident with VQMS fields mapped
        to ServiceNow incident fields.

        Args:
            request: Ticket creation request with all required fields.
            correlation_id: Tracing ID.

        Returns:
            TicketInfo with the ServiceNow incident number and metadata.

        Raises:
            ServiceNowConnectorError: If ticket creation fails.
        """
        # Map VQMS priority to ServiceNow numeric priority (1-4) and the
        # matching (impact, urgency) pair. We send all three so the Priority
        # column matches what VQMS decided AND ServiceNow's Impact/Urgency
        # widgets, dashboards, and filters all have valid data.
        snow_priority = PRIORITY_MAP.get(request.priority, "3")
        snow_impact, snow_urgency = IMPACT_URGENCY_MAP.get(
            request.priority, ("2", "2")
        )

        # Compute ticket-open + SLA deadline timestamps once, use them for
        # both the ServiceNow payload (due_date, u_sla_deadline) and the
        # returned TicketInfo so all downstream consumers see the same values.
        now = TimeHelper.ist_now()
        sla_deadline = TimeHelper.ist_now_offset(hours=request.sla_hours)
        sla_deadline_str = sla_deadline.strftime(SERVICENOW_DATETIME_FORMAT)

        # Pass the VQMS-routed team through as-is. No default-group fallback,
        # no pre-lookup. With sysparm_input_display_value=true, ServiceNow
        # resolves the name to a sys_id when a matching sys_user_group exists;
        # when it doesn't, the reference stays unresolved but the incident
        # is still created and is visible under "Incident → All" in the UI.
        assignment_group = (request.assigned_team or "").strip()

        # Resolve caller_id to the authenticated ServiceNow user's display
        # name ("System Administrator" for the "admin" account). This is
        # what puts the ticket into the default "Self Service" view, which
        # filters by Caller = <logged-in user>. The lookup is cached, so
        # this only hits ServiceNow once per process.
        caller_user_name = (
            getattr(self._settings, "servicenow_username", "") or ""
        ).strip()
        caller_display = await self.resolve_user_display_name(caller_user_name)

        # One-line VQMS provenance breadcrumb on the ServiceNow Activity
        # log. This is internal-only (work_notes are not shown to the
        # caller), so it's safe to include correlation and vendor IDs.
        # Gives ops an instant "this came from VQMS" trail without having
        # to cross-reference the u_* custom fields.
        vendor_label = request.vendor_name or request.vendor_id or "unknown"
        work_notes = (
            "Created by VQMS\n"
            f"- query_id: {request.query_id}\n"
            f"- correlation_id: {request.correlation_id}\n"
            f"- vendor: {vendor_label}"
            + (f" ({request.vendor_id})" if request.vendor_name and request.vendor_id else "")
            + "\n"
            f"- priority: {request.priority} (SLA {request.sla_hours}h, "
            f"deadline {sla_deadline_str})\n"
            f"- routed team: {assignment_group or '(unresolved)'}"
        )

        # Build the ServiceNow incident payload. Fields are grouped so the
        # intent of each block is obvious at a glance.
        incident_data = {
            # Content
            "short_description": request.subject,
            "description": request.description,
            # Classification
            "category": request.category,
            "priority": snow_priority,
            "impact": snow_impact,
            "urgency": snow_urgency,
            # Lifecycle — every VQMS-created ticket starts as New ("1").
            # Subsequent state changes happen via update_ticket_status().
            "state": "1",
            # Routing — assignment_group comes from VQMS routing; we leave
            # assigned_to blank so the team can self-assign after triage.
            "assignment_group": assignment_group,
            # People + origin
            "caller_id": caller_display,
            "contact_type": "email",
            # SLA — due_date lets ServiceNow's "Overdue" filter and SLA widget
            # work without us having to configure a ServiceNow SLA definition.
            "due_date": sla_deadline_str,
            # Internal breadcrumb on the Activity log — never shown to caller
            "work_notes": work_notes,
            # VQMS-specific custom fields. ServiceNow auto-prefixed these
            # with u_vqms_* when the columns were created from labels like
            # "VQMS Query ID" -- the column names in sys_dictionary are
            # u_vqms_query_id, u_vqms_correlation_id, etc. Sending the
            # shorter u_* names causes ServiceNow to silently drop them.
            "u_vqms_query_id": request.query_id,
            "u_vqms_correlation_id": request.correlation_id,
            "u_vqms_vendor_id": request.vendor_id or "",
            "u_vqms_vendor_name": request.vendor_name or "",
            "u_vqms_sla_hours": str(request.sla_hours),
            "u_vqms_sla_deadline": sla_deadline_str,
        }

        logger.info(
            "Creating ServiceNow incident",
            tool="servicenow",
            query_id=request.query_id,
            priority=snow_priority,
            assignment_group=assignment_group,
            caller_id=caller_display,
            correlation_id=correlation_id,
        )

        try:
            client = self._get_client()
            url = f"{self._base_url}/api/now/table/incident"
            # sysparm_input_display_value=true lets ServiceNow resolve
            # reference fields (assignment_group, caller_id, category) by
            # their human-readable display name, so we don't have to
            # pre-lookup sys_ids for every value VQMS might route.
            response = await client.post(
                url,
                json=incident_data,
                params={"sysparm_input_display_value": "true"},
            )
            response.raise_for_status()
            record = response.json().get("result", {})
        except Exception as exc:
            logger.exception(
                "ServiceNow incident creation failed",
                tool="servicenow",
                query_id=request.query_id,
                correlation_id=correlation_id,
            )
            raise ServiceNowConnectorError(
                f"Failed to create incident for {request.query_id}: {exc}"
            ) from exc

        # Extract fields from the created record
        ticket_id = record.get("number", "")
        sys_id = record.get("sys_id", "")

        logger.info(
            "ServiceNow incident created",
            tool="servicenow",
            ticket_id=ticket_id,
            sys_id=sys_id,
            query_id=request.query_id,
            correlation_id=correlation_id,
        )

        return TicketInfo(
            ticket_id=ticket_id,
            query_id=request.query_id,
            status="New",
            created_at=now,
            assigned_team=request.assigned_team,
            sla_deadline=sla_deadline,
        )
