"""Tests for the Phase 6 AutoCloseScheduler.

Covers:
- tick: closes each row whose auto_close_deadline has passed
- tick: returns 0 and does not raise when no rows match
- tick: per-row ClosureService failures are caught, scanning continues
- tick: DB fetch failure returns 0 without raising
- stop: flips the running flag to False
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from config.settings import Settings
from services.auto_close_scheduler import AutoCloseScheduler


@pytest.fixture
def phase6_settings() -> Settings:
    """Minimal Settings for auto-close tests."""
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
    )


@pytest.fixture
def mock_closure_service() -> AsyncMock:
    svc = AsyncMock()
    svc.close_case.return_value = None
    return svc


@pytest.fixture
def scheduler(
    mock_postgres: AsyncMock,
    mock_closure_service: AsyncMock,
    phase6_settings: Settings,
) -> AutoCloseScheduler:
    return AutoCloseScheduler(
        postgres=mock_postgres,
        closure_service=mock_closure_service,
        settings=phase6_settings,
    )


@pytest.mark.asyncio
async def test_tick_closes_expired_rows(
    scheduler: AutoCloseScheduler,
    mock_postgres: AsyncMock,
    mock_closure_service: AsyncMock,
) -> None:
    """Two expired rows → two close_case(AUTO_CLOSED) calls."""
    mock_postgres.fetch.return_value = [
        {"query_id": "VQ-2026-0001", "correlation_id": "corr-1"},
        {"query_id": "VQ-2026-0002", "correlation_id": "corr-2"},
    ]

    closed = await scheduler.tick()

    assert closed == 2
    assert mock_closure_service.close_case.await_count == 2
    # Each call uses AUTO_CLOSED and the row's correlation_id
    for call in mock_closure_service.close_case.await_args_list:
        assert call.kwargs["reason"] == "AUTO_CLOSED"
        assert call.kwargs["correlation_id"] in ("corr-1", "corr-2")


@pytest.mark.asyncio
async def test_tick_returns_zero_when_no_rows(
    scheduler: AutoCloseScheduler,
    mock_postgres: AsyncMock,
    mock_closure_service: AsyncMock,
) -> None:
    """No expired rows → no close_case calls, count=0."""
    mock_postgres.fetch.return_value = []

    closed = await scheduler.tick()

    assert closed == 0
    mock_closure_service.close_case.assert_not_called()


@pytest.mark.asyncio
async def test_tick_continues_on_per_row_close_failure(
    scheduler: AutoCloseScheduler,
    mock_postgres: AsyncMock,
    mock_closure_service: AsyncMock,
) -> None:
    """A close_case failure on row 1 does not stop row 2 from processing."""
    mock_postgres.fetch.return_value = [
        {"query_id": "VQ-BAD", "correlation_id": "corr-1"},
        {"query_id": "VQ-GOOD", "correlation_id": "corr-2"},
    ]
    mock_closure_service.close_case.side_effect = [
        RuntimeError("close failed"),
        None,
    ]

    closed = await scheduler.tick()

    # Only the good row counts toward the closed tally
    assert closed == 1
    assert mock_closure_service.close_case.await_count == 2


@pytest.mark.asyncio
async def test_tick_skips_rows_without_query_id(
    scheduler: AutoCloseScheduler,
    mock_postgres: AsyncMock,
    mock_closure_service: AsyncMock,
) -> None:
    """A row with no query_id is skipped silently."""
    mock_postgres.fetch.return_value = [
        {"query_id": None, "correlation_id": "corr-1"},
        {"query_id": "VQ-OK", "correlation_id": "corr-2"},
    ]

    closed = await scheduler.tick()

    assert closed == 1
    mock_closure_service.close_case.assert_awaited_once()
    assert (
        mock_closure_service.close_case.await_args.kwargs["query_id"]
        == "VQ-OK"
    )


@pytest.mark.asyncio
async def test_tick_handles_fetch_failure(
    scheduler: AutoCloseScheduler,
    mock_postgres: AsyncMock,
    mock_closure_service: AsyncMock,
) -> None:
    """DB fetch raises → tick returns 0 without raising."""
    mock_postgres.fetch.side_effect = RuntimeError("db down")

    closed = await scheduler.tick()

    assert closed == 0
    mock_closure_service.close_case.assert_not_called()


def test_stop_sets_running_false(scheduler: AutoCloseScheduler) -> None:
    scheduler._running = True  # type: ignore[attr-defined]
    scheduler.stop()
    assert scheduler._running is False  # type: ignore[attr-defined]
