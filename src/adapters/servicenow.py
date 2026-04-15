"""Module: adapters/servicenow.py

ServiceNow ITSM connector for VQMS.

Handles ticket creation, status updates, and work note retrieval
via the ServiceNow Table API (REST). Used by the Delivery node
(Step 12) to create incidents and by the SLA monitor to track
ticket state.

Uses httpx.AsyncClient for native async HTTP — same pattern as
graph_api.py. Avoids pysnow because its python-magic dependency
causes native DLL crashes on Windows.

Usage:
    from adapters.servicenow import ServiceNowConnector
    from config.settings import get_settings

    snow = ServiceNowConnector(get_settings())
    ticket = await snow.create_ticket(request, correlation_id="abc-123")
    await snow.update_ticket_status("INC-0000001", "In Progress")
    await snow.close()
"""

from __future__ import annotations

import httpx
import structlog

from config.settings import Settings
from models.ticket import TicketCreateRequest, TicketInfo
from utils.decorators import log_service_call
from utils.helpers import TimeHelper

logger = structlog.get_logger(__name__)

# ServiceNow priority mapping: VQMS priority string -> ServiceNow numeric value
# ServiceNow uses 1=Critical, 2=High, 3=Moderate, 4=Low
PRIORITY_MAP = {
    "CRITICAL": "1",
    "HIGH": "2",
    "MEDIUM": "3",
    "LOW": "4",
}


class ServiceNowConnectorError(Exception):
    """Raised when a ServiceNow API call fails."""


class ServiceNowConnector:
    """ServiceNow ITSM connector for ticket operations.

    Uses httpx.AsyncClient with basic auth for the ServiceNow
    Table API. The client is created lazily on first API call
    to avoid connection errors during startup.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize with application settings.

        Does NOT connect to ServiceNow yet. The httpx client is
        created lazily on first use via _get_client().

        Args:
            settings: Application settings with ServiceNow config.
        """
        self._settings = settings
        self._client: httpx.AsyncClient | None = None
        self._base_url: str = ""

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the httpx async client.

        Lazy initialization — the client is created on first call
        and cached for subsequent calls.

        Returns:
            Configured httpx.AsyncClient with basic auth.

        Raises:
            ServiceNowConnectorError: If required credentials are missing.
        """
        if self._client is not None:
            return self._client

        instance_url = self._settings.servicenow_instance_url
        if not instance_url:
            raise ServiceNowConnectorError(
                "SERVICENOW_INSTANCE_URL is not configured"
            )

        username = self._settings.servicenow_username
        password = self._settings.servicenow_password

        if not username or not password:
            raise ServiceNowConnectorError(
                "SERVICENOW_USERNAME and SERVICENOW_PASSWORD are required"
            )

        # Strip trailing slash from instance URL
        self._base_url = instance_url.rstrip("/")

        self._client = httpx.AsyncClient(
            auth=(username, password),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

        return self._client

    async def close(self) -> None:
        """Close the httpx client. Call during app shutdown."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

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

    @log_service_call
    async def update_ticket_status(
        self,
        ticket_id: str,
        new_status: str,
        work_notes: str = "",
        *,
        correlation_id: str = "",
    ) -> dict:
        """Update an existing ServiceNow incident status.

        Two-step: GET by number to find sys_id, then PATCH to update.

        Args:
            ticket_id: ServiceNow incident number (INC-XXXXXXX).
            new_status: New status string (e.g., "In Progress", "Resolved").
            work_notes: Optional work notes to add to the ticket.
            correlation_id: Tracing ID.

        Returns:
            Dict with ticket_id and updated status.

        Raises:
            ServiceNowConnectorError: If the update fails.
        """
        logger.info(
            "Updating ServiceNow incident",
            tool="servicenow",
            ticket_id=ticket_id,
            new_status=new_status,
            correlation_id=correlation_id,
        )

        try:
            # Step 1: Find sys_id by incident number
            sys_id = await self._find_sys_id(ticket_id)
            if not sys_id:
                raise ServiceNowConnectorError(
                    f"Incident {ticket_id} not found in ServiceNow"
                )

            # Step 2: PATCH to update
            update_data: dict = {"state": _status_to_state(new_status)}
            if work_notes:
                update_data["work_notes"] = work_notes

            client = self._get_client()
            url = f"{self._base_url}/api/now/table/incident/{sys_id}"
            response = await client.patch(url, json=update_data)
            response.raise_for_status()
        except ServiceNowConnectorError:
            raise
        except Exception as exc:
            logger.exception(
                "ServiceNow incident update failed",
                tool="servicenow",
                ticket_id=ticket_id,
                correlation_id=correlation_id,
            )
            raise ServiceNowConnectorError(
                f"Failed to update incident {ticket_id}: {exc}"
            ) from exc

        logger.info(
            "ServiceNow incident updated",
            tool="servicenow",
            ticket_id=ticket_id,
            new_status=new_status,
            correlation_id=correlation_id,
        )

        return {
            "ticket_id": ticket_id,
            "status": new_status,
        }

    @log_service_call
    async def get_ticket(
        self,
        ticket_id: str,
        *,
        correlation_id: str = "",
    ) -> dict | None:
        """Fetch a single ServiceNow incident by ticket number.

        GET /api/now/table/incident?number={ticket_id}&sysparm_limit=1

        Args:
            ticket_id: ServiceNow incident number (INC-XXXXXXX).
            correlation_id: Tracing ID.

        Returns:
            Dict with ticket fields, or None if not found.
        """
        try:
            client = self._get_client()
            url = f"{self._base_url}/api/now/table/incident"
            response = await client.get(
                url,
                params={"number": ticket_id, "sysparm_limit": "1"},
            )
            response.raise_for_status()
            results = response.json().get("result", [])
        except Exception:
            logger.exception(
                "ServiceNow incident fetch failed",
                tool="servicenow",
                ticket_id=ticket_id,
                correlation_id=correlation_id,
            )
            return None

        if not results:
            logger.info(
                "ServiceNow incident not found",
                tool="servicenow",
                ticket_id=ticket_id,
                correlation_id=correlation_id,
            )
            return None

        record = results[0]
        return {
            "ticket_id": record.get("number", ""),
            "sys_id": record.get("sys_id", ""),
            "status": _state_to_status(record.get("state", "")),
            "short_description": record.get("short_description", ""),
            "work_notes": record.get("work_notes", ""),
            "assigned_to": record.get("assigned_to", ""),
            "assignment_group": record.get("assignment_group", ""),
        }

    @log_service_call
    async def get_work_notes(
        self,
        ticket_id: str,
        *,
        correlation_id: str = "",
    ) -> str:
        """Fetch work notes from a ServiceNow incident.

        Used by Path B Step 15 — when the human team marks a ticket
        as resolved, we read their notes to generate a resolution email.

        Args:
            ticket_id: ServiceNow incident number (INC-XXXXXXX).
            correlation_id: Tracing ID.

        Returns:
            Work notes text, or empty string if not found.
        """
        ticket = await self.get_ticket(
            ticket_id, correlation_id=correlation_id
        )
        if ticket is None:
            return ""

        return ticket.get("work_notes", "")

    async def _find_sys_id(self, ticket_id: str) -> str | None:
        """Look up the sys_id for an incident by its number.

        Used internally by update_ticket_status to find the record
        before PATCHing it.

        Returns:
            sys_id string, or None if not found.
        """
        client = self._get_client()
        url = f"{self._base_url}/api/now/table/incident"
        response = await client.get(
            url,
            params={
                "number": ticket_id,
                "sysparm_limit": "1",
                "sysparm_fields": "sys_id",
            },
        )
        response.raise_for_status()
        results = response.json().get("result", [])
        if not results:
            return None
        return results[0].get("sys_id")


# --- Helper Functions ---


def _status_to_state(status: str) -> str:
    """Map a human-readable status to ServiceNow state integer.

    ServiceNow uses integer state codes internally:
    1=New, 2=In Progress, 3=On Hold, 6=Resolved, 7=Closed.
    """
    mapping = {
        "New": "1",
        "In Progress": "2",
        "On Hold": "3",
        "Resolved": "6",
        "Closed": "7",
    }
    return mapping.get(status, "1")


def _state_to_status(state: str) -> str:
    """Map a ServiceNow state integer to human-readable status."""
    mapping = {
        "1": "New",
        "2": "In Progress",
        "3": "On Hold",
        "6": "Resolved",
        "7": "Closed",
    }
    return mapping.get(str(state), "New")
