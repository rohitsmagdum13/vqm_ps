"""Module: adapters/salesforce/client.py

Salesforce client initialization and authentication.

Manages the simple-salesforce client with lazy initialization
and provides shared helper methods used across all Salesforce
operation classes.
"""

from __future__ import annotations

import structlog
from simple_salesforce import Salesforce as SFClient

from config.settings import Settings
from utils.decorators import log_service_call

logger = structlog.get_logger(__name__)


class SalesforceConnectorError(Exception):
    """Raised when a Salesforce API call fails in vendor CRUD operations."""


class SalesforceClient:
    """Base Salesforce client with connection management.

    Uses lazy initialization for the Salesforce client — it's only
    created on the first API call. This avoids connection errors
    during startup if Salesforce credentials aren't configured yet.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize with application settings.

        Does NOT connect to Salesforce yet. The client is created
        lazily on first use via _get_client().
        """
        self._settings = settings
        self._sf: SFClient | None = None

    def _get_client(self) -> SFClient:
        """Get or create the Salesforce client.

        Lazy initialization — the client is created on first call
        and cached for subsequent calls.

        Returns:
            Authenticated simple-salesforce client.
        """
        if self._sf is None:
            self._sf = SFClient(
                username=self._settings.salesforce_username or "",
                password=self._settings.salesforce_password or "",
                security_token=self._settings.salesforce_security_token or "",
                instance_url=self._settings.salesforce_instance_url,
            )
        return self._sf

    @log_service_call
    def _is_salesforce_record_id(self, value: str) -> bool:
        """Check if a string looks like a Salesforce record ID.

        Salesforce record IDs are 15 or 18 characters long.
        Vendor_ID__c values look like 'V-001', 'V-025' — short,
        start with 'V-', clearly different from record IDs.
        """
        return len(value) in (15, 18) and not value.startswith("V-")

    async def _fetch_vendor_record(
        self,
        record_id: str,
        *,
        correlation_id: str = "",
    ) -> dict:
        """Fetch a single Vendor_Account__c record by its Salesforce ID.

        Returns a dict with all portal-visible fields, matching the
        same shape as get_all_active_vendors() output.
        Used after create/update to return the full record to the caller.
        """
        import asyncio

        safe_id = record_id.replace("'", "\\'")
        soql = (
            "SELECT Id, Name, Vendor_ID__c, Website__c, Vendor_Tier__c, "
            "Category__c, Payment_Terms__c, Annual_Revenue__c, "
            "SLA_Response_Hours__c, SLA_Resolution_Days__c, "
            "Vendor_Status__c, Onboarded_Date__c, "
            "City__c, State__c, Country__c "
            "FROM Vendor_Account__c "
            f"WHERE Id = '{safe_id}' LIMIT 1"
        )

        try:
            result = await asyncio.to_thread(self._get_client().query, soql)
        except Exception:
            logger.warning(
                "Failed to fetch vendor record after create/update",
                tool="salesforce",
                record_id=record_id,
                correlation_id=correlation_id,
            )
            return {}

        records = result.get("records", [])
        if not records:
            return {}

        record = records[0]
        return {
            "id": record.get("Id"),
            "name": record.get("Name"),
            "vendor_id": record.get("Vendor_ID__c"),
            "website": record.get("Website__c"),
            "vendor_tier": record.get("Vendor_Tier__c"),
            "category": record.get("Category__c"),
            "payment_terms": record.get("Payment_Terms__c"),
            "annual_revenue": record.get("Annual_Revenue__c"),
            "sla_response_hours": record.get("SLA_Response_Hours__c"),
            "sla_resolution_days": record.get("SLA_Resolution_Days__c"),
            "vendor_status": record.get("Vendor_Status__c"),
            "onboarded_date": record.get("Onboarded_Date__c"),
            "billing_city": record.get("City__c"),
            "billing_state": record.get("State__c"),
            "billing_country": record.get("Country__c"),
        }
