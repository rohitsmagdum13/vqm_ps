"""Tests for the TriageService (Path C reviewer queue + resume).

Covers:
- list_pending: correct ordering and limit clamping
- get_package: happy path + TriagePackageNotFoundError
- submit_decision: happy path (sqs), already-reviewed, not-found,
  db_only fallback (SQS missing), db_only fallback (SQS throws)
- _apply_corrections: confidence + human_validated + immutability
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import orjson
import pytest

from models.triage import ReviewerDecision
from services.triage import (
    TriageAlreadyReviewedError,
    TriagePackageNotFoundError,
    TriageService,
)
from utils.helpers import TimeHelper


# ---------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------


@pytest.fixture
def mock_sqs() -> AsyncMock:
    """AsyncMock SQSConnector — send_message succeeds by default."""
    sqs = AsyncMock()
    sqs.send_message.return_value = None
    return sqs


@pytest.fixture
def mock_eventbridge() -> AsyncMock:
    """AsyncMock EventBridgeConnector — publish_event succeeds by default."""
    eb = AsyncMock()
    eb.publish_event.return_value = None
    return eb


def _sample_unified_payload(query_id: str = "VQ-2026-0099") -> dict:
    return {
        "query_id": query_id,
        "correlation_id": "corr-99",
        "execution_id": "exec-99",
        "source": "email",
        "vendor_id": "V-001",
        "subject": "Unusual request",
        "body": "Please help with this unusual ask.",
        "priority": "MEDIUM",
        "received_at": "2026-04-12T10:30:00+05:30",
        "attachments": [],
        "thread_status": "NEW",
        "metadata": {},
    }


def _sample_analysis_result() -> dict:
    return {
        "intent_classification": "UNKNOWN",
        "extracted_entities": {"invoice_number": "INV-1"},
        "urgency_level": "MEDIUM",
        "sentiment": "NEUTRAL",
        "confidence_score": 0.40,
        "multi_issue_detected": False,
        "suggested_category": "general",
        "analysis_duration_ms": 1500,
        "model_id": "anthropic.claude-3-5-sonnet",
        "tokens_in": 1500,
        "tokens_out": 50,
    }


def _sample_package_dict(
    query_id: str = "VQ-2026-0099",
    callback_token: str = "token-abc-123-uuid-v4-0000000000000000",
) -> dict:
    """A fully-shaped TriagePackage dict matching the Pydantic schema."""
    return {
        "query_id": query_id,
        "correlation_id": "corr-99",
        "callback_token": callback_token,
        "original_query": _sample_unified_payload(query_id),
        "analysis_result": _sample_analysis_result(),
        "confidence_breakdown": {
            "overall": 0.40,
            "intent_classification": 0.40,
            "entity_extraction": 0.40,
            "single_issue_detection": 0.40,
            "threshold": 0.85,
        },
        "suggested_routing": None,
        "suggested_draft": None,
        "created_at": "2026-04-12T10:30:00+05:30",
    }


def _make_decision(
    query_id: str = "VQ-2026-0099",
    reviewer_id: str = "reviewer-01",
    *,
    confidence_override: float | None = None,
    corrected_intent: str | None = "invoice_inquiry",
    corrected_vendor_id: str | None = "V-001",
    reviewer_notes: str = "Intent corrected after human review.",
) -> ReviewerDecision:
    return ReviewerDecision(
        query_id=query_id,
        reviewer_id=reviewer_id,
        corrected_intent=corrected_intent,
        corrected_vendor_id=corrected_vendor_id,
        corrected_routing="finance-ops",
        confidence_override=confidence_override,
        reviewer_notes=reviewer_notes,
        decided_at=TimeHelper.ist_now(),
    )


@pytest.fixture
def triage_service(
    mock_postgres: AsyncMock,
    mock_sqs: AsyncMock,
    mock_eventbridge: AsyncMock,
    mock_settings,
) -> TriageService:
    return TriageService(
        postgres=mock_postgres,
        sqs=mock_sqs,
        eventbridge=mock_eventbridge,
        settings=mock_settings,
    )


# ---------------------------------------------------------------
# list_pending
# ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_pending_returns_ordered_items(
    mock_postgres: AsyncMock, triage_service: TriageService,
) -> None:
    """Queue items come back as TriageQueueItem ordered by DB (oldest-first)."""
    now = datetime(2026, 4, 12, 10, 0, 0)
    mock_postgres.fetch.return_value = [
        {
            "query_id": "VQ-2026-0001",
            "correlation_id": "corr-1",
            "original_confidence": 0.40,
            "suggested_category": "billing",
            "status": "PENDING",
            "created_at": now,
        },
        {
            "query_id": "VQ-2026-0002",
            "correlation_id": "corr-2",
            "original_confidence": 0.55,
            "suggested_category": "general",
            "status": "PENDING",
            "created_at": now,
        },
    ]

    items = await triage_service.list_pending(limit=50)

    assert len(items) == 2
    assert items[0].query_id == "VQ-2026-0001"
    assert items[0].original_confidence == 0.40
    assert items[1].query_id == "VQ-2026-0002"

    # Verify the query was issued with status=PENDING and the clamped limit
    call_args = mock_postgres.fetch.await_args
    assert call_args.args[1] == "PENDING"
    assert call_args.args[2] == 50


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_limit, expected_limit",
    [(0, 1), (-5, 1), (10, 10), (300, 200), (1000, 200)],
)
async def test_list_pending_clamps_limit(
    mock_postgres: AsyncMock,
    triage_service: TriageService,
    raw_limit: int,
    expected_limit: int,
) -> None:
    """list_pending clamps limit into [1, 200]."""
    mock_postgres.fetch.return_value = []
    await triage_service.list_pending(limit=raw_limit)
    assert mock_postgres.fetch.await_args.args[2] == expected_limit


# ---------------------------------------------------------------
# get_package
# ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_package_returns_pydantic_model(
    mock_postgres: AsyncMock, triage_service: TriageService,
) -> None:
    """get_package decodes JSONB and builds a TriagePackage."""
    package_dict = _sample_package_dict()
    mock_postgres.fetchrow.return_value = {
        "query_id": "VQ-2026-0099",
        "correlation_id": "corr-99",
        "package_data": orjson.dumps(package_dict).decode("utf-8"),
        "status": "PENDING",
        "created_at": datetime(2026, 4, 12, 10, 30, 0),
    }

    package = await triage_service.get_package("VQ-2026-0099")

    assert package.query_id == "VQ-2026-0099"
    assert package.callback_token == package_dict["callback_token"]
    assert package.analysis_result.confidence_score == 0.40
    assert package.suggested_routing is None


@pytest.mark.asyncio
async def test_get_package_raises_when_missing(
    mock_postgres: AsyncMock, triage_service: TriageService,
) -> None:
    """get_package raises TriagePackageNotFoundError when the row is missing."""
    mock_postgres.fetchrow.return_value = None

    with pytest.raises(TriagePackageNotFoundError) as exc_info:
        await triage_service.get_package("VQ-2026-UNKNOWN")

    assert exc_info.value.query_id == "VQ-2026-UNKNOWN"


# ---------------------------------------------------------------
# submit_decision — happy path
# ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_decision_happy_path(
    mock_postgres: AsyncMock,
    mock_sqs: AsyncMock,
    mock_eventbridge: AsyncMock,
    triage_service: TriageService,
) -> None:
    """Decision row inserted, package flipped REVIEWED, SQS sent, event fired."""
    package_dict = _sample_package_dict()
    mock_postgres.fetchrow.return_value = {
        "query_id": "VQ-2026-0099",
        "correlation_id": "corr-99",
        "package_data": orjson.dumps(package_dict).decode("utf-8"),
        "status": "PENDING",
    }

    decision = _make_decision()
    result = await triage_service.submit_decision("VQ-2026-0099", decision)

    assert result == {
        "status": "REVIEWED",
        "query_id": "VQ-2026-0099",
        "resume_method": "sqs",
    }

    # Three execute calls: decision insert, package UPDATE, case_execution UPDATE
    assert mock_postgres.execute.await_count == 3

    # SQS re-enqueue with resume_context carries corrected_analysis + from_triage=True
    mock_sqs.send_message.assert_awaited_once()
    sent_queue_url, sent_body = mock_sqs.send_message.await_args.args[:2]
    assert "query-intake" in sent_queue_url
    assert sent_body["resume_context"]["from_triage"] is True
    assert sent_body["resume_context"]["corrected_analysis"]["human_validated"] is True

    # HumanReviewCompleted event published
    mock_eventbridge.publish_event.assert_awaited_once()
    assert mock_eventbridge.publish_event.await_args.args[0] == "HumanReviewCompleted"


# ---------------------------------------------------------------
# submit_decision — error + fallback paths
# ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_decision_raises_when_missing(
    mock_postgres: AsyncMock, triage_service: TriageService,
) -> None:
    """No row → TriagePackageNotFoundError."""
    mock_postgres.fetchrow.return_value = None

    with pytest.raises(TriagePackageNotFoundError):
        await triage_service.submit_decision("VQ-UNKNOWN", _make_decision("VQ-UNKNOWN"))


@pytest.mark.asyncio
async def test_submit_decision_raises_when_already_reviewed(
    mock_postgres: AsyncMock, triage_service: TriageService,
) -> None:
    """Row in REVIEWED status → TriageAlreadyReviewedError (idempotency guard)."""
    package_dict = _sample_package_dict()
    mock_postgres.fetchrow.return_value = {
        "query_id": "VQ-2026-0099",
        "correlation_id": "corr-99",
        "package_data": orjson.dumps(package_dict).decode("utf-8"),
        "status": "REVIEWED",
    }

    with pytest.raises(TriageAlreadyReviewedError):
        await triage_service.submit_decision("VQ-2026-0099", _make_decision())


@pytest.mark.asyncio
async def test_submit_decision_falls_back_to_db_only_when_sqs_missing(
    mock_postgres: AsyncMock,
    mock_eventbridge: AsyncMock,
    mock_settings,
) -> None:
    """sqs=None → resume_method='db_only' but package still flipped REVIEWED."""
    package_dict = _sample_package_dict()
    mock_postgres.fetchrow.return_value = {
        "query_id": "VQ-2026-0099",
        "correlation_id": "corr-99",
        "package_data": orjson.dumps(package_dict).decode("utf-8"),
        "status": "PENDING",
    }

    service = TriageService(
        postgres=mock_postgres,
        sqs=None,
        eventbridge=mock_eventbridge,
        settings=mock_settings,
    )

    result = await service.submit_decision("VQ-2026-0099", _make_decision())

    assert result["resume_method"] == "db_only"
    # Audit trail still persisted: decision + package update + case_execution update
    assert mock_postgres.execute.await_count == 3
    # Event still fires so observability is unaffected
    mock_eventbridge.publish_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_submit_decision_falls_back_to_db_only_when_sqs_throws(
    mock_postgres: AsyncMock,
    mock_eventbridge: AsyncMock,
    mock_settings,
) -> None:
    """SQS send_message throws → resume_method='db_only', no exception raised."""
    package_dict = _sample_package_dict()
    mock_postgres.fetchrow.return_value = {
        "query_id": "VQ-2026-0099",
        "correlation_id": "corr-99",
        "package_data": orjson.dumps(package_dict).decode("utf-8"),
        "status": "PENDING",
    }
    broken_sqs = AsyncMock()
    broken_sqs.send_message.side_effect = RuntimeError("SQS is down")

    service = TriageService(
        postgres=mock_postgres,
        sqs=broken_sqs,
        eventbridge=mock_eventbridge,
        settings=mock_settings,
    )

    result = await service.submit_decision("VQ-2026-0099", _make_decision())

    assert result["resume_method"] == "db_only"
    assert result["status"] == "REVIEWED"
    # Package + decision rows still persisted despite SQS failure
    assert mock_postgres.execute.await_count == 3


# ---------------------------------------------------------------
# _apply_corrections
# ---------------------------------------------------------------


def test_apply_corrections_defaults_confidence_to_one(
    triage_service: TriageService,
) -> None:
    """With no override, human validation bumps confidence to 1.0."""
    original = _sample_analysis_result()
    decision = _make_decision(confidence_override=None)

    corrected = triage_service._apply_corrections(original, decision)

    assert corrected["confidence_score"] == 1.0
    assert corrected["human_validated"] is True
    assert corrected["reviewer_id"] == decision.reviewer_id
    assert corrected["intent_classification"] == "invoice_inquiry"


def test_apply_corrections_honors_override(
    triage_service: TriageService,
) -> None:
    """Reviewer-specified confidence_override is used verbatim."""
    original = _sample_analysis_result()
    decision = _make_decision(confidence_override=0.92)

    corrected = triage_service._apply_corrections(original, decision)

    assert corrected["confidence_score"] == 0.92
    assert corrected["human_validated"] is True


def test_apply_corrections_never_mutates_original(
    triage_service: TriageService,
) -> None:
    """Immutability: original dict must be untouched after correction."""
    original = _sample_analysis_result()
    snapshot = dict(original)
    decision = _make_decision(confidence_override=0.75)

    triage_service._apply_corrections(original, decision)

    assert original == snapshot
    assert "human_validated" not in original
    assert "reviewer_id" not in original
