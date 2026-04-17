"""Module: services/email_intake/vendor_identifier.py

Vendor identification from email sender via Salesforce.

Uses the Salesforce 3-step fallback chain: exact email match,
body text extraction, fuzzy name match.
"""

from __future__ import annotations

import structlog

from adapters.salesforce import SalesforceConnector

logger = structlog.get_logger(__name__)


class VendorIdentifier:
    """Identifies the vendor from an email sender via Salesforce.

    Wraps the Salesforce adapter's identify_vendor method with
    non-critical error handling (returns unresolved on failure).
    """

    def __init__(self, salesforce: SalesforceConnector) -> None:
        """Initialize with Salesforce connector.

        Args:
            salesforce: Salesforce connector for vendor lookup.
        """
        self._salesforce = salesforce

    async def identify_vendor(
        self, parsed: dict, correlation_id: str
    ) -> tuple[str | None, str | None]:
        """Identify the vendor via Salesforce 3-step fallback.

        Non-critical — returns (None, "unresolved") on failure.
        """
        try:
            match = await self._salesforce.identify_vendor(
                sender_email=parsed["sender_email"],
                sender_name=parsed.get("sender_name"),
                body_text=parsed.get("body_text"),
                correlation_id=correlation_id,
            )
            if match is not None:
                return match.vendor_id, match.match_method
            return None, "unresolved"
        except Exception:
            logger.warning(
                "Vendor identification failed — continuing without vendor",
                sender=parsed["sender_email"],
                correlation_id=correlation_id,
            )
            return None, "unresolved"
