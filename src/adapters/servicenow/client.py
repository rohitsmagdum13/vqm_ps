"""Module: adapters/servicenow/client.py

ServiceNow client initialization and authentication.

Manages the httpx async client with lazy initialization and
provides shared helper methods and constants used across all
ServiceNow operation classes.
"""

from __future__ import annotations

import httpx
import structlog

from config.settings import Settings

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


class ServiceNowClient:
    """Base ServiceNow client with connection management.

    Uses lazy initialization for the httpx client — it's only
    created on the first API call. This avoids connection errors
    during startup if ServiceNow credentials aren't configured yet.
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

    @staticmethod
    def status_to_state(status: str) -> str:
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

    @staticmethod
    def state_to_status(state: str) -> str:
        """Map a ServiceNow state integer to human-readable status."""
        mapping = {
            "1": "New",
            "2": "In Progress",
            "3": "On Hold",
            "6": "Resolved",
            "7": "Closed",
        }
        return mapping.get(str(state), "New")
