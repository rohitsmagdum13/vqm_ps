"""Module: connectors/salesforce.py

Salesforce CRM connector for VQMS.

Handles vendor identification using a 3-step fallback chain:
1. Exact email match on Vendor_Contact__c records
2. Extract email/name from email body, try again
3. Fuzzy name match on Vendor_Account__c records

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
        """Find a vendor by exact email match on Vendor_Contact__c records.

        Queries the Vendor_Contact__c object for records where Email__c
        matches exactly, then returns the parent Vendor_Account__c as
        the vendor.

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
        """Look up a vendor by Salesforce Vendor_Account__c ID.

        Args:
            vendor_id: Salesforce Vendor_Account__c record ID.
            correlation_id: Tracing ID.

        Returns:
            Vendor_Account__c record dict, or None if not found.
        """
        safe_id = vendor_id.replace("'", "\\'")
        soql = (
            "SELECT Id, Name, Vendor_ID__c, Website__c, Vendor_Tier__c, "
            "City__c "
            f"FROM Vendor_Account__c WHERE Id = '{safe_id}' "
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

        Args:
            name: Vendor or sender name to search for.
            correlation_id: Tracing ID.

        Returns:
            VendorMatch with match_method="fuzzy_name" if found,
            None if no matching vendor account exists.
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

    # --- Vendor_Account__c CRUD Methods ---
    # All methods below query the custom Vendor_Account__c object
    # in Salesforce. Used by the vendor management portal endpoints.

    @log_service_call
    async def get_all_active_vendors(
        self,
        *,
        correlation_id: str = "",
    ) -> list[dict]:
        """Get all active vendors from the Vendor_Account__c custom object.

        Used by GET /vendors for the portal vendor management table.
        """
        soql = (
            "SELECT Id, Name, Vendor_ID__c, Website__c, Vendor_Tier__c, "
            "Category__c, Payment_Terms__c, Annual_Revenue__c, "
            "SLA_Response_Hours__c, SLA_Resolution_Days__c, "
            "Vendor_Status__c, Onboarded_Date__c, "
            "City__c, State__c, Country__c "
            "FROM Vendor_Account__c "
            "WHERE Vendor_Status__c = 'Active' "
            "ORDER BY Vendor_ID__c ASC"
        )

        logger.info(
            "Salesforce SOQL: get_all_active_vendors (Vendor_Account__c)",
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
            "Active vendors retrieved from Vendor_Account__c",
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
            })
        return cleaned

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

    @log_service_call
    def _is_salesforce_record_id(self, value: str) -> bool:
        """Check if a string looks like a Salesforce record ID.

        Salesforce record IDs are 15 or 18 characters long.
        For Vendor_Account__c (custom object), IDs start with
        the object's key prefix (e.g., 'a0B' or similar).
        Standard Account IDs start with '001'.

        Vendor_ID__c values look like 'V-001', 'V-025' — short,
        start with 'V-', clearly different from record IDs.
        """
        # Custom object record IDs are 15 or 18 chars but do NOT
        # start with '001' — that prefix is for standard Account.
        # We check length only; the 'V-' prefix distinguishes
        # Vendor_ID__c values from any Salesforce record ID.
        return len(value) in (15, 18) and not value.startswith("V-")

    @log_service_call
    async def get_next_vendor_id(
        self,
        *,
        correlation_id: str = "",
    ) -> str:
        """Find the highest Vendor_ID__c and return the next one.

        Vendor IDs follow the pattern V-001, V-002, ..., V-025.
        This method queries all Vendor_Account__c records that have
        a Vendor_ID__c value, extracts the numeric part, finds
        the maximum, and returns V-{max+1} zero-padded to 3 digits.

        If no vendors exist yet, returns 'V-001'.
        """
        soql = (
            "SELECT Vendor_ID__c "
            "FROM Vendor_Account__c "
            "WHERE Vendor_ID__c != null "
            "ORDER BY Vendor_ID__c DESC"
        )

        try:
            result = await asyncio.to_thread(self._get_client().query, soql)
        except Exception:
            logger.exception(
                "Salesforce query failed: get_next_vendor_id",
                tool="salesforce",
                correlation_id=correlation_id,
            )
            raise SalesforceConnectorError("Failed to query existing Vendor_ID__c values")

        records = result.get("records", [])

        if not records:
            return "V-001"

        # Extract numeric parts from all Vendor_ID__c values
        # Format: V-001, V-002, ..., V-025
        max_number = 0
        for record in records:
            vid = record.get("Vendor_ID__c", "")
            if vid and vid.startswith("V-"):
                try:
                    num = int(vid.split("-", 1)[1])
                    if num > max_number:
                        max_number = num
                except (ValueError, IndexError):
                    # Skip malformed Vendor_ID__c values
                    continue

        next_number = max_number + 1
        next_vendor_id = f"V-{next_number:03d}"

        logger.info(
            "Next Vendor_ID__c determined",
            tool="salesforce",
            current_max=max_number,
            next_vendor_id=next_vendor_id,
            correlation_id=correlation_id,
        )

        return next_vendor_id

    @log_service_call
    async def create_vendor_account(
        self,
        create_data: dict,
        *,
        correlation_id: str = "",
    ) -> dict:
        """Create a new Vendor_Account__c record in Salesforce.

        Auto-generates the next Vendor_ID__c (V-XXX) by finding
        the current highest number and incrementing by 1.

        Args:
            create_data: Dict of Salesforce field names and values.
                         Must include 'Name' at minimum.
            correlation_id: Tracing ID.

        Returns:
            Dict with salesforce_id, vendor_id, and name.
        """
        # Step 1: Get the next Vendor_ID__c
        next_vendor_id = await self.get_next_vendor_id(
            correlation_id=correlation_id,
        )

        # Step 2: Add the auto-generated Vendor_ID__c to the data
        create_data["Vendor_ID__c"] = next_vendor_id

        logger.info(
            "Creating Vendor_Account__c record",
            tool="salesforce",
            vendor_id=next_vendor_id,
            name=create_data.get("Name", ""),
            correlation_id=correlation_id,
        )

        # Step 3: Create the Vendor_Account__c record in Salesforce
        try:
            result = await asyncio.to_thread(
                self._get_client().Vendor_Account__c.create, create_data
            )
        except Exception as exc:
            logger.exception(
                "Vendor_Account__c creation failed",
                tool="salesforce",
                vendor_id=next_vendor_id,
                correlation_id=correlation_id,
            )
            # Extract the actual Salesforce error message for better
            # user feedback (e.g., "bad value for restricted picklist")
            sf_detail = str(exc)
            raise SalesforceConnectorError(
                f"Vendor_Account__c creation failed for {create_data.get('Name', '')}. "
                f"Salesforce error: {sf_detail}"
            )

        # simple-salesforce returns {'id': 'a0B...', 'success': True, 'errors': []}
        salesforce_id = result.get("id", "")

        logger.info(
            "Vendor_Account__c record created",
            tool="salesforce",
            salesforce_id=salesforce_id,
            vendor_id=next_vendor_id,
            name=create_data.get("Name", ""),
            correlation_id=correlation_id,
        )

        # Fetch the full record back so the API can return all fields
        vendor_record = await self._fetch_vendor_record(
            salesforce_id, correlation_id=correlation_id,
        )

        return {
            "success": True,
            "salesforce_id": salesforce_id,
            "vendor_id": next_vendor_id,
            "name": create_data.get("Name", ""),
            "vendor_record": vendor_record,
        }

    @log_service_call
    async def delete_vendor_account(
        self,
        vendor_id_field: str,
        *,
        correlation_id: str = "",
    ) -> dict:
        """Delete a Vendor_Account__c record from Salesforce.

        Accepts EITHER a Salesforce record ID (e.g., 'a0Bal00002Ie1zjAAB')
        OR a Vendor_ID__c value (e.g., 'V-001'). Detects which type was
        passed and resolves to the record ID before deleting.

        Args:
            vendor_id_field: Salesforce record ID or Vendor_ID__c.
            correlation_id: Tracing ID.

        Returns:
            Dict with success status and deleted vendor info.
        """
        is_record_id = self._is_salesforce_record_id(vendor_id_field)

        if is_record_id:
            record_id = vendor_id_field
            logger.info(
                "Salesforce delete: using record ID directly",
                tool="salesforce",
                record_id=record_id,
                correlation_id=correlation_id,
            )
        else:
            # Lookup by Vendor_ID__c to find the record ID
            safe_id = vendor_id_field.replace("'", "\\'")
            soql = (
                "SELECT Id, Name, Vendor_ID__c "
                "FROM Vendor_Account__c "
                f"WHERE Vendor_ID__c = '{safe_id}' "
                "LIMIT 1"
            )

            try:
                result = await asyncio.to_thread(self._get_client().query, soql)
            except Exception:
                logger.exception(
                    "Vendor_Account__c lookup for delete failed",
                    tool="salesforce",
                    vendor_id=vendor_id_field,
                    correlation_id=correlation_id,
                )
                raise SalesforceConnectorError(
                    f"SOQL query failed for Vendor_Account__c lookup: {vendor_id_field}"
                )

            records = result.get("records", [])
            if not records:
                raise SalesforceConnectorError(
                    f"No Vendor_Account__c found with Vendor_ID__c = '{vendor_id_field}'"
                )

            record_id = records[0]["Id"]

        # Delete the Vendor_Account__c record
        try:
            await asyncio.to_thread(
                self._get_client().Vendor_Account__c.delete, record_id
            )
        except Exception:
            logger.exception(
                "Vendor_Account__c deletion failed",
                tool="salesforce",
                vendor_id=vendor_id_field,
                record_id=record_id,
                correlation_id=correlation_id,
            )
            raise SalesforceConnectorError(
                f"Vendor_Account__c deletion failed for {vendor_id_field}"
            )

        logger.info(
            "Vendor_Account__c record deleted",
            tool="salesforce",
            vendor_id=vendor_id_field,
            record_id=record_id,
            correlation_id=correlation_id,
        )

        return {
            "success": True,
            "vendor_id": vendor_id_field,
            "record_id": record_id,
        }

    async def update_vendor_account(
        self,
        vendor_id_field: str,
        update_data: dict,
        *,
        correlation_id: str = "",
    ) -> dict:
        """Update a Vendor_Account__c record in Salesforce.

        Accepts EITHER a Salesforce record ID (e.g., 'a0Bal00002Ie1zjAAB')
        OR a Vendor_ID__c value (e.g., 'V-001'). Detects which type was
        passed and queries accordingly.

        The GET /vendors endpoint returns the record ID as the 'id' field,
        so most callers will pass a record ID.
        """
        # Determine lookup strategy based on the ID format
        is_record_id = self._is_salesforce_record_id(vendor_id_field)

        if is_record_id:
            # Direct lookup by Salesforce record ID — no SOQL needed,
            # just use the ID directly for the update call
            record_id = vendor_id_field

            logger.info(
                "Salesforce update: using record ID directly",
                tool="salesforce",
                record_id=record_id,
                correlation_id=correlation_id,
            )
        else:
            # Lookup by Vendor_ID__c custom field (e.g., 'V-001')
            safe_id = vendor_id_field.replace("'", "\\'")
            soql = (
                "SELECT Id, Name, Vendor_ID__c "
                "FROM Vendor_Account__c "
                f"WHERE Vendor_ID__c = '{safe_id}' "
                "LIMIT 1"
            )

            logger.info(
                "Salesforce SOQL: find Vendor_Account__c by Vendor_ID__c for update",
                tool="salesforce",
                vendor_id=vendor_id_field,
                correlation_id=correlation_id,
            )

            try:
                result = await asyncio.to_thread(self._get_client().query, soql)
            except Exception:
                logger.exception(
                    "Vendor_Account__c lookup failed",
                    tool="salesforce",
                    vendor_id=vendor_id_field,
                    correlation_id=correlation_id,
                )
                raise SalesforceConnectorError(
                    f"SOQL query failed for Vendor_Account__c lookup: {vendor_id_field}"
                )

            records = result.get("records", [])
            if not records:
                raise SalesforceConnectorError(
                    f"No Vendor_Account__c found with Vendor_ID__c = '{vendor_id_field}'"
                )

            record_id = records[0]["Id"]

        try:
            await asyncio.to_thread(
                self._get_client().Vendor_Account__c.update, record_id, update_data
            )
        except Exception as exc:
            logger.exception(
                "Vendor_Account__c update failed",
                tool="salesforce",
                vendor_id=vendor_id_field,
                record_id=record_id,
                correlation_id=correlation_id,
            )
            sf_detail = str(exc)
            raise SalesforceConnectorError(
                f"Vendor_Account__c update failed for {vendor_id_field}. "
                f"Salesforce error: {sf_detail}"
            )

        updated_fields = list(update_data.keys())
        logger.info(
            "Vendor_Account__c record updated",
            tool="salesforce",
            vendor_id=vendor_id_field,
            record_id=record_id,
            updated_fields=updated_fields,
            correlation_id=correlation_id,
        )

        # Fetch the full record back so the API can return all fields
        vendor_record = await self._fetch_vendor_record(
            record_id, correlation_id=correlation_id,
        )

        return {
            "success": True,
            "vendor_id": vendor_id_field,
            "updated_fields": updated_fields,
            "vendor_record": vendor_record,
        }
