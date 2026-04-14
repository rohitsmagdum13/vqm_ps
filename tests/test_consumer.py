"""Tests for the SQS Pipeline Consumer.

Tests message processing (success → delete, failure → no delete)
and initial state construction.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from orchestration.sqs_consumer import PipelineConsumer


@pytest.fixture
def mock_sqs() -> AsyncMock:
    """Mock SQS connector."""
    mock = AsyncMock()
    mock.receive_messages.return_value = []
    mock.delete_message.return_value = None
    return mock


@pytest.fixture
def mock_graph() -> AsyncMock:
    """Mock compiled LangGraph graph."""
    mock = AsyncMock()
    mock.ainvoke.return_value = {
        "query_id": "VQ-2026-0001",
        "status": "RESOLVED",
        "processing_path": "A",
    }
    return mock


@pytest.fixture
def consumer(mock_sqs, mock_graph, mock_settings, mock_postgres) -> PipelineConsumer:
    """Create a PipelineConsumer with mocked dependencies."""
    return PipelineConsumer(
        sqs=mock_sqs,
        compiled_graph=mock_graph,
        postgres=mock_postgres,
        settings=mock_settings,
    )


@pytest.fixture
def sample_sqs_message() -> dict:
    """A parsed SQS message as returned by SQSConnector.receive_messages."""
    return {
        "message_id": "msg-001",
        "receipt_handle": "rh-001",
        "body": {
            "query_id": "VQ-2026-0001",
            "correlation_id": "test-corr-001",
            "execution_id": "test-exec-001",
            "source": "email",
            "unified_payload": {
                "query_id": "VQ-2026-0001",
                "vendor_id": "V-001",
                "subject": "Invoice question",
                "body": "I have a question about invoice INV-5678.",
                "source": "email",
                "attachments": [],
            },
        },
    }


class TestProcessMessage:
    """Tests for PipelineConsumer.process_message."""

    @pytest.mark.asyncio
    async def test_success_returns_result(
        self, consumer, sample_sqs_message, mock_graph
    ) -> None:
        """Successful processing returns the final state."""
        result = await consumer.process_message(sample_sqs_message)

        assert result["status"] == "RESOLVED"
        assert result["processing_path"] == "A"
        mock_graph.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_initial_state_has_required_fields(
        self, consumer, sample_sqs_message, mock_graph
    ) -> None:
        """Graph is called with a properly structured initial state."""
        await consumer.process_message(sample_sqs_message)

        call_args = mock_graph.ainvoke.call_args[0][0]
        assert call_args["query_id"] == "VQ-2026-0001"
        assert call_args["correlation_id"] == "test-corr-001"
        assert call_args["source"] == "email"
        assert call_args["status"] == "RECEIVED"
        assert "created_at" in call_args
        assert "updated_at" in call_args
        assert "unified_payload" in call_args

    @pytest.mark.asyncio
    async def test_graph_failure_raises(
        self, consumer, sample_sqs_message, mock_graph
    ) -> None:
        """Graph failure propagates so message stays in queue."""
        mock_graph.ainvoke.side_effect = RuntimeError("Graph exploded")

        with pytest.raises(RuntimeError, match="Graph exploded"):
            await consumer.process_message(sample_sqs_message)

    @pytest.mark.asyncio
    async def test_missing_correlation_id_generates_one(
        self, consumer, mock_graph
    ) -> None:
        """Missing correlation_id in message body generates a new one."""
        message = {
            "message_id": "msg-002",
            "receipt_handle": "rh-002",
            "body": {
                "query_id": "VQ-2026-0002",
                "source": "portal",
                "unified_payload": {"subject": "Test"},
            },
        }

        await consumer.process_message(message)

        call_args = mock_graph.ainvoke.call_args[0][0]
        # Should have a generated correlation_id (not empty)
        assert len(call_args["correlation_id"]) > 0


class TestConsumerControl:
    """Tests for consumer start/stop control."""

    def test_stop_sets_running_false(self, consumer) -> None:
        """Calling stop() should set _running to False."""
        consumer._running = True
        consumer.stop()
        assert consumer._running is False
