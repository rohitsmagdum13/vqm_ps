"""Module: connectors/graph_api.py

Microsoft Graph API connector for VQMS.

Handles OAuth2 authentication via MSAL, email fetch/send via
Graph API, webhook subscription for real-time email detection,
and reconciliation polling for missed emails.

Uses httpx.AsyncClient for truly async HTTP calls. MSAL token
acquisition is synchronous and wrapped in asyncio.to_thread.

Usage:
    from connectors.graph_api import GraphAPIConnector
    from config.settings import get_settings

    graph = GraphAPIConnector(get_settings())
    email = await graph.fetch_email("AAMkAGI2...", correlation_id="abc-123")
    await graph.send_email("vendor@example.com", "Subject", "<p>Body</p>")
    unread = await graph.list_unread_messages(top=50)
    await graph.close()
"""

from __future__ import annotations

import asyncio

import httpx
import msal
import structlog
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from config.settings import Settings
from utils.decorators import log_service_call
from utils.exceptions import GraphAPIError

logger = structlog.get_logger(__name__)

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPES = ["https://graph.microsoft.com/.default"]


def _is_retryable(exc: BaseException) -> bool:
    """Check if a Graph API error is transient and worth retrying.

    Retries on: 429 (throttled), 500, 502, 503 (server errors).
    Does NOT retry on: 401 (auth), 403 (forbidden), 404 (not found).
    """
    return isinstance(exc, GraphAPIError) and exc.status_code in (429, 500, 502, 503)


class GraphAPIConnector:
    """Microsoft Graph API connector for email operations.

    Handles MSAL OAuth2 client_credentials flow for authentication,
    email fetch/send, webhook subscription, and unread listing.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize with application settings.

        Both the MSAL app and httpx client are lazy-initialized on
        first use. This avoids OIDC tenant discovery during __init__,
        which would fail in tests and dev environments without real
        Azure AD credentials.
        """
        self._tenant_id = settings.graph_api_tenant_id or ""
        self._client_id = settings.graph_api_client_id or ""
        self._client_secret = settings.graph_api_client_secret or ""
        self._mailbox = settings.graph_api_mailbox

        # Lazy-initialized — created on first token acquisition
        self._msal_app: msal.ConfidentialClientApplication | None = None
        self._http_client: httpx.AsyncClient | None = None
        self._cached_token: dict | None = None

    def _get_msal_app(self) -> msal.ConfidentialClientApplication:
        """Get or create the MSAL ConfidentialClientApplication.

        Lazy initialization avoids OIDC tenant discovery at import
        time, which fails in tests with fake tenant IDs.
        """
        if self._msal_app is None:
            authority = f"https://login.microsoftonline.com/{self._tenant_id}"
            self._msal_app = msal.ConfidentialClientApplication(
                self._client_id,
                authority=authority,
                client_credential=self._client_secret,
            )
        return self._msal_app

    async def _acquire_token(self, *, correlation_id: str = "") -> str:
        """Acquire an OAuth2 access token, using cache when possible.

        MSAL handles token caching internally, but we also cache
        the result dict to avoid calling MSAL on every request.

        Returns:
            Access token string.

        Raises:
            GraphAPIError: If token acquisition fails.
        """
        # MSAL's acquire_token_for_client handles caching internally
        msal_app = self._get_msal_app()
        result = await asyncio.to_thread(
            msal_app.acquire_token_for_client,
            scopes=GRAPH_SCOPES,
        )

        if "access_token" not in result:
            error_desc = result.get("error_description", "Unknown MSAL error")
            logger.error(
                "MSAL token acquisition failed",
                tool="graph_api",
                error=result.get("error", "unknown"),
                error_description=error_desc,
                correlation_id=correlation_id,
            )
            raise GraphAPIError(
                endpoint="token",
                status_code=401,
                correlation_id=correlation_id,
            )

        self._cached_token = result
        return result["access_token"]

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create the httpx async client."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: dict | None = None,
        params: dict | None = None,
        correlation_id: str = "",
    ) -> httpx.Response:
        """Make an authenticated request to the Graph API.

        Args:
            method: HTTP method (GET, POST, etc.).
            url: Full Graph API URL.
            json_body: Optional JSON request body.
            params: Optional query parameters.
            correlation_id: Tracing ID.

        Returns:
            httpx.Response object.

        Raises:
            GraphAPIError: On non-2xx responses.
        """
        token = await self._acquire_token(correlation_id=correlation_id)
        client = await self._get_http_client()

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        response = await client.request(
            method=method,
            url=url,
            headers=headers,
            json=json_body,
            params=params,
        )

        if response.status_code >= 400:
            logger.error(
                "Graph API request failed",
                tool="graph_api",
                method=method,
                url=url,
                status_code=response.status_code,
                correlation_id=correlation_id,
            )
            raise GraphAPIError(
                endpoint=url,
                status_code=response.status_code,
                correlation_id=correlation_id,
            )

        return response

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
    async def send_email(
        self,
        to: str,
        subject: str,
        body_html: str,
        *,
        reply_to_message_id: str | None = None,
        correlation_id: str = "",
    ) -> None:
        """Send an email via Graph API.

        Args:
            to: Recipient email address.
            subject: Email subject.
            body_html: HTML body content.
            reply_to_message_id: Optional message ID to reply to.
            correlation_id: Tracing ID.

        Raises:
            GraphAPIError: On API errors.
        """
        message = {
            "subject": subject,
            "body": {
                "contentType": "HTML",
                "content": body_html,
            },
            "toRecipients": [
                {"emailAddress": {"address": to}}
            ],
        }

        url = f"{GRAPH_BASE_URL}/users/{self._mailbox}/sendMail"
        await self._request(
            "POST",
            url,
            json_body={"message": message, "saveToSentItems": True},
            correlation_id=correlation_id,
        )

        logger.info(
            "Email sent via Graph API",
            tool="graph_api",
            to=to,
            subject=subject,
            correlation_id=correlation_id,
        )

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

    async def close(self) -> None:
        """Close the httpx client. Call on application shutdown."""
        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None
