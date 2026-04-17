"""Module: adapters/graph_api/email_fetch.py

Email fetching operations via Microsoft Graph API.

Handles fetching individual emails by message ID and listing
unread messages for reconciliation polling. Used by the Email
Intake Service (Steps E1-E2) and the polling service.
"""

from __future__ import annotations

import structlog
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from adapters.graph_api.client import GRAPH_BASE_URL, _is_retryable
from utils.decorators import log_service_call

logger = structlog.get_logger(__name__)


class EmailFetchMixin:
    """Email fetch methods for the Graph API connector.

    Mixed into GraphAPIConnector. Expects self._request()
    and self._mailbox from GraphAPIClient.
    """

    @log_service_call
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    async def fetch_email(
        self,
        message_id: str,
        *,
        correlation_id: str = "",
    ) -> dict:
        """Fetch a single email from Exchange Online via Graph API.

        Expands attachments inline so they're included in the response.

        Args:
            message_id: The Exchange Online message ID.
            correlation_id: Tracing ID.

        Returns:
            Full message dict from Graph API (includes from, subject,
            body, attachments, conversationId, etc.).

        Raises:
            GraphAPIError: On API errors (retries on 429/500/502/503).
        """
        url = f"{GRAPH_BASE_URL}/users/{self._mailbox}/messages/{message_id}"
        response = await self._request(
            "GET",
            url,
            params={"$expand": "attachments"},
            correlation_id=correlation_id,
        )
        return response.json()

    @log_service_call
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    async def list_unread_messages(
        self,
        *,
        top: int = 50,
        correlation_id: str = "",
    ) -> list[dict]:
        """List unread messages in the shared mailbox.

        Used by the reconciliation poller to catch emails that
        the webhook might have missed.

        Args:
            top: Maximum number of messages to return (default 50).
            correlation_id: Tracing ID.

        Returns:
            List of message dicts (id, subject, from, receivedDateTime).
        """
        url = f"{GRAPH_BASE_URL}/users/{self._mailbox}/messages"
        response = await self._request(
            "GET",
            url,
            params={
                "$filter": "isRead eq false",
                "$top": str(top),
                "$select": "id,subject,from,receivedDateTime,conversationId",
            },
            correlation_id=correlation_id,
        )
        data = response.json()
        return data.get("value", [])
