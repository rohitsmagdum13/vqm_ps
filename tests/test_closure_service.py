"""Tests for the Phase 6 ClosureService.

Covers:
- register_resolution_sent: INSERT ON CONFLICT with business-day deadline
- detect_confirmation: keyword hit closes, no hit skips, already-closed skips
- handle_reopen: inside-window reopens, outside-window links new case
- close_case: DB writes critical; ServiceNow / EventBridge / episodic memory
  non-critical (failure in any one does NOT raise)
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from config.settings import Settings
from services.closure import ClosureService
from utils.helpers import DateHelper, TimeHelper


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def phase6_settings() -> Settings:
    """Minimal Settings for closure tests."""
    return Settings(
        app_env="test",
        aws_region="us-east-1",
        graph_api_tenant_id="t",
        graph_api_client_id="c",
        graph_api_client_secret="s",
        graph_api_mailbox="m@co.com",
        salesforce_instance_url="https://sf.test",
        salesforce_username="u",
        salesforce_password="p",
        salesforce_security_token="tk",
        servicenow_instance_url="https://snow.test",
        servicenow_username="u",
        servicenow_password="p",
        postgres_host="localhost",
        postgres_port=5432,
        postgres_db="vqms_test",
        postgres_user="u",
        postgres_password="p",
        sqs_query_intake_queue_url="https://sqs.test/q",
    )


@pytest.fixture
def mock_servicenow() -> AsyncMock:
    sn = AsyncMock()
    sn.update_ticket_status.return_value = None
    return sn


@pytest.fixture
def mock_eventbridge_async() -> AsyncMock:
    eb = AsyncMock()
    eb.publish_event.return_value = None
    return eb


@pytest.fixture
def mock_sqs_conn() -> AsyncMock:
    sqs = AsyncMock()
    sqs.send_message.return_value = None
    return sqs


@pytest.fixture
def mock_episodic_memory_writer() -> AsyncMock:
    writer = AsyncMock()
    writer.save_closure.return_value = "MEM-xyz"
    return writer


@pytest.fixture
def closure_service(
    mock_postgres: AsyncMock,
    mock_servicenow: AsyncMock,
    mock_eventbridge_async: AsyncMock,
    mock_sqs_conn: AsyncMock,
    mock_episodic_memory_writer: AsyncMock,
    phase6_settings: Settings,
) -> ClosureService:
    return ClosureService(
        postgres=mock_postgres,
        servicenow=mock_servicenow,
        eventbridge=mock_eventbridge_async,
        sqs=mock_sqs_conn,
        episodic_memory_writer=mock_episodic_memory_writer,
        settings=phase6_settings,
    )


# ---------------------------------------------------------------------------
# register_resolution_sent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_resolution_sent_inserts_with_business_day_deadline(
    closure_service: ClosureService,
    mock_postgres: AsyncMock,
    phase6_settings: Settings,
) -> None:
    """Inserts closure_tracking with deadline = now + N business days."""
    ok = await closure_service.register_resolution_sent(
        query_id="VQ-2026-0001", correlation_id="corr-1"
    )

    assert ok is True
    assert mock_postgres.execute.await_count == 1
    call_args = mock_postgres.execute.await_args.args
    sql = call_args[0]
    assert "INSERT INTO workflow.closure_tracking" in sql
    assert "ON CONFLICT (query_id) DO NOTHING" in sql
    # Positional args: sql, query_id, correlation_id, resolution_sent_at,
    #                  auto_close_deadline, created_at
    assert call_args[1] == "VQ-2026-0001"
    assert call_args[2] == "corr-1"
    resolution_sent_at = call_args[3]
    deadline = call_args[4]
    expected_deadline = DateHelper.add_business_days(
        resolution_sent_at, phase6_settings.auto_close_business_days
    )
    assert deadline == expected_deadline


@pytest.mark.asyncio
async def test_register_resolution_sent_empty_query_id_returns_false(
    closure_service: ClosureService,
    mock_postgres: AsyncMock,
) -> None:
    """Empty query_id short-circuits — no DB write."""
    ok = await closure_service.register_resolution_sent(
        query_id="", correlation_id="corr-1"
    )

    assert ok is False
    mock_postgres.execute.assert_not_called()


@pytest.mark.asyncio
async def test_register_resolution_sent_db_failure_returns_false(
    closure_service: ClosureService,
    mock_postgres: AsyncMock,
) -> None:
    """DB exception is swallowed — non-critical path returns False."""
    mock_postgres.execute.side_effect = RuntimeError("db down")

    ok = await closure_service.register_resolution_sent(
        query_id="VQ-2026-0001", correlation_id="corr-1"
    )

    assert ok is False


# ---------------------------------------------------------------------------
# detect_confirmation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_confirmation_missing_conversation_id_returns_false(
    closure_service: ClosureService,
    mock_postgres: AsyncMock,
) -> None:
    ok = await closure_service.detect_confirmation(
        conversation_id=None, body_text="Thanks!", correlation_id="corr-1"
    )
    assert ok is False
    mock_postgres.fetchrow.assert_not_called()


@pytest.mark.asyncio
async def test_detect_confirmation_no_prior_query_returns_false(
    closure_service: ClosureService,
    mock_postgres: AsyncMock,
) -> None:
    """No case_execution row for this conversation → skip."""
    mock_postgres.fetchrow.return_value = None

    ok = await closure_service.detect_confirmation(
        conversation_id="conv-1",
        body_text="Thanks!",
        correlation_id="corr-1",
    )

    assert ok is False


@pytest.mark.asyncio
async def test_detect_confirmation_already_closed_returns_false(
    closure_service: ClosureService,
    mock_postgres: AsyncMock,
) -> None:
    """Prior case already closed — no re-close."""
    mock_postgres.fetchrow.side_effect = [
        {"query_id": "VQ-PRIOR"},
        {"closed_at": TimeHelper.ist_now(), "closed_reason": "AUTO_CLOSED"},
    ]

    ok = await closure_service.detect_confirmation(
        conversation_id="conv-1",
        body_text="Thanks!",
        correlation_id="corr-1",
    )

    assert ok is False


@pytest.mark.asyncio
async def test_detect_confirmation_no_keyword_match_returns_false(
    closure_service: ClosureService,
    mock_postgres: AsyncMock,
) -> None:
    """Body has none of the confirmation keywords → skip."""
    mock_postgres.fetchrow.side_effect = [
        {"query_id": "VQ-PRIOR"},
        {"closed_at": None, "closed_reason": None},
    ]

    ok = await closure_service.detect_confirmation(
        conversation_id="conv-1",
        body_text="I still have an issue with this",
        correlation_id="corr-1",
    )

    assert ok is False


@pytest.mark.asyncio
async def test_detect_confirmation_keyword_hit_closes_case(
    closure_service: ClosureService,
    mock_postgres: AsyncMock,
    mock_servicenow: AsyncMock,
    mock_eventbridge_async: AsyncMock,
    mock_episodic_memory_writer: AsyncMock,
) -> None:
    """Keyword match drives close_case(VENDOR_CONFIRMED)."""
    mock_postgres.fetchrow.side_effect = [
        {"query_id": "VQ-PRIOR"},  # _find_prior_query_by_conversation
        {"closed_at": None, "closed_reason": None},  # _fetch_closure_tracking
        {"ticket_id": "INC-123"},  # _close_servicenow_ticket
    ]

    ok = await closure_service.detect_confirmation(
        conversation_id="conv-1",
        body_text="Thank you, that worked!",
        correlation_id="corr-1",
    )

    assert ok is True
    # close_case ran: 2 critical UPDATEs on case_execution + closure_tracking
    update_calls = [c.args[0] for c in mock_postgres.execute.await_args_list]
    assert any("UPDATE workflow.case_execution" in q for q in update_calls)
    assert any(
        "UPDATE workflow.closure_tracking" in q
        and "vendor_confirmation_detected_at" in q
        for q in update_calls
    )
    mock_servicenow.update_ticket_status.assert_awaited_once()
    mock_eventbridge_async.publish_event.assert_awaited_once()
    assert (
        mock_eventbridge_async.publish_event.await_args.args[0]
        == "TicketClosed"
    )
    mock_episodic_memory_writer.save_closure.assert_awaited_once()


# ---------------------------------------------------------------------------
# handle_reopen
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_reopen_missing_args_skips(
    closure_service: ClosureService,
    mock_postgres: AsyncMock,
) -> None:
    result = await closure_service.handle_reopen(
        conversation_id=None,
        new_query_id="VQ-NEW",
        correlation_id="corr-1",
    )
    assert result == "SKIPPED"
    mock_postgres.fetchrow.assert_not_called()


@pytest.mark.asyncio
async def test_handle_reopen_no_prior_case_skips(
    closure_service: ClosureService,
    mock_postgres: AsyncMock,
) -> None:
    mock_postgres.fetchrow.return_value = None

    result = await closure_service.handle_reopen(
        conversation_id="conv-1",
        new_query_id="VQ-NEW",
        correlation_id="corr-1",
    )

    assert result == "SKIPPED"


@pytest.mark.asyncio
async def test_handle_reopen_prior_not_closed_skips(
    closure_service: ClosureService,
    mock_postgres: AsyncMock,
) -> None:
    """closed_at is NULL — nothing to reopen."""
    mock_postgres.fetchrow.side_effect = [
        {"query_id": "VQ-PRIOR"},
        {"closed_at": None, "closed_reason": None},
    ]

    result = await closure_service.handle_reopen(
        conversation_id="conv-1",
        new_query_id="VQ-NEW",
        correlation_id="corr-1",
    )

    assert result == "SKIPPED"


@pytest.mark.asyncio
async def test_handle_reopen_inside_window_reopens_same_case(
    closure_service: ClosureService,
    mock_postgres: AsyncMock,
    mock_eventbridge_async: AsyncMock,
    mock_sqs_conn: AsyncMock,
) -> None:
    """Closed 2 days ago + 7-day window → reopen."""
    closed_at = TimeHelper.ist_now() - timedelta(days=2)
    mock_postgres.fetchrow.side_effect = [
        {"query_id": "VQ-PRIOR"},
        {"closed_at": closed_at, "closed_reason": "VENDOR_CONFIRMED"},
    ]

    result = await closure_service.handle_reopen(
        conversation_id="conv-1",
        new_query_id="VQ-NEW",
        correlation_id="corr-1",
    )

    assert result == "REOPENED_SAME_CASE"
    # case_execution flipped to AWAITING_RESOLUTION
    update_sqls = [c.args[0] for c in mock_postgres.execute.await_args_list]
    assert any(
        "UPDATE workflow.case_execution" in q
        and "AWAITING_RESOLUTION" in q
        for q in update_sqls
    )
    # closure_tracking marked REOPENED
    assert any(
        "UPDATE workflow.closure_tracking" in q
        and "REOPENED" in q
        for q in update_sqls
    )
    mock_eventbridge_async.publish_event.assert_awaited_once()
    assert (
        mock_eventbridge_async.publish_event.await_args.args[0]
        == "TicketReopened"
    )
    mock_sqs_conn.send_message.assert_awaited_once()
    sent_msg = mock_sqs_conn.send_message.await_args.args[1]
    assert sent_msg["resume_context"]["is_reopen"] is True


@pytest.mark.asyncio
async def test_handle_reopen_outside_window_links_new_case(
    closure_service: ClosureService,
    mock_postgres: AsyncMock,
    mock_eventbridge_async: AsyncMock,
    mock_sqs_conn: AsyncMock,
) -> None:
    """Closed 30 days ago, 7-day window → link new case, don't reopen."""
    closed_at = TimeHelper.ist_now() - timedelta(days=30)
    mock_postgres.fetchrow.side_effect = [
        {"query_id": "VQ-PRIOR"},
        {"closed_at": closed_at, "closed_reason": "VENDOR_CONFIRMED"},
    ]

    result = await closure_service.handle_reopen(
        conversation_id="conv-1",
        new_query_id="VQ-NEW",
        correlation_id="corr-1",
    )

    assert result == "LINKED_NEW_CASE"
    # Exactly one UPDATE and it's on the NEW query_id setting linked_query_id
    link_calls = [
        c
        for c in mock_postgres.execute.await_args_list
        if "linked_query_id" in c.args[0]
    ]
    assert len(link_calls) == 1
    # Positional: sql, prior_query_id, now, new_query_id
    assert link_calls[0].args[1] == "VQ-PRIOR"
    assert link_calls[0].args[3] == "VQ-NEW"
    mock_eventbridge_async.publish_event.assert_not_called()
    mock_sqs_conn.send_message.assert_not_called()


# ---------------------------------------------------------------------------
# close_case
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_case_vendor_confirmed_writes_confirmation_timestamp(
    closure_service: ClosureService,
    mock_postgres: AsyncMock,
) -> None:
    """VENDOR_CONFIRMED path sets vendor_confirmation_detected_at."""
    mock_postgres.fetchrow.return_value = {"ticket_id": "INC-1"}

    await closure_service.close_case(
        query_id="VQ-2026-0001",
        reason="VENDOR_CONFIRMED",
        correlation_id="corr-1",
    )

    tracking_updates = [
        c.args[0]
        for c in mock_postgres.execute.await_args_list
        if "UPDATE workflow.closure_tracking" in c.args[0]
    ]
    assert len(tracking_updates) == 1
    assert "vendor_confirmation_detected_at" in tracking_updates[0]


@pytest.mark.asyncio
async def test_close_case_auto_closed_omits_confirmation_timestamp(
    closure_service: ClosureService,
    mock_postgres: AsyncMock,
) -> None:
    """AUTO_CLOSED path does NOT touch vendor_confirmation_detected_at."""
    mock_postgres.fetchrow.return_value = {"ticket_id": "INC-1"}

    await closure_service.close_case(
        query_id="VQ-2026-0001",
        reason="AUTO_CLOSED",
        correlation_id="corr-1",
    )

    tracking_updates = [
        c.args[0]
        for c in mock_postgres.execute.await_args_list
        if "UPDATE workflow.closure_tracking" in c.args[0]
    ]
    assert len(tracking_updates) == 1
    assert "vendor_confirmation_detected_at" not in tracking_updates[0]


@pytest.mark.asyncio
async def test_close_case_continues_on_eventbridge_failure(
    closure_service: ClosureService,
    mock_postgres: AsyncMock,
    mock_eventbridge_async: AsyncMock,
    mock_episodic_memory_writer: AsyncMock,
) -> None:
    """EventBridge outage: DB closure still succeeds, memory still written."""
    mock_postgres.fetchrow.return_value = {"ticket_id": "INC-1"}
    mock_eventbridge_async.publish_event.side_effect = RuntimeError("bus down")

    # Must not raise
    await closure_service.close_case(
        query_id="VQ-2026-0001",
        reason="VENDOR_CONFIRMED",
        correlation_id="corr-1",
    )

    # DB writes still happened; episodic memory still called
    assert mock_postgres.execute.await_count >= 2
    mock_episodic_memory_writer.save_closure.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_case_continues_on_servicenow_failure(
    closure_service: ClosureService,
    mock_postgres: AsyncMock,
    mock_servicenow: AsyncMock,
    mock_eventbridge_async: AsyncMock,
) -> None:
    """ServiceNow down: close still publishes TicketClosed."""
    mock_postgres.fetchrow.return_value = {"ticket_id": "INC-1"}
    mock_servicenow.update_ticket_status.side_effect = RuntimeError(
        "snow down"
    )

    await closure_service.close_case(
        query_id="VQ-2026-0001",
        reason="AUTO_CLOSED",
        correlation_id="corr-1",
    )

    mock_eventbridge_async.publish_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_case_continues_on_episodic_memory_failure(
    closure_service: ClosureService,
    mock_postgres: AsyncMock,
    mock_episodic_memory_writer: AsyncMock,
    mock_eventbridge_async: AsyncMock,
) -> None:
    """Episodic-memory failure does not prevent the DB close."""
    mock_postgres.fetchrow.return_value = {"ticket_id": "INC-1"}
    mock_episodic_memory_writer.save_closure.side_effect = RuntimeError(
        "mem down"
    )

    await closure_service.close_case(
        query_id="VQ-2026-0001",
        reason="VENDOR_CONFIRMED",
        correlation_id="corr-1",
    )

    mock_eventbridge_async.publish_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_case_skips_servicenow_when_no_ticket_linked(
    closure_service: ClosureService,
    mock_postgres: AsyncMock,
    mock_servicenow: AsyncMock,
) -> None:
    """No ticket_link row → ServiceNow update is skipped silently."""
    mock_postgres.fetchrow.return_value = None

    await closure_service.close_case(
        query_id="VQ-2026-0001",
        reason="AUTO_CLOSED",
        correlation_id="corr-1",
    )

    mock_servicenow.update_ticket_status.assert_not_called()
