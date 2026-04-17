"""Module: adapters/graph_api/webhook.py

Webhook subscription and large attachment download via Graph API.

Handles creating webhook subscriptions for real-time email
detection and downloading large attachments (>3MB) that are
not returned inline in the message response.
"""

from __future__ import annotations

import structlog

from adapters.graph_api.client import GRAPH_BASE_URL
from utils.decorators import log_service_call

logger = structlog.get_logger(__name__)


class WebhookMixin:
    """Webhook and attachment methods for the Graph API connector.

    Mixed into GraphAPIConnector. Expects self._request()
    and self._mailbox from GraphAPIClient.
    """

    @log_service_call
    async def subscribe_webhook(
        self,
        notification_url: str,
        *,
        correlation_id: str = "",
    ) -> dict:
        """Create a Graph API webhook subscription for new emails.

        Args:
            notification_url: Public URL to receive webhook notifications.
            correlation_id: Tracing ID.

        Returns:
            Subscription dict from Graph API.
        """
        url = f"{GRAPH_BASE_URL}/subscriptions"
        body = {
            "changeType": "created",
            "notificationUrl": notification_url,
            "resource": f"/users/{self._mailbox}/messages",
            "expirationDateTime": "",  # Will be set by Graph API
            "clientState": "vqms-webhook-secret",
        }
        response = await self._request(
            "POST",
            url,
            json_body=body,
            correlation_id=correlation_id,
        )
        return response.json()

    @log_service_call
    async def download_large_attachment(
        self,
        message_id: str,
        attachment_id: str,
        *,
        correlation_id: str = "",
    ) -> bytes:
        """Download a large attachment (>3MB) separately.

        Small attachments (<3MB) are returned inline as Base64 in
        the message response. Large ones need a separate API call.

        Args:
            message_id: The Exchange Online message ID.
            attachment_id: The attachment ID within the message.
            correlation_id: Tracing ID.

        Returns:
            Attachment content as bytes.
        """
        url = (
            f"{GRAPH_BASE_URL}/users/{self._mailbox}/messages/"
            f"{message_id}/attachments/{attachment_id}/$value"
        )
        response = await self._request(
            "GET",
            url,
            correlation_id=correlation_id,
        )
        return response.content
