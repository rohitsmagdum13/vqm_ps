"""Package: adapters/graph_api

Microsoft Graph API connector for VQMS — split into focused modules.

The GraphAPIConnector class combines:
- GraphAPIClient: MSAL OAuth2 authentication, httpx client, token management
- EmailFetchMixin: email fetch and unread message listing
- EmailSendMixin: email sending via /sendMail
- WebhookMixin: webhook subscription and large attachment download

Re-exports so existing imports like
``from adapters.graph_api import GraphAPIConnector`` keep working.
"""

from adapters.graph_api.client import GraphAPIClient
from adapters.graph_api.email_fetch import EmailFetchMixin
from adapters.graph_api.email_send import EmailSendMixin, OutboundAttachment
from adapters.graph_api.webhook import WebhookMixin
from config.settings import Settings


class GraphAPIConnector(GraphAPIClient, EmailFetchMixin, EmailSendMixin, WebhookMixin):
    """Full Graph API connector combining all operations.

    Inherits from:
    - GraphAPIClient: MSAL auth, _request(), _acquire_token(), close()
    - EmailFetchMixin: fetch_email(), list_unread_messages()
    - EmailSendMixin: send_email()
    - WebhookMixin: subscribe_webhook(), download_large_attachment()
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize with application settings."""
        super().__init__(settings)


__all__ = ["GraphAPIConnector", "OutboundAttachment"]
