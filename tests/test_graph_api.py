"""Tests for GraphAPIConnector.

All tests mock MSAL token acquisition and httpx responses.
No real Microsoft Graph API calls are made.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from adapters.graph_api import GraphAPIConnector
from utils.exceptions import GraphAPIError


@pytest.fixture
def graph_connector(mock_settings) -> GraphAPIConnector:
    """Create a GraphAPIConnector with mocked MSAL app."""
    connector = GraphAPIConnector(mock_settings)
    # Mock the MSAL app to return a valid token
    connector._msal_app = MagicMock()
    connector._msal_app.acquire_token_for_client.return_value = {
        "access_token": "fake-access-token-12345",
        "token_type": "Bearer",
        "expires_in": 3600,
    }
    return connector


def _mock_response(status_code: int = 200, json_data: dict | None = None) -> httpx.Response:
    """Create a mock httpx.Response with the given status and JSON body."""
    return httpx.Response(
        status_code=status_code,
        json=json_data or {},
        request=httpx.Request("GET", "https://graph.microsoft.com/v1.0/test"),
    )


class TestGraphAPITokenAcquisition:
    """Tests for MSAL token caching and acquisition."""

    async def test_acquire_token_returns_access_token(self, graph_connector) -> None:
        """Token acquisition returns the access_token string."""
        token = await graph_connector._acquire_token(correlation_id="test-001")
        assert token == "fake-access-token-12345"

    async def test_acquire_token_caches_result(self, graph_connector) -> None:
        """Calling acquire twice still calls MSAL each time (MSAL handles internal cache)."""
        await graph_connector._acquire_token()
        await graph_connector._acquire_token()
        # MSAL is called each time — it handles caching internally
        assert graph_connector._msal_app.acquire_token_for_client.call_count == 2

    async def test_acquire_token_raises_on_failure(self, graph_connector) -> None:
        """GraphAPIError raised when MSAL returns an error response."""
        graph_connector._msal_app.acquire_token_for_client.return_value = {
            "error": "invalid_client",
            "error_description": "Client secret is invalid",
        }
        with pytest.raises(GraphAPIError):
            await graph_connector._acquire_token(correlation_id="test-002")


class TestGraphAPIFetchEmail:
    """Tests for fetch_email method."""

    async def test_fetch_email_returns_dict(
        self, graph_connector, sample_email_response
    ) -> None:
        """fetch_email returns the parsed JSON response dict."""
        mock_response = _mock_response(200, sample_email_response)

        # Mock the httpx client
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.request.return_value = mock_response
        graph_connector._http_client = mock_client

        result = await graph_connector.fetch_email(
            "AAMkAGI2TG93AAA=", correlation_id="test-010"
        )
        assert result["id"] == "AAMkAGI2TG93AAA="
        assert result["subject"] == "Invoice discrepancy for PO-2026-1234"

    async def test_fetch_email_raises_on_401(self, graph_connector) -> None:
        """GraphAPIError raised on 401 Unauthorized (not retried)."""
        mock_response = _mock_response(401, {"error": {"code": "InvalidAuthenticationToken"}})

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.request.return_value = mock_response
        graph_connector._http_client = mock_client

        with pytest.raises(GraphAPIError) as exc_info:
            await graph_connector.fetch_email("AAMkAGI2TG93AAA=")
        assert exc_info.value.status_code == 401

    async def test_fetch_email_retries_on_429(self, graph_connector, sample_email_response) -> None:
        """fetch_email retries on 429 (throttled), then succeeds."""
        response_429 = _mock_response(429, {"error": {"code": "TooManyRequests"}})
        response_200 = _mock_response(200, sample_email_response)

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        # First call returns 429, second returns 200
        mock_client.request.side_effect = [response_429, response_200]
        graph_connector._http_client = mock_client

        # The _request method raises GraphAPIError on 429, which triggers retry
        # But since _request raises, we need the retry decorator to handle it
        # Let's verify the retry by checking the call count
        # Actually, fetch_email calls _request which raises on 429.
        # The @retry decorator on fetch_email catches GraphAPIError(429) and retries.
        result = await graph_connector.fetch_email(
            "AAMkAGI2TG93AAA=", correlation_id="test-retry"
        )
        assert result["id"] == "AAMkAGI2TG93AAA="
        assert mock_client.request.call_count == 2


class TestGraphAPIListUnread:
    """Tests for list_unread_messages method."""

    async def test_list_unread_returns_list(self, graph_connector) -> None:
        """list_unread_messages returns a list of message dicts."""
        messages = [
            {"id": "msg-1", "subject": "Query 1"},
            {"id": "msg-2", "subject": "Query 2"},
        ]
        mock_response = _mock_response(200, {"value": messages})

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.request.return_value = mock_response
        graph_connector._http_client = mock_client

        result = await graph_connector.list_unread_messages(
            top=10, correlation_id="test-020"
        )
        assert len(result) == 2
        assert result[0]["id"] == "msg-1"
        assert result[1]["id"] == "msg-2"

        # The query must be scoped to the Inbox folder, otherwise unread
        # items in Deleted Items / Archive / Junk leak through.
        called_url = mock_client.request.call_args.kwargs["url"]
        assert "/mailFolders/Inbox/messages" in called_url

    async def test_list_unread_empty_returns_empty_list(self, graph_connector) -> None:
        """Empty mailbox returns an empty list."""
        mock_response = _mock_response(200, {"value": []})

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.request.return_value = mock_response
        graph_connector._http_client = mock_client

        result = await graph_connector.list_unread_messages()
        assert result == []


class TestGraphAPISendEmail:
    """Tests for send_email method."""

    async def test_send_email_posts_correctly(self, graph_connector) -> None:
        """send_email makes a POST request with correct body structure."""
        mock_response = _mock_response(202, {})

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.request.return_value = mock_response
        graph_connector._http_client = mock_client

        await graph_connector.send_email(
            to="vendor@example.com",
            subject="Re: Your query",
            body_html="<p>Your issue has been resolved.</p>",
            correlation_id="test-030",
        )

        # Verify the request was made
        mock_client.request.assert_called_once()
        call_kwargs = mock_client.request.call_args
        assert call_kwargs.kwargs["method"] == "POST"
        assert "sendMail" in call_kwargs.kwargs["url"]

        # Verify the body structure
        body = call_kwargs.kwargs["json"]
        assert "message" in body
        assert body["message"]["subject"] == "Re: Your query"
        assert body["message"]["toRecipients"][0]["emailAddress"]["address"] == "vendor@example.com"


class TestGraphAPIClose:
    """Tests for close method."""

    async def test_close_closes_http_client(self, graph_connector) -> None:
        """close() shuts down the httpx client."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        graph_connector._http_client = mock_client

        await graph_connector.close()

        mock_client.aclose.assert_called_once()
        assert graph_connector._http_client is None

    async def test_close_when_no_client_is_noop(self, graph_connector) -> None:
        """close() is safe to call when no client exists."""
        graph_connector._http_client = None
        await graph_connector.close()  # Should not raise
