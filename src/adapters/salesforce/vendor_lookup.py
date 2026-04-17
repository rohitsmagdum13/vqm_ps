"""Module: adapters/salesforce/vendor_lookup.py

Vendor identification and lookup via Salesforce.

Implements the 3-step fallback chain for vendor identification:
1. Exact email match on Vendor_Contact__c records
2. Extract email/name from email body, try again
3. Fuzzy name match on Vendor_Account__c records
"""

from __future__ import annotations

import asyncio
import re

import structlog

from models.vendor import VendorMatch
from utils.decorators import log_service_call

logger = structlog.get_logger(__name__)


class VendorLookupMixin:
    """Vendor identification methods for the Salesforce connector.

    Mixed into SalesforceConnector. Expects self._get_client()
    and self._is_salesforce_record_id() from SalesforceClient.
    """

    @log_service_call
    async def find_vendor_by_email(
        self,
        email: str,
        *,
        correlation_id: str = "",
    ) -> VendorMatch | None:
        """Find a vendor by exact email match on Vendor_Contact__c records.

        Queries the Vendor_Contact__c object for records where Email__c
        matches exactly, then returns the parent Vendor_Account__c as
        the vendor.
        """
        # Escape single quotes in email to prevent SOQL injection
        safe_email = email.replace("'", "\\'")
        soql = (
            "SELECT Vendor_Account__c, Vendor_Account__r.Id, "
            "Vendor_Account__r.Name "
            "FROM Vendor_Contact__c "
            f"WHERE Email__c = '{safe_email}' "
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
        account = record.get("Vendor_Account__r", {}) or {}
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
        """Look up a vendor by Salesforce record ID or Vendor_ID__c.

        Accepts EITHER a Salesforce record ID (e.g., 'a0Bal00002Ie1zjAAB')
        OR a Vendor_ID__c value (e.g., 'V-001').
        """
        safe_id = vendor_id.replace("'", "\\'")

        is_record_id = self._is_salesforce_record_id(vendor_id)
        where_field = "Id" if is_record_id else "Vendor_ID__c"

        soql = (
            "SELECT Id, Name, Vendor_ID__c, Website__c, Vendor_Tier__c, "
            "City__c "
            f"FROM Vendor_Account__c WHERE {where_field} = '{safe_id}' "
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
        """Find a vendor by fuzzy name match on Vendor_Account__c records.

        Uses SOQL LIKE with wildcards for partial matching.
        This is the last resort in the 3-step fallback chain.
        """
        if not name or not name.strip():
            return None

        # Escape SOQL special characters and wrap in wildcards
        safe_name = name.replace("'", "\\'").replace("%", "\\%")
        soql = (
            "SELECT Id, Name "
            "FROM Vendor_Account__c "
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

        # All steps failed
        logger.warning(
            "Vendor identification failed — all 3 steps returned no match",
            tool="salesforce",
            sender_email=sender_email,
            sender_name=sender_name,
            correlation_id=correlation_id,
        )
        return None
