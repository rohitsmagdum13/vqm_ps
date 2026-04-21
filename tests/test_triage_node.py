"""Tests for the Triage Node (Path C entry point).

Verifies the node builds a TriagePackage, persists it, updates
case_execution to PAUSED, and publishes the HumanReviewRequired
event when EventBridge is available.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from orchestration.nodes.triage import TriageNode


def _base_state(confidence: float = 0.40) -> dict:
    """Pipeline state as it looks when Path C triggers — analysis is done
    but routing/KB search have not run yet."""
    return {
        "query_id": "VQ-2026-0099",
        "correlation_id": "corr-99",
        "execution_id": "exec-99",
        "source": "email",
        "unified_payload": {
            "query_id": "VQ-2026-0099",
            "vendor_id": "V-001",
            "subject": "Strange request",
            "body": "Please help with this unusual ask.",
            "source": "email",
            "attachments": [],
        },
        "analysis_result": {
            "intent_classification": "UNKNOWN",
            "confidence_score": confidence,
            "urgency_level": "MEDIUM",
            "sentiment": "NEUTRAL",
            "suggested_category": "general",
            "extracted_entities": {"invoice_number": "INV-1"},
            "multi_issue_detected": False,
        },
        "status": "PAUSED",
        "processing_path": "C",
    }


@pytest.fixture
def mock_eventbridge() -> AsyncMock:
    eb = AsyncMock()
    eb.publish_event.return_value = None
    return eb


@pytest.mark.asyncio
async def test_triage_node_persists_package_and_pauses(
    mock_postgres: AsyncMock, mock_eventbridge: AsyncMock, mock_settings
) -> None:
    """Happy path: build package, persist it, update case_execution, publish event."""
    node = TriageNode(
        postgres=mock_postgres,
        eventbridge=mock_eventbridge,
        settings=mock_settings,
    )

    result = await node.execute(_base_state())

    # State update shape
    assert result["status"] == "PAUSED"
    package = result["triage_package"]
    assert package["query_id"] == "VQ-2026-0099"
    assert package["correlation_id"] == "corr-99"
    # callback_token is a uuid4 string
    assert isinstance(package["callback_token"], str)
    assert len(package["callback_token"]) == 36
    # Confidence breakdown is derived and present
    breakdown = package["confidence_breakdown"]
    assert breakdown["overall"] == 0.40
    assert breakdown["threshold"] == mock_settings.agent_confidence_threshold

    # Two INSERTs: triage_packages + case_execution update
    assert mock_postgres.execute.await_count == 2

    # HumanReviewRequired event fired
    mock_eventbridge.publish_event.assert_awaited_once()
    event_name = mock_eventbridge.publish_event.await_args.args[0]
    assert event_name == "HumanReviewRequired"


@pytest.mark.asyncio
async def test_triage_node_continues_when_eventbridge_missing(
    mock_postgres: AsyncMock, mock_settings
) -> None:
    """If EventBridge is None, the node still persists and returns PAUSED."""
    node = TriageNode(
        postgres=mock_postgres,
        eventbridge=None,
        settings=mock_settings,
    )

    result = await node.execute(_base_state())

    assert result["status"] == "PAUSED"
    assert "triage_package" in result
    assert mock_postgres.execute.await_count == 2


@pytest.mark.asyncio
async def test_triage_node_survives_eventbridge_failure(
    mock_postgres: AsyncMock, mock_settings
) -> None:
    """EventBridge publish failure must not block the workflow pause — it's non-critical."""
    eb = AsyncMock()
    eb.publish_event.side_effect = RuntimeError("EB down")

    node = TriageNode(
        postgres=mock_postgres,
        eventbridge=eb,
        settings=mock_settings,
    )

    # Should not raise
    result = await node.execute(_base_state())

    assert result["status"] == "PAUSED"
    assert mock_postgres.execute.await_count == 2


@pytest.mark.asyncio
async def test_triage_node_propagates_postgres_failure(
    mock_settings,
) -> None:
    """Postgres persistence is CRITICAL — failure must propagate so SQS retries."""
    pg = AsyncMock()
    pg.execute.side_effect = RuntimeError("DB down")
    node = TriageNode(
        postgres=pg,
        eventbridge=None,
        settings=mock_settings,
    )

    with pytest.raises(RuntimeError, match="DB down"):
        await node.execute(_base_state())


@pytest.mark.asyncio
async def test_confidence_breakdown_lowers_for_missing_entities(
    mock_postgres: AsyncMock, mock_settings
) -> None:
    """No extracted entities → entity_confidence is lowered below overall."""
    node = TriageNode(
        postgres=mock_postgres, eventbridge=None, settings=mock_settings,
    )
    state = _base_state(confidence=0.50)
    state["analysis_result"]["extracted_entities"] = {}

    result = await node.execute(state)
    breakdown = result["triage_package"]["confidence_breakdown"]
    assert breakdown["overall"] == 0.50
    assert breakdown["entity_extraction"] < breakdown["overall"]


@pytest.mark.asyncio
async def test_confidence_breakdown_lowers_for_multi_issue(
    mock_postgres: AsyncMock, mock_settings
) -> None:
    """Multi-issue detection → single_issue_detection dimension is lowered."""
    node = TriageNode(
        postgres=mock_postgres, eventbridge=None, settings=mock_settings,
    )
    state = _base_state(confidence=0.60)
    state["analysis_result"]["multi_issue_detected"] = True

    result = await node.execute(state)
    breakdown = result["triage_package"]["confidence_breakdown"]
    assert breakdown["single_issue_detection"] < breakdown["overall"]
