"""Tests for ReconciliationPoller.

All connectors are mocked. Tests verify that the poller
correctly processes unread emails, skips duplicates, and
continues on individual message errors.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from services.polling import ReconciliationPoller


@pytest.fixture
def mock_email_intake() -> AsyncMock:
    """Mock EmailIntakeService."""
    mock = AsyncMock()
    # Default: process_email returns a result (not None = newly processed)
    mock.process_email.return_value = AsyncMock()
    return mock


@pytest.fixture
def poller(mock_email_intake, mock_graph_api, mock_settings) -> ReconciliationPoller:
    """Create a ReconciliationPoller with mocked dependencies."""
    return ReconciliationPoller(
        email_intake=mock_email_intake,
        graph_api=mock_graph_api,
        settings=mock_settings,
    )


class TestPollOnce:
    """Tests for the poll_once method."""

    async def test_processes_unread_emails(
        self, poller, mock_graph_api, mock_email_intake
    ) -> None:
        """Each unread email is passed to process_email."""
        mock_graph_api.list_unread_messages.return_value = [
            {"id": "msg-001", "subject": "Query 1"},
            {"id": "msg-002", "subject": "Query 2"},
        ]

        count = await poller.poll_once(correlation_id="test-poll-001")

        assert count == 2
        assert mock_email_intake.process_email.call_count == 2

    async def test_skips_duplicates(
        self, poller, mock_graph_api, mock_email_intake
    ) -> None:
        """Duplicate emails (process_email returns None) are counted as 0."""
        mock_graph_api.list_unread_messages.return_value = [
            {"id": "msg-dup-001", "subject": "Already processed"},
        ]
        # Return None = duplicate (already processed via webhook)
        mock_email_intake.process_email.return_value = None

        count = await poller.poll_once()

        assert count == 0
        mock_email_intake.process_email.assert_called_once()

    async def test_continues_on_error(
        self, poller, mock_graph_api, mock_email_intake
    ) -> None:
        """Error on one email doesn't block processing of the next."""
        mock_graph_api.list_unread_messages.return_value = [
            {"id": "msg-fail", "subject": "Will fail"},
            {"id": "msg-ok", "subject": "Will succeed"},
        ]
        # First call raises, second succeeds
        mock_email_intake.process_email.side_effect = [
            Exception("Processing failed"),
            AsyncMock(),  # Success
        ]

        count = await poller.poll_once()

        # Only the second email was successfully processed
        assert count == 1
        assert mock_email_intake.process_email.call_count == 2

    async def test_empty_mailbox_returns_zero(
        self, poller, mock_graph_api, mock_email_intake
    ) -> None:
        """Empty mailbox returns 0 and doesn't call process_email."""
        mock_graph_api.list_unread_messages.return_value = []

        count = await poller.poll_once()

        assert count == 0
        mock_email_intake.process_email.assert_not_called()

    async def test_graph_api_failure_returns_zero(
        self, poller, mock_graph_api, mock_email_intake
    ) -> None:
        """Graph API failure returns 0 without crashing."""
        mock_graph_api.list_unread_messages.side_effect = Exception("Graph API down")

        count = await poller.poll_once()

        assert count == 0
        mock_email_intake.process_email.assert_not_called()


class TestPollerLifecycle:
    """Tests for start/stop behavior."""

    def test_stop_sets_running_false(self, poller) -> None:
        """stop() sets the _running flag to False."""
        poller._running = True
        poller.stop()
        assert poller._running is False
