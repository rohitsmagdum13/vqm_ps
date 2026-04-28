"""Package: adapters/graph_api

Microsoft Graph API connector for VQMS — split into focused modules.

The GraphAPIConnector class combines:
- GraphAPIClient: MSAL OAuth2 authentication, httpx client, token management
- EmailFetchMixin: email fetch and unread message listing
- EmailSendMixin: email sending via /sendMail
- WebhookMixin: webhook subscription and large attachment download

Re-exports so existing imports like
``from adapters.graph_api import GraphAPIConnector`` keep working.

Public re-exports for callers:
- ``GraphAPIConnector``  — the combined connector class
- ``OutboundAttachment`` — frozen dataclass used by AdminEmailService
  to hand attachments to ``send_email``. Re-exported here so callers
  don't have to reach into ``adapters.graph_api.email_send``.
"""

from adapters.graph_api.client import GraphAPIClient
from adapters.graph_api.email_fetch import EmailFetchMixin
from adapters.graph_api.email_send import EmailSendMixin

# Explicit `as` alias signals to linters and type-checkers that this is
# a deliberate re-export (PEP 484). Keeps the public name stable even if
# the dataclass moves between submodules later.
from adapters.graph_api.email_send import (
    OutboundAttachment as OutboundAttachment,  # noqa: PLC0414
)
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
