"""Module: adapters/graph_api/client.py

Microsoft Graph API client initialization and authentication.

Manages MSAL OAuth2 client_credentials flow and provides
the shared _request() helper used by all Graph API operation
classes. Uses httpx.AsyncClient for truly async HTTP calls.
"""

from __future__ import annotations

import asyncio

import httpx
import msal
import structlog

from config.settings import Settings
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


class GraphAPIClient:
    """Base Graph API client with MSAL authentication.

    Both the MSAL app and httpx client are lazy-initialized on
    first use. This avoids OIDC tenant discovery during __init__,
    which would fail in tests and dev environments without real
    Azure AD credentials.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize with application settings.

        Does NOT connect to Graph API yet. Both MSAL and httpx
        are created lazily on first API call.
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

    async def close(self) -> None:
        """Close the httpx client. Call on application shutdown."""
        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None
