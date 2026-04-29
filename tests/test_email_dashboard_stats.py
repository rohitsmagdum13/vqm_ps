"""Tests for EmailDashboardService.get_stats — focused on the
priority breakdown and the new 10-day daily breakdown.

Covers the bug fix (Critical was being collapsed into High in
PRIORITY_MAP) and the new past_10_days_new / past_10_days_resolved
fields. PostgresConnector is stubbed — no DB access.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from models.email_dashboard import EmailStatsResponse
from services.email_dashboard.mappings import PRIORITY_MAP, DashboardMapper
from services.email_dashboard.service import EmailDashboardService


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _service_with_rows(
    *,
    stats_row: dict | None,
    priority_rows: list[dict],
    new_daily_rows: list[dict],
    resolved_daily_rows: list[dict],
) -> EmailDashboardService:
    """Build a service whose Postgres connector returns the supplied rows.
    `fetchrow` always serves the stats_row; `fetch` is dispatched by call
    order: priority first, then new-daily, then resolved-daily — matching
    the order in service.get_stats().
    """
    postgres = MagicMock()
    postgres.fetchrow = AsyncMock(return_value=stats_row)
    postgres.fetch = AsyncMock(
        side_effect=[priority_rows, new_daily_rows, resolved_daily_rows]
    )

    s3 = MagicMock()
    settings = MagicMock()
    settings.s3_bucket_data_store = "test-bucket"

    return EmailDashboardService(postgres=postgres, s3=s3, settings=settings)


# ---------------------------------------------------------------------
# 1. Priority mapping bug fix
# ---------------------------------------------------------------------


class TestPriorityMapping:
    """Verify the PRIORITY_MAP fix routes 'critical' to its own bucket."""

    def test_critical_maps_to_critical_not_high(self):
        # Was the bug — 'critical' used to map to 'High'.
        assert PRIORITY_MAP["critical"] == "Critical"

    def test_dashboard_mapper_returns_critical(self):
        assert DashboardMapper.map_priority("critical") == "Critical"
        assert DashboardMapper.map_priority("CRITICAL") == "Critical"

    def test_other_priorities_unchanged(self):
        assert DashboardMapper.map_priority("high") == "High"
        assert DashboardMapper.map_priority("medium") == "Medium"
        assert DashboardMapper.map_priority("low") == "Low"

    def test_null_priority_defaults_to_medium(self):
        assert DashboardMapper.map_priority(None) == "Medium"
        assert DashboardMapper.map_priority("") == "Medium"


# ---------------------------------------------------------------------
# 2. _empty_priority_breakdown — ensures Critical slot
# ---------------------------------------------------------------------


def test_empty_priority_breakdown_includes_critical():
    breakdown = EmailDashboardService._empty_priority_breakdown()
    assert breakdown == {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
    assert set(breakdown) == {"Critical", "High", "Medium", "Low"}


# ---------------------------------------------------------------------
# 3. _fill_daily_buckets — date projection, gap-filling, fixed length
# ---------------------------------------------------------------------


class TestFillDailyBuckets:
    """The helper that flattens per-day count rows into a length-10 array
    indexed oldest → newest. Critical for sparkline rendering."""

    def test_returns_length_10_when_rows_empty(self):
        result = EmailDashboardService._fill_daily_buckets([], date(2026, 4, 28))
        assert result == [0] * 10

    def test_today_bucket_lands_at_index_9(self):
        today = date(2026, 4, 28)
        rows = [{"day": today, "cnt": 7}]
        result = EmailDashboardService._fill_daily_buckets(rows, today)
        assert len(result) == 10
        assert result[-1] == 7
        assert result[:-1] == [0] * 9

    def test_oldest_bucket_lands_at_index_0(self):
        today = date(2026, 4, 28)
        oldest = today - timedelta(days=9)
        rows = [{"day": oldest, "cnt": 3}]
        result = EmailDashboardService._fill_daily_buckets(rows, today)
        assert result[0] == 3
        assert result[1:] == [0] * 9

    def test_gaps_become_zero(self):
        today = date(2026, 4, 28)
        # Days at offsets 9, 5, 0 from today; rest blank.
        # Index 0 = oldest (offset 9), index 9 = newest (offset 0).
        # offset 5 → index 9-5 = 4.
        rows = [
            {"day": today - timedelta(days=9), "cnt": 1},
            {"day": today - timedelta(days=5), "cnt": 2},
            {"day": today, "cnt": 3},
        ]
        result = EmailDashboardService._fill_daily_buckets(rows, today)
        assert result == [1, 0, 0, 0, 2, 0, 0, 0, 0, 3]

    def test_dates_outside_window_are_dropped(self):
        today = date(2026, 4, 28)
        rows = [
            {"day": today - timedelta(days=20), "cnt": 99},  # outside window
            {"day": today, "cnt": 5},
        ]
        result = EmailDashboardService._fill_daily_buckets(rows, today)
        assert sum(result) == 5
        assert result[-1] == 5

    def test_custom_window_size(self):
        today = date(2026, 4, 28)
        result = EmailDashboardService._fill_daily_buckets(
            [{"day": today, "cnt": 1}], today, window_days=5
        )
        assert len(result) == 5
        assert result == [0, 0, 0, 0, 1]


# ---------------------------------------------------------------------
# 4. get_stats — full integration with mocked Postgres
# ---------------------------------------------------------------------


class TestGetStats:
    """End-to-end shape check on the EmailStatsResponse, including the
    new fields and the Critical slot."""

    @pytest.mark.asyncio
    async def test_response_includes_critical_in_priority_breakdown(self):
        service = _service_with_rows(
            stats_row={
                "total": 4,
                "new_count": 2,
                "reopened_count": 0,
                "resolved_count": 1,
                "today_count": 1,
                "week_count": 4,
            },
            priority_rows=[
                {"priority": "critical", "cnt": 1},
                {"priority": "high", "cnt": 2},
                {"priority": "low", "cnt": 1},
            ],
            new_daily_rows=[],
            resolved_daily_rows=[],
        )
        result = await service.get_stats(correlation_id="test-1")

        assert isinstance(result, EmailStatsResponse)
        assert result.priority_breakdown["Critical"] == 1
        assert result.priority_breakdown["High"] == 2
        assert result.priority_breakdown["Medium"] == 0  # zero-filled
        assert result.priority_breakdown["Low"] == 1
        assert set(result.priority_breakdown) == {"Critical", "High", "Medium", "Low"}

    @pytest.mark.asyncio
    async def test_critical_no_longer_double_counts_into_high(self):
        # The bug: 1 critical + 1 high used to render as High=2, Critical=0.
        # After the fix it should be Critical=1, High=1.
        service = _service_with_rows(
            stats_row={
                "total": 2,
                "new_count": 2,
                "reopened_count": 0,
                "resolved_count": 0,
                "today_count": 0,
                "week_count": 2,
            },
            priority_rows=[
                {"priority": "critical", "cnt": 1},
                {"priority": "high", "cnt": 1},
            ],
            new_daily_rows=[],
            resolved_daily_rows=[],
        )
        result = await service.get_stats(correlation_id="test-2")

        assert result.priority_breakdown["Critical"] == 1
        assert result.priority_breakdown["High"] == 1

    @pytest.mark.asyncio
    async def test_response_includes_past_10_days_arrays(self):
        service = _service_with_rows(
            stats_row={
                "total": 0,
                "new_count": 0,
                "reopened_count": 0,
                "resolved_count": 0,
                "today_count": 0,
                "week_count": 0,
            },
            priority_rows=[],
            new_daily_rows=[],
            resolved_daily_rows=[],
        )
        result = await service.get_stats(correlation_id="test-3")

        assert hasattr(result, "past_10_days_new")
        assert hasattr(result, "past_10_days_resolved")
        assert len(result.past_10_days_new) == 10
        assert len(result.past_10_days_resolved) == 10
        assert result.past_10_days_new == [0] * 10
        assert result.past_10_days_resolved == [0] * 10

    @pytest.mark.asyncio
    async def test_past_10_days_arrays_reflect_daily_rows(self):
        # Construct rows for "today" using the same TimeHelper.ist_now()
        # the service uses, then assert the two arrays end with those counts.
        from utils.helpers import TimeHelper

        now = TimeHelper.ist_now()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0).date()
        yesterday = today - timedelta(days=1)

        service = _service_with_rows(
            stats_row={
                "total": 5,
                "new_count": 3,
                "reopened_count": 0,
                "resolved_count": 2,
                "today_count": 4,
                "week_count": 5,
            },
            priority_rows=[],
            new_daily_rows=[
                {"day": yesterday, "cnt": 1},
                {"day": today, "cnt": 2},
            ],
            resolved_daily_rows=[
                {"day": today, "cnt": 1},
            ],
        )
        result = await service.get_stats(correlation_id="test-4")

        # Today is the rightmost (newest) bucket.
        assert result.past_10_days_new[-1] == 2
        assert result.past_10_days_new[-2] == 1
        assert sum(result.past_10_days_new) == 3
        assert result.past_10_days_resolved[-1] == 1
        assert sum(result.past_10_days_resolved) == 1

    @pytest.mark.asyncio
    async def test_db_failure_returns_safe_zero_response_with_new_fields(self):
        # Simulate a Postgres failure. The service swallows it and returns
        # an all-zeros EmailStatsResponse — the response shape (including
        # the two new arrays) must still be present so the frontend doesn't
        # crash on missing fields.
        postgres = MagicMock()
        postgres.fetchrow = AsyncMock(side_effect=RuntimeError("db down"))
        postgres.fetch = AsyncMock(side_effect=RuntimeError("db down"))
        s3 = MagicMock()
        settings = MagicMock()
        settings.s3_bucket_data_store = "test-bucket"

        service = EmailDashboardService(postgres=postgres, s3=s3, settings=settings)
        result = await service.get_stats(correlation_id="test-5")

        assert result.total_emails == 0
        assert result.priority_breakdown == {
            "Critical": 0,
            "High": 0,
            "Medium": 0,
            "Low": 0,
        }
        assert result.past_10_days_new == [0] * 10
        assert result.past_10_days_resolved == [0] * 10

    @pytest.mark.asyncio
    async def test_no_stats_row_still_returns_full_shape(self):
        # When the SQL returns no stats row at all (empty table), the
        # service falls into the second return branch — must still
        # populate the new fields.
        service = _service_with_rows(
            stats_row=None,
            priority_rows=[],
            new_daily_rows=[],
            resolved_daily_rows=[],
        )
        result = await service.get_stats(correlation_id="test-6")

        assert result.total_emails == 0
        assert "Critical" in result.priority_breakdown
        assert len(result.past_10_days_new) == 10
        assert len(result.past_10_days_resolved) == 10


# ---------------------------------------------------------------------
# 5. EmailStatsResponse model — required-field contract
# ---------------------------------------------------------------------


def test_response_model_requires_new_fields():
    """The two new fields are required (no defaults). This catches a
    regression where a future refactor accidentally re-introduces a
    fallback that omits them."""
    with pytest.raises(Exception):
        # Missing past_10_days_new + past_10_days_resolved — should raise.
        EmailStatsResponse(
            total_emails=0,
            new_count=0,
            reopened_count=0,
            resolved_count=0,
            priority_breakdown={"Critical": 0, "High": 0, "Medium": 0, "Low": 0},
            today_count=0,
            this_week_count=0,
        )


def test_response_model_serialises_new_fields():
    """End-to-end JSON shape check — the two arrays must round-trip
    through model_dump (what the FastAPI route returns)."""
    response = EmailStatsResponse(
        total_emails=7,
        new_count=7,
        reopened_count=0,
        resolved_count=0,
        priority_breakdown={"Critical": 0, "High": 0, "Medium": 0, "Low": 0},
        today_count=7,
        this_week_count=7,
        past_10_days_new=[0, 0, 0, 0, 0, 0, 0, 0, 1, 2],
        past_10_days_resolved=[0, 0, 0, 0, 0, 0, 0, 0, 1, 1],
    )
    dump = response.model_dump(mode="json")

    assert dump["past_10_days_new"] == [0, 0, 0, 0, 0, 0, 0, 0, 1, 2]
    assert dump["past_10_days_resolved"] == [0, 0, 0, 0, 0, 0, 0, 0, 1, 1]
    assert dump["priority_breakdown"]["Critical"] == 0


# unused imports kept off the hot path
_ = datetime
