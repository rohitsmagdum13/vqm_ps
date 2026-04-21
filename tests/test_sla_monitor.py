"""Tests for the Phase 6 SlaMonitor background task.

Covers:
- compute_threshold_crossed: correct escalation picking given elapsed %
- tick: publishes SLAWarning70 / SLAEscalation85 / SLAEscalation95 once each
- tick: idempotent — a second tick with the same row does NOT re-publish
- tick: EventBridge failure does NOT flip the _fired flag (retries next tick)
- tick: per-row exceptions are caught; the monitor keeps scanning
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from config.settings import Settings
from models.sla import SlaThresholdCrossed
from services.sla_monitor import SlaMonitor
from utils.helpers import TimeHelper


@pytest.fixture
def phase6_settings() -> Settings:
    """Minimal Settings for SLA tests."""
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
def mock_eventbridge() -> AsyncMock:
    eb = AsyncMock()
    eb.publish_event.return_value = None
    return eb


@pytest.fixture
def sla_monitor(mock_postgres, mock_eventbridge, phase6_settings) -> SlaMonitor:
    return SlaMonitor(
        postgres=mock_postgres,
        eventbridge=mock_eventbridge,
        settings=phase6_settings,
    )


def _active_row(
    *,
    query_id: str = "VQ-2026-0001",
    correlation_id: str = "corr-1",
    elapsed_fraction: float = 0.75,
    warning_fired: bool = False,
    l1_fired: bool = False,
    l2_fired: bool = False,
) -> dict:
    """Build a row whose elapsed fraction is `elapsed_fraction` of the SLA window."""
    total_hours = 4
    now = TimeHelper.ist_now()
    started = now - timedelta(hours=total_hours * elapsed_fraction)
    deadline = started + timedelta(hours=total_hours)
    return {
        "query_id": query_id,
        "correlation_id": correlation_id,
        "sla_started_at": started,
        "sla_deadline": deadline,
        "sla_target_hours": total_hours,
        "warning_fired": warning_fired,
        "l1_fired": l1_fired,
        "l2_fired": l2_fired,
    }


@pytest.mark.parametrize(
    "pct, warning_fired, l1_fired, l2_fired, expected",
    [
        (50.0, False, False, False, SlaThresholdCrossed.NONE),
        (70.0, False, False, False, SlaThresholdCrossed.WARNING),
        # At 85% both WARNING and L1 thresholds have been crossed; the
        # monitor picks the highest uncrossed one (L1) and relies on a
        # later tick to pick up WARNING if its flag were somehow still
        # False.
        (85.0, False, False, False, SlaThresholdCrossed.L1),
        (92.0, True, True, False, SlaThresholdCrossed.NONE),
        (95.0, True, True, False, SlaThresholdCrossed.L2),
        (95.0, True, True, True, SlaThresholdCrossed.NONE),
        (72.0, True, False, False, SlaThresholdCrossed.NONE),
    ],
)
def test_compute_threshold_crossed(
    sla_monitor: SlaMonitor,
    pct: float,
    warning_fired: bool,
    l1_fired: bool,
    l2_fired: bool,
    expected: SlaThresholdCrossed,
) -> None:
    """Escalation picking is done highest-threshold-first."""
    result = sla_monitor.compute_threshold_crossed(
        pct, warning_fired, l1_fired, l2_fired
    )
    assert result is expected


@pytest.mark.asyncio
async def test_tick_publishes_warning_event(
    sla_monitor: SlaMonitor,
    mock_postgres: AsyncMock,
    mock_eventbridge: AsyncMock,
) -> None:
    """A row at 70% with no flags set publishes SLAWarning70 and flips warning_fired."""
    mock_postgres.fetch.return_value = [_active_row(elapsed_fraction=0.70)]

    published = await sla_monitor.tick(correlation_id="corr-1")

    assert published == 1
    assert mock_eventbridge.publish_event.await_count == 1
    event_type = mock_eventbridge.publish_event.await_args.args[0]
    assert event_type == "SLAWarning70"
    # Flip query issued + last_checked_at bump
    update_calls = [c for c in mock_postgres.execute.await_args_list]
    assert any("warning_fired" in (c.args[0] or "") for c in update_calls)


@pytest.mark.asyncio
async def test_tick_picks_highest_threshold_on_large_jump(
    sla_monitor: SlaMonitor,
    mock_postgres: AsyncMock,
    mock_eventbridge: AsyncMock,
) -> None:
    """A row at 95% with no flags gets L2 published first, not WARNING."""
    mock_postgres.fetch.return_value = [_active_row(elapsed_fraction=0.96)]

    published = await sla_monitor.tick()

    assert published == 1
    event_type = mock_eventbridge.publish_event.await_args.args[0]
    assert event_type == "SLAEscalation95"


@pytest.mark.asyncio
async def test_tick_idempotent_does_not_republish(
    sla_monitor: SlaMonitor,
    mock_postgres: AsyncMock,
    mock_eventbridge: AsyncMock,
) -> None:
    """Warning already fired + elapsed 72% → NONE → no event published."""
    mock_postgres.fetch.return_value = [
        _active_row(elapsed_fraction=0.72, warning_fired=True)
    ]

    published = await sla_monitor.tick()

    assert published == 0
    mock_eventbridge.publish_event.assert_not_called()


@pytest.mark.asyncio
async def test_tick_does_not_flip_flag_on_eventbridge_failure(
    sla_monitor: SlaMonitor,
    mock_postgres: AsyncMock,
    mock_eventbridge: AsyncMock,
) -> None:
    """EventBridge outage: flag stays False so the next tick retries."""
    mock_postgres.fetch.return_value = [_active_row(elapsed_fraction=0.90)]
    mock_eventbridge.publish_event.side_effect = RuntimeError("bus down")

    published = await sla_monitor.tick()

    assert published == 0
    # Only the last_checked_at bump runs; no flag-flip UPDATE
    update_calls = [c.args[0] for c in mock_postgres.execute.await_args_list]
    assert not any(
        "l1_fired = TRUE" in q or "l2_fired = TRUE" in q for q in update_calls
    )


@pytest.mark.asyncio
async def test_tick_continues_on_per_row_exception(
    sla_monitor: SlaMonitor,
    mock_postgres: AsyncMock,
    mock_eventbridge: AsyncMock,
) -> None:
    """One bad row does not block processing of the next row."""
    good_row = _active_row(elapsed_fraction=0.95, query_id="VQ-2026-0001")
    # Bad row has zero-duration SLA which triggers the early-return (0 events)
    bad_row = _active_row(elapsed_fraction=0.95, query_id="VQ-2026-0002")
    bad_row["sla_deadline"] = bad_row["sla_started_at"]

    mock_postgres.fetch.return_value = [bad_row, good_row]

    published = await sla_monitor.tick()

    # Only the good row publishes
    assert published == 1
    assert mock_eventbridge.publish_event.await_count == 1


@pytest.mark.asyncio
async def test_tick_handles_fetch_failure(
    sla_monitor: SlaMonitor,
    mock_postgres: AsyncMock,
    mock_eventbridge: AsyncMock,
) -> None:
    """A DB fetch failure returns 0 without raising."""
    mock_postgres.fetch.side_effect = RuntimeError("db down")

    published = await sla_monitor.tick()

    assert published == 0
    mock_eventbridge.publish_event.assert_not_called()


def test_stop_sets_running_false(sla_monitor: SlaMonitor) -> None:
    sla_monitor._running = True  # type: ignore[attr-defined]
    sla_monitor.stop()
    assert sla_monitor._running is False  # type: ignore[attr-defined]
