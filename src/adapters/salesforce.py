"""Module: connectors/salesforce.py

Salesforce CRM connector for VQMS.

Handles vendor identification using a 3-step fallback chain:
1. Exact email match on Contact records
2. Extract email/name from email body, try again
3. Fuzzy name match on Account records

Uses simple-salesforce for the Salesforce REST API. All calls
are wrapped in asyncio.to_thread because simple-salesforce is
synchronous.

Usage:
    from connectors.salesforce import SalesforceConnector
    from config.settings import get_settings

    sf = SalesforceConnector(get_settings())
    match = await sf.identify_vendor(
        sender_email="rajesh@technova.com",
        sender_name="Rajesh Kumar",
        correlation_id="abc-123",
    )
"""

from __future__ import annotations

import asyncio

import structlog
from simple_salesforce import Salesforce as SFClient

from config.settings import Settings
from models.vendor import VendorMatch
from utils.decorators import log_service_call

logger = structlog.get_logger(__name__)


class SalesforceConnectorError(Exception):
    """Raised when a Salesforce API call fails in vendor CRUD operations."""


class SalesforceConnector:
    """Salesforce CRM connector for vendor lookup and identification.

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
    async def find_vendor_by_email(
        self,
        email: str,
        *,
        correlation_id: str = "",
    ) -> VendorMatch | None:
        """Find a vendor by exact email match on Salesforce Contact records.

        Queries the Contact object for records where Email matches
        exactly, then returns the parent Account as the vendor.

        Args:
            email: Email address to search for.
            correlation_id: Tracing ID.

        Returns:
            VendorMatch with match_method="exact_email" if found,
            None if no matching contact exists.
        """
        # Escape single quotes in email to prevent SOQL injection
        safe_email = email.replace("'", "\\'")
        soql = (
            "SELECT Contact.AccountId, Account.Id, Account.Name "
            "FROM Contact "
            f"WHERE Email = '{safe_email}' "
            "LIMIT 1"
        )

        try:
            result = await asyncio.to_thread(self._get_client().query, soql)
        except Exception:
            logger.exception(
                "Salesforce query failed for email lookup",
                tool="salesforce",
                email=email,
                correlation_id=correlation_id,
            )
            return None

        records = result.get("records", [])
        if not records:
            logger.info(
                "No vendor found by email",
                tool="salesforce",
                email=email,
                correlation_id=correlation_id,
            )
            return None

        record = records[0]
        account = record.get("Account", {}) or {}
        vendor_id = account.get("Id", "")
        vendor_name = account.get("Name", "")

        return VendorMatch(
            vendor_id=vendor_id,
            vendor_name=vendor_name,
            match_method="exact_email",
            confidence=1.0,
        )

    @log_service_call
    async def find_vendor_by_id(
        self,
        vendor_id: str,
        *,
        correlation_id: str = "",
    ) -> dict | None:
        """Look up a vendor Account by Salesforce Account ID.

        Args:
            vendor_id: Salesforce Account ID.
            correlation_id: Tracing ID.

        Returns:
            Account record dict, or None if not found.
        """
        safe_id = vendor_id.replace("'", "\\'")
        soql = (
            "SELECT Id, Name, Industry, Phone, Website, BillingCity "
            f"FROM Account WHERE Id = '{safe_id}' "
            "LIMIT 1"
        )

        try:
            result = await asyncio.to_thread(self._get_client().query, soql)
        except Exception:
            logger.exception(
                "Salesforce query failed for vendor ID lookup",
                tool="salesforce",
                vendor_id=vendor_id,
                correlation_id=correlation_id,
            )
            return None

        records = result.get("records", [])
        return records[0] if records else None

    @log_service_call
    async def fuzzy_name_match(
        self,
        name: str,
        *,
        correlation_id: str = "",
    ) -> VendorMatch | None:
        """Find a vendor by fuzzy name match on Account records.

        Uses SOQL LIKE with wildcards for partial matching.
        This is the last resort in the 3-step fallback chain.

        Args:
            name: Vendor or sender name to search for.
            correlation_id: Tracing ID.

        Returns:
            VendorMatch with match_method="fuzzy_name" if found,
            None if no matching account exists.
        """
        if not name or not name.strip():
            return None

        # Escape SOQL special characters and wrap in wildcards
        safe_name = name.replace("'", "\\'").replace("%", "\\%")
        soql = (
            "SELECT Id, Name "
            "FROM Account "
            f"WHERE Name LIKE '%{safe_name}%' "
            "LIMIT 1"
        )

        try:
            result = await asyncio.to_thread(self._get_client().query, soql)
        except Exception:
            logger.exception(
                "Salesforce fuzzy name match failed",
                tool="salesforce",
                name=name,
                correlation_id=correlation_id,
            )
            return None

        records = result.get("records", [])
        if not records:
            return None

        record = records[0]
        return VendorMatch(
            vendor_id=record.get("Id", ""),
            vendor_name=record.get("Name", ""),
            match_method="fuzzy_name",
            confidence=0.6,
        )

    @log_service_call
    async def identify_vendor(
        self,
        sender_email: str,
        sender_name: str | None = None,
        body_text: str | None = None,
        *,
        correlation_id: str = "",
    ) -> VendorMatch | None:
        """Identify a vendor using the 3-step fallback chain.

        Step 1: Exact email match on sender_email.
        Step 2: If body_text provided, try to extract alternative
                email addresses or company names and search again.
        Step 3: Fuzzy name match on sender_name.

        Args:
            sender_email: Email address of the sender.
            sender_name: Display name of the sender (optional).
            body_text: Plain text of the email body (optional).
            correlation_id: Tracing ID.

        Returns:
            VendorMatch if any step succeeds, None if all fail.
            The caller decides how to handle None (email path
            continues with vendor_id=None, portal path gets
            vendor_id from JWT).
        """
        # Step 1: Exact email match
        match = await self.find_vendor_by_email(
            sender_email, correlation_id=correlation_id
        )
        if match is not None:
            logger.info(
                "Vendor identified by exact email",
                tool="salesforce",
                vendor_id=match.vendor_id,
                email=sender_email,
                correlation_id=correlation_id,
            )
            return match

        # Step 2: Try to extract info from email body
        if body_text:
            # Simple extraction: look for email-like patterns
            # in the body text and try each one
            import re

            email_pattern = r"[\w.+-]+@[\w-]+\.[\w.-]+"
            found_emails = re.findall(email_pattern, body_text)
            for extracted_email in found_emails:
                # Skip the sender's own email — we already tried it
                if extracted_email.lower() == sender_email.lower():
                    continue
                match = await self.find_vendor_by_email(
                    extracted_email, correlation_id=correlation_id
                )
                if match is not None:
                    # Override match_method to indicate body extraction
                    match = VendorMatch(
                        vendor_id=match.vendor_id,
                        vendor_name=match.vendor_name,
                        match_method="body_extraction",
                        confidence=0.8,
                    )
                    logger.info(
                        "Vendor identified from email body",
                        tool="salesforce",
                        vendor_id=match.vendor_id,
                        extracted_email=extracted_email,
                        correlation_id=correlation_id,
                    )
                    return match

        # Step 3: Fuzzy name match
        if sender_name:
            match = await self.fuzzy_name_match(
                sender_name, correlation_id=correlation_id
            )
            if match is not None:
                logger.info(
                    "Vendor identified by fuzzy name",
                    tool="salesforce",
                    vendor_id=match.vendor_id,
                    name=sender_name,
                    correlation_id=correlation_id,
                )
                return match

        # All steps failed — return None (caller handles this)
        logger.warning(
            "Vendor identification failed — all 3 steps returned no match",
            tool="salesforce",
            sender_email=sender_email,
            sender_name=sender_name,
            correlation_id=correlation_id,
        )
        return None

    # --- Standard Account Methods (merged from local_vqm) ---
    # The methods below query the Salesforce STANDARD Account object,
    # NOT the custom Vendor_Account__c object used by methods above.

    @log_service_call
    async def get_all_active_vendors(
        self,
        *,
        correlation_id: str = "",
    ) -> list[dict]:
        """Get all active vendors from the Salesforce STANDARD Account object.

        This queries the standard Account object (NOT custom
        Vendor_Account__c). Used by GET /vendors for the portal
        vendor management table.
        """
        soql = (
            "SELECT Id, Name, Vendor_ID__c, Website, Vendor_Tier__c, "
            "Category__c, Payment_Terms__c, AnnualRevenue, "
            "SLA_Response_Hours__c, SLA_Resolution_Days__c, "
            "Vendor_Status__c, Onboarded_Date__c, "
            "BillingCity, BillingState, BillingCountry "
            "FROM Account "
            "WHERE Vendor_Status__c = 'Active'"
        )

        logger.info(
            "Salesforce SOQL: get_all_active_vendors (standard Account)",
            tool="salesforce",
            correlation_id=correlation_id,
        )

        try:
            result = await asyncio.to_thread(self._get_client().query, soql)
        except Exception:
            logger.exception(
                "Salesforce query failed: get_all_active_vendors",
                tool="salesforce",
                correlation_id=correlation_id,
            )
            raise SalesforceConnectorError("SOQL query failed for active vendors")

        records = result.get("records", [])
        logger.info(
            "Active vendors retrieved from standard Account",
            tool="salesforce",
            result_count=len(records),
            correlation_id=correlation_id,
        )

        cleaned = []
        for record in records:
            cleaned.append({
                "id": record.get("Id"),
                "name": record.get("Name"),
                "vendor_id": record.get("Vendor_ID__c"),
                "website": record.get("Website"),
                "vendor_tier": record.get("Vendor_Tier__c"),
                "category": record.get("Category__c"),
                "payment_terms": record.get("Payment_Terms__c"),
                "annual_revenue": record.get("AnnualRevenue"),
                "sla_response_hours": record.get("SLA_Response_Hours__c"),
                "sla_resolution_days": record.get("SLA_Resolution_Days__c"),
                "vendor_status": record.get("Vendor_Status__c"),
                "onboarded_date": record.get("Onboarded_Date__c"),
                "billing_city": record.get("BillingCity"),
                "billing_state": record.get("BillingState"),
                "billing_country": record.get("BillingCountry"),
            })
        return cleaned

    @log_service_call
    async def update_vendor_account(
        self,
        vendor_id_field: str,
        update_data: dict,
        *,
        correlation_id: str = "",
    ) -> dict:
        """Update a vendor record in the Salesforce STANDARD Account object.

        Finds the Account by its Vendor_ID__c custom field, then
        applies the provided field updates.
        """
        # Escape single quotes in vendor_id to prevent SOQL injection
        safe_id = vendor_id_field.replace("'", "\\'")
        soql = (
            "SELECT Id, Name, Vendor_ID__c "
            "FROM Account "
            f"WHERE Vendor_ID__c = '{safe_id}' "
            "LIMIT 1"
        )

        logger.info(
            "Salesforce SOQL: find Account for update",
            tool="salesforce",
            vendor_id=vendor_id_field,
            correlation_id=correlation_id,
        )

        try:
            result = await asyncio.to_thread(self._get_client().query, soql)
        except Exception:
            logger.exception(
                "Salesforce Account lookup failed",
                tool="salesforce",
                vendor_id=vendor_id_field,
                correlation_id=correlation_id,
            )
            raise SalesforceConnectorError(
                f"SOQL query failed for Account lookup: {vendor_id_field}"
            )

        records = result.get("records", [])
        if not records:
            raise SalesforceConnectorError(
                f"No Account found with Vendor_ID__c = '{vendor_id_field}'"
            )

        record_id = records[0]["Id"]

        try:
            await asyncio.to_thread(
                self._get_client().Account.update, record_id, update_data
            )
        except Exception:
            logger.exception(
                "Salesforce Account update failed",
                tool="salesforce",
                vendor_id=vendor_id_field,
                record_id=record_id,
                correlation_id=correlation_id,
            )
            raise SalesforceConnectorError(
                f"Account update failed for {vendor_id_field}"
            )

        updated_fields = list(update_data.keys())
        logger.info(
            "Salesforce Account updated",
            tool="salesforce",
            vendor_id=vendor_id_field,
            record_id=record_id,
            updated_fields=updated_fields,
            correlation_id=correlation_id,
        )

        return {
            "success": True,
            "vendor_id": vendor_id_field,
            "updated_fields": updated_fields,
        }
