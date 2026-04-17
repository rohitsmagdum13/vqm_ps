"""Package: adapters/servicenow

ServiceNow ITSM connector for VQMS — split into focused modules.

The ServiceNowConnector class combines:
- ServiceNowClient: connection management, httpx client, shared helpers
- TicketCreateMixin: incident creation via POST /api/now/table/incident
- TicketQueryMixin: ticket lookup and work notes retrieval

Re-exports so existing imports like
``from adapters.servicenow import ServiceNowConnector`` keep working.
"""

from adapters.servicenow.client import ServiceNowClient, ServiceNowConnectorError
from adapters.servicenow.ticket_create import TicketCreateMixin
from adapters.servicenow.ticket_query import TicketQueryMixin
from config.settings import Settings


class ServiceNowConnector(ServiceNowClient, TicketCreateMixin, TicketQueryMixin):
    """Full ServiceNow connector combining all operations.

    Inherits from:
    - ServiceNowClient: lazy httpx client init, _get_client(), close(), helpers
    - TicketCreateMixin: create_ticket()
    - TicketQueryMixin: get_ticket(), get_work_notes(), update_ticket_status()
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize with application settings."""
        super().__init__(settings)


# Backward-compatible aliases for the helper functions that were
# module-level in the original single-file version. Tests and other
# code may import these directly.
_status_to_state = ServiceNowClient.status_to_state
_state_to_status = ServiceNowClient.state_to_status

__all__ = [
    "ServiceNowConnector",
    "ServiceNowConnectorError",
    "_status_to_state",
    "_state_to_status",
]
