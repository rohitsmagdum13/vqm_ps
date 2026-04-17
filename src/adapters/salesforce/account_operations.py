"""Module: adapters/salesforce/account_operations.py

Vendor account CRUD operations via Salesforce.

Handles listing, creating, updating, and deleting
Vendor_Account__c records in Salesforce. Used by the
vendor management portal endpoints.
"""

from __future__ import annotations

import asyncio

import structlog

from adapters.salesforce.client import SalesforceConnectorError
from utils.decorators import log_service_call

logger = structlog.get_logger(__name__)


class AccountOperationsMixin:
    """Vendor account CRUD methods for the Salesforce connector.

    Mixed into SalesforceConnector. Expects self._get_client(),
    self._is_salesforce_record_id(), and self._fetch_vendor_record()
    from SalesforceClient.
    """

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

    @log_service_call
    async def get_next_vendor_id(
        self,
        *,
        correlation_id: str = "",
    ) -> str:
        """Find the highest Vendor_ID__c and return the next one.

        Vendor IDs follow the pattern V-001, V-002, ..., V-025.
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

        max_number = 0
        for record in records:
            vid = record.get("Vendor_ID__c", "")
            if vid and vid.startswith("V-"):
                try:
                    num = int(vid.split("-", 1)[1])
                    if num > max_number:
                        max_number = num
                except (ValueError, IndexError):
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

        Auto-generates the next Vendor_ID__c (V-XXX).
        """
        next_vendor_id = await self.get_next_vendor_id(
            correlation_id=correlation_id,
        )

        create_data["Vendor_ID__c"] = next_vendor_id

        logger.info(
            "Creating Vendor_Account__c record",
            tool="salesforce",
            vendor_id=next_vendor_id,
            name=create_data.get("Name", ""),
            correlation_id=correlation_id,
        )

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
            sf_detail = str(exc)
            raise SalesforceConnectorError(
                f"Vendor_Account__c creation failed for {create_data.get('Name', '')}. "
                f"Salesforce error: {sf_detail}"
            )

        salesforce_id = result.get("id", "")

        logger.info(
            "Vendor_Account__c record created",
            tool="salesforce",
            salesforce_id=salesforce_id,
            vendor_id=next_vendor_id,
            name=create_data.get("Name", ""),
            correlation_id=correlation_id,
        )

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

        Accepts EITHER a Salesforce record ID or a Vendor_ID__c value.
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

        Accepts EITHER a Salesforce record ID or a Vendor_ID__c value.
        """
        is_record_id = self._is_salesforce_record_id(vendor_id_field)

        if is_record_id:
            record_id = vendor_id_field
            logger.info(
                "Salesforce update: using record ID directly",
                tool="salesforce",
                record_id=record_id,
                correlation_id=correlation_id,
            )
        else:
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

        vendor_record = await self._fetch_vendor_record(
            record_id, correlation_id=correlation_id,
        )

        return {
            "success": True,
            "vendor_id": vendor_id_field,
            "updated_fields": updated_fields,
            "vendor_record": vendor_record,
        }
