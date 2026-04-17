"""Module: adapters/servicenow/ticket_create.py

Ticket creation via the ServiceNow Table API.

Handles creating new incident records in ServiceNow with
VQMS field mapping. Used by the Delivery node (Step 12)
to create tickets for both Path A and Path B.
"""

from __future__ import annotations

import structlog

from adapters.servicenow.client import PRIORITY_MAP, ServiceNowConnectorError
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
        # Map VQMS priority to ServiceNow numeric priority
        snow_priority = PRIORITY_MAP.get(request.priority, "3")

        # Build the ServiceNow incident payload
        incident_data = {
            "short_description": request.subject,
            "description": request.description,
            "priority": snow_priority,
            "assignment_group": request.assigned_team,
            "category": request.category,
            "u_query_id": request.query_id,
            "u_correlation_id": request.correlation_id,
            "u_vendor_id": request.vendor_id or "",
            "u_vendor_name": request.vendor_name or "",
            "u_sla_hours": str(request.sla_hours),
        }

        logger.info(
            "Creating ServiceNow incident",
            tool="servicenow",
            query_id=request.query_id,
            priority=snow_priority,
            assigned_team=request.assigned_team,
            correlation_id=correlation_id,
        )

        try:
            client = self._get_client()
            url = f"{self._base_url}/api/now/table/incident"
            response = await client.post(url, json=incident_data)
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

        now = TimeHelper.ist_now()
        sla_deadline = TimeHelper.ist_now_offset(hours=request.sla_hours)

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
