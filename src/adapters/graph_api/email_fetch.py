"""Module: adapters/graph_api/email_fetch.py

Email fetching operations via Microsoft Graph API.

Handles fetching individual emails by message ID, listing unread
messages, and the delta-query reconciliation pattern. Used by the
Email Intake Service (Steps E1-E2) and the polling service.
"""

from __future__ import annotations

import structlog
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from adapters.graph_api.client import GRAPH_BASE_URL, _is_retryable
from utils.decorators import log_service_call

logger = structlog.get_logger(__name__)

# Server-side filter applied when listing unread messages.
# Narrows to real unread mail by excluding the most common auto-reply
# subject prefixes. Graph's $filter doesn't support regex, so we chain
# a handful of startswith() clauses — they cover 99% of noise subjects.
UNREAD_FILTER = (
    "isRead eq false"
    " and not(startswith(subject,'Automatic reply'))"
    " and not(startswith(subject,'Auto:'))"
    " and not(startswith(subject,'Out of office'))"
    " and not(startswith(subject,'Undeliverable'))"
    " and not(startswith(subject,'Delivery Status Notification'))"
    " and not(startswith(subject,'Mail Delivery Failure'))"
)


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
        """List unread messages in the mailbox's Inbox folder.

        Scoped to the Inbox only. The mailbox-level /messages endpoint
        would also return unread items from Deleted Items, Archive,
        Junk Email, and every other folder — surprising behavior when
        a human opens Outlook and only sees Inbox contents.

        Used by the reconciliation poller to catch emails that the
        webhook might have missed.

        Args:
            top: Maximum number of messages to return (default 50).
            correlation_id: Tracing ID.

        Returns:
            List of message dicts (id, subject, from, receivedDateTime).
        """
        url = (
            f"{GRAPH_BASE_URL}/users/{self._mailbox}"
            "/mailFolders/Inbox/messages"
        )
        response = await self._request(
            "GET",
            url,
            params={
                "$filter": UNREAD_FILTER,
                "$top": str(top),
                "$select": "id,subject,from,receivedDateTime,conversationId",
            },
            correlation_id=correlation_id,
        )
        data = response.json()
        return data.get("value", [])

    @log_service_call
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    async def delta_query(
        self,
        *,
        delta_link: str | None = None,
        top: int = 50,
        correlation_id: str = "",
    ) -> dict:
        """Run a Graph delta query against the mailbox Inbox folder.

        The delta endpoint returns only what has changed since the
        last call. The first call (no delta_link) walks the current
        state and returns an ``@odata.deltaLink`` we persist; every
        following call uses that link and gets only new/changed mail.

        Reference: docs.microsoft.com/graph/api/message-delta

        Args:
            delta_link: The full ``@odata.deltaLink`` URL from the
                previous poll. Pass None on the very first call to
                start a new delta sequence.
            top: Page size hint for Graph (max 50 for delta).
            correlation_id: Tracing ID.

        Returns:
            Dict with three keys:
              - "messages":   list of message dicts (id, subject,
                              from, receivedDateTime, conversationId,
                              isRead, ...).
              - "delta_link": Updated ``@odata.deltaLink`` to use on
                              the next call. None if Graph returned
                              an ``@odata.nextLink`` instead — caller
                              should keep paging.
              - "next_link":  Next-page link for cases where the delta
                              spans multiple pages.

        Raises:
            GraphAPIError: On non-2xx responses (retries 429/500/502/503).
        """
        if delta_link:
            # Subsequent call — use the persisted link verbatim.
            url = delta_link
            params: dict | None = None
        else:
            # First call — start a new delta sequence on Inbox only.
            url = (
                f"{GRAPH_BASE_URL}/users/{self._mailbox}"
                "/mailFolders/Inbox/messages/delta"
            )
            params = {
                "$top": str(top),
                "$select": (
                    "id,subject,from,receivedDateTime,"
                    "conversationId,isRead"
                ),
            }

        response = await self._request(
            "GET",
            url,
            params=params,
            correlation_id=correlation_id,
        )
        data = response.json()

        return {
            "messages": data.get("value", []),
            "delta_link": data.get("@odata.deltaLink"),
            "next_link": data.get("@odata.nextLink"),
        }

    @log_service_call
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    async def mark_as_read(
        self,
        message_id: str,
        *,
        correlation_id: str = "",
    ) -> None:
        """Mark a single email as read in Exchange Online.

        Idempotent — marking an already-read message is a no-op on the
        server side. Called after successful ingestion (including
        dedup / relevance-rejected paths) so the poller's
        'isRead eq false' filter only surfaces genuinely new mail next
        cycle. Without this, the unread count in Outlook grows forever
        and every poll cycle re-scans the same processed emails.

        Args:
            message_id: Exchange Online message ID.
            correlation_id: Tracing ID.

        Raises:
            GraphAPIError: On non-2xx responses (retries 429/500/502/503).
        """
        url = f"{GRAPH_BASE_URL}/users/{self._mailbox}/messages/{message_id}"
        await self._request(
            "PATCH",
            url,
            json_body={"isRead": True},
            correlation_id=correlation_id,
        )
