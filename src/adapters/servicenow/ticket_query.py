"""Module: adapters/servicenow/ticket_query.py

Ticket query, update, and work notes retrieval via ServiceNow.

Handles fetching existing incidents, updating their status,
and reading work notes. Used by the SLA monitor and Path B
resolution flow (Step 15).
"""

from __future__ import annotations

import structlog

from adapters.servicenow.client import ServiceNowConnectorError
from utils.decorators import log_service_call

logger = structlog.get_logger(__name__)


class TicketQueryMixin:
    """Ticket query and update methods for the ServiceNow connector.

    Mixed into ServiceNowConnector. Expects self._get_client(),
    self._base_url, self.status_to_state(), and self.state_to_status()
    from ServiceNowClient.
    """

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
            update_data: dict = {"state": self.status_to_state(new_status)}
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
            "status": self.state_to_status(record.get("state", "")),
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
