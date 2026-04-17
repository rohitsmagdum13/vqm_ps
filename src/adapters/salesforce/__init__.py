"""Package: adapters/salesforce

Salesforce CRM connector for VQMS — split into focused modules.

The SalesforceConnector class combines:
- SalesforceClient: connection management and shared helpers
- VendorLookupMixin: 3-step vendor identification fallback chain
- AccountOperationsMixin: Vendor_Account__c CRUD operations

Re-exports so existing imports like
``from adapters.salesforce import SalesforceConnector`` keep working.
"""

from adapters.salesforce.account_operations import AccountOperationsMixin
from adapters.salesforce.client import SalesforceClient, SalesforceConnectorError
from adapters.salesforce.vendor_lookup import VendorLookupMixin
from config.settings import Settings


class SalesforceConnector(SalesforceClient, VendorLookupMixin, AccountOperationsMixin):
    """Full Salesforce connector combining all operations.

    Inherits from:
    - SalesforceClient: lazy client init, _get_client(), helpers
    - VendorLookupMixin: find_vendor_by_email, identify_vendor, fuzzy_name_match
    - AccountOperationsMixin: get_all_active_vendors, create/update/delete vendor
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize with application settings."""
        super().__init__(settings)


__all__ = ["SalesforceConnector", "SalesforceConnectorError"]
