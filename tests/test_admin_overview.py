"""Tests for AdminOverviewService — the bundle of aggregations behind
GET /admin/overview.

Postgres is stubbed so no DB access. Each section is tested in isolation
plus one end-to-end check that the bundled response has every field
populated and the right shape (length-30 sparklines, length-24 hourly,
five confidence bands).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from models.admin_overview import (
    AdminOverviewResponse,
    HeadlineKPIs,
    PathMix,
)
from services.admin_overview.service import (
    _CONFIDENCE_BANDS,
    _HOURLY_WINDOW_HOURS,
    _KPI_WINDOW_DAYS,
    AdminOverviewService,
)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _service(
    *,
    fetchrow_side_effect=None,
    fetch_side_effect=None,
) -> AdminOverviewService:
    postgres = MagicMock()
    postgres.fetchrow = AsyncMock(side_effect=fetchrow_side_effect)
    postgres.fetch = AsyncMock(side_effect=fetch_side_effect)
    return AdminOverviewService(postgres=postgres)


def _empty_run_fetchrow():
    """Side-effect generator for fetchrow that returns empty rows."""
    return [
        {"total": 0, "resolved": 0, "avg_response_minutes": 0},  # cur kpi
        {"total": 0, "resolved": 0, "avg_response_minutes": 0},  # prev kpi
        {"cur": 0, "prev": 0},  # breaches
    ]


def _empty_run_fetch():
    """Side-effect generator for fetch that returns empty lists for every
    aggregation called in get_overview."""
    return [
        [],  # daily kpi rows
        [],  # breaches daily
        [],  # path_mix
        [],  # volume_by_path
        [],  # hourly ingested
        [],  # hourly resolved
        [],  # confidence histogram
        [],  # sla_by_team
        [],  # top_intents
    ]


# ---------------------------------------------------------------------
# 1. _pct_delta — boundary cases
# ---------------------------------------------------------------------


class TestPctDelta:
    def test_growth(self):
        assert AdminOverviewService._pct_delta(120, 100) == 20.0

    def test_decline(self):
        assert AdminOverviewService._pct_delta(80, 100) == -20.0

    def test_zero_baseline_with_growth_returns_100(self):
        # By convention "any growth from zero" is +100%; otherwise the
        # frontend would have to special-case "infinite improvement".
        assert AdminOverviewService._pct_delta(5, 0) == 100.0

    def test_zero_baseline_zero_current_returns_zero(self):
        assert AdminOverviewService._pct_delta(0, 0) == 0.0

    def test_rounds_to_one_decimal(self):
        assert AdminOverviewService._pct_delta(101, 100) == 1.0
        assert AdminOverviewService._pct_delta(102.5, 100) == 2.5


# ---------------------------------------------------------------------
# 2. _day_index — date math correctness
# ---------------------------------------------------------------------


class TestDayIndex:
    def test_length_matches_window(self):
        days = AdminOverviewService._day_index(date(2026, 4, 28), 30)
        assert len(days) == 30

    def test_oldest_first_newest_last(self):
        end = date(2026, 4, 28)
        days = AdminOverviewService._day_index(end, 30)
        assert days[-1] == end
        assert days[0] == end - timedelta(days=29)


# ---------------------------------------------------------------------
# 3. Zero-default factories
# ---------------------------------------------------------------------


def test_zero_kpis_shape():
    k = AdminOverviewService._zero_kpis()
    assert isinstance(k, HeadlineKPIs)
    assert k.queries_received == 0
    assert k.resolution_rate_pct == 0.0


def test_zero_sparklines_lengths():
    s = AdminOverviewService._zero_sparklines()
    assert len(s.received_per_day) == _KPI_WINDOW_DAYS
    assert len(s.resolution_rate_per_day) == _KPI_WINDOW_DAYS
    assert len(s.response_minutes_per_day) == _KPI_WINDOW_DAYS
    assert len(s.breaches_per_day) == _KPI_WINDOW_DAYS


def test_zero_hourly_length():
    h = AdminOverviewService._zero_hourly()
    assert len(h) == _HOURLY_WINDOW_HOURS


def test_zero_volume_length():
    rows = AdminOverviewService._zero_volume(date(2026, 4, 28))
    assert len(rows) == _KPI_WINDOW_DAYS
    assert rows[0].A == 0
    assert rows[0].B == 0
    assert rows[0].C == 0


# ---------------------------------------------------------------------
# 4. _safe — failure isolation
# ---------------------------------------------------------------------


class TestSafe:
    @pytest.mark.asyncio
    async def test_returns_default_on_exception(self):
        service = _service()

        async def boom():
            raise RuntimeError("simulated db failure")

        result = await service._safe(
            "boom_section", "corr-1", boom, default="FALLBACK"
        )
        assert result == "FALLBACK"

    @pytest.mark.asyncio
    async def test_returns_value_on_success(self):
        service = _service()

        async def ok():
            return [1, 2, 3]

        result = await service._safe("ok_section", "corr-2", ok, default=[])
        assert result == [1, 2, 3]


# ---------------------------------------------------------------------
# 5. get_overview — end-to-end shape with empty DB
# ---------------------------------------------------------------------


class TestGetOverviewEmpty:
    """When the DB has zero rows, every section should return well-formed
    defaults (length-30 / length-24 arrays etc.)."""

    @pytest.mark.asyncio
    async def test_returns_full_shape_on_empty_db(self):
        service = _service(
            fetchrow_side_effect=_empty_run_fetchrow(),
            fetch_side_effect=_empty_run_fetch(),
        )
        result = await service.get_overview(correlation_id="test-empty")

        assert isinstance(result, AdminOverviewResponse)
        assert result.kpis.queries_received == 0
        assert result.kpis.queries_received_delta_pct == 0.0
        assert result.kpis.resolution_rate_pct == 0.0
        assert result.kpis.sla_breaches == 0

        assert len(result.kpi_sparklines.received_per_day) == _KPI_WINDOW_DAYS
        assert len(result.kpi_sparklines.resolution_rate_per_day) == _KPI_WINDOW_DAYS
        assert len(result.kpi_sparklines.response_minutes_per_day) == _KPI_WINDOW_DAYS
        assert len(result.kpi_sparklines.breaches_per_day) == _KPI_WINDOW_DAYS

        assert result.path_mix == PathMix(A=0, B=0, C=0)
        assert len(result.volume_by_path) == _KPI_WINDOW_DAYS
        assert len(result.hourly_throughput) == _HOURLY_WINDOW_HOURS
        assert len(result.confidence_histogram) == len(_CONFIDENCE_BANDS)
        assert result.sla_by_team == []
        assert result.top_intents == []

    @pytest.mark.asyncio
    async def test_response_serialises_to_dict(self):
        """Sanity check the FastAPI route can model_dump the response."""
        service = _service(
            fetchrow_side_effect=_empty_run_fetchrow(),
            fetch_side_effect=_empty_run_fetch(),
        )
        result = await service.get_overview(correlation_id="test-dump")
        dump = result.model_dump(mode="json")
        assert "kpis" in dump
        assert "kpi_sparklines" in dump
        assert "path_mix" in dump
        assert "volume_by_path" in dump
        assert "hourly_throughput" in dump
        assert "confidence_histogram" in dump
        assert "sla_by_team" in dump
        assert "top_intents" in dump


# ---------------------------------------------------------------------
# 6. get_overview — populated KPIs + delta
# ---------------------------------------------------------------------


class TestGetOverviewPopulated:
    """Verify the headline KPI math when both windows have data."""

    @pytest.mark.asyncio
    async def test_kpis_compute_deltas(self):
        # current 30d: 100 received, 80 resolved, 240min avg, 10 breaches
        # prior   30d:  80 received, 60 resolved, 300min avg,  5 breaches
        # received delta: (100-80)/80 = +25%
        # resolution rate delta: 80% vs 75% => (80-75)/75 = +6.67% rounded to 6.7
        # response minutes delta: (240-300)/300 = -20%
        # breaches delta: (10-5)/5 = +100%
        service = _service(
            fetchrow_side_effect=[
                {"total": 100, "resolved": 80, "avg_response_minutes": 240},
                {"total": 80, "resolved": 60, "avg_response_minutes": 300},
                {"cur": 10, "prev": 5},
            ],
            fetch_side_effect=_empty_run_fetch(),
        )
        result = await service.get_overview(correlation_id="test-kpi")

        assert result.kpis.queries_received == 100
        assert result.kpis.queries_received_delta_pct == 25.0
        assert result.kpis.resolution_rate_pct == 80.0
        assert result.kpis.resolution_rate_delta_pct == pytest.approx(6.7, abs=0.1)
        assert result.kpis.avg_response_minutes == 240
        assert result.kpis.avg_response_delta_pct == -20.0
        assert result.kpis.sla_breaches == 10
        assert result.kpis.sla_breaches_delta_pct == 100.0


# ---------------------------------------------------------------------
# 7. _path_mix isolated
# ---------------------------------------------------------------------


class TestPathMix:
    @pytest.mark.asyncio
    async def test_aggregates_three_paths(self):
        service = _service()
        service._postgres.fetch = AsyncMock(
            return_value=[
                {"processing_path": "A", "cnt": 5},
                {"processing_path": "B", "cnt": 3},
                {"processing_path": "C", "cnt": 1},
            ]
        )
        result = await service._path_mix(datetime(2026, 4, 1))
        assert result == PathMix(A=5, B=3, C=1)

    @pytest.mark.asyncio
    async def test_unknown_path_value_ignored(self):
        # Defensive: if a future migration introduces 'D' or NULL, we
        # silently ignore it rather than crash on a missing key.
        service = _service()
        service._postgres.fetch = AsyncMock(
            return_value=[
                {"processing_path": "A", "cnt": 5},
                {"processing_path": "X", "cnt": 99},
            ]
        )
        result = await service._path_mix(datetime(2026, 4, 1))
        assert result == PathMix(A=5, B=0, C=0)


# ---------------------------------------------------------------------
# 8. KPI sparkline shape — length and projection correctness
# ---------------------------------------------------------------------


class TestKpiSparklines:
    @pytest.mark.asyncio
    async def test_today_count_lands_at_index_29(self):
        # Build a daily row for "today" (computed in service) and assert
        # it ends up in the rightmost bucket of every sparkline.
        from utils.helpers import TimeHelper

        now = TimeHelper.ist_now()
        today_d = now.replace(hour=0, minute=0, second=0, microsecond=0).date()

        service = _service(
            fetchrow_side_effect=[
                {"total": 1, "resolved": 0, "avg_response_minutes": 0},
                {"total": 0, "resolved": 0, "avg_response_minutes": 0},
                {"cur": 0, "prev": 0},
            ],
            fetch_side_effect=[
                # daily kpi rows
                [{"day": today_d, "total": 1, "resolved": 0, "avg_min": 12}],
                # breaches daily
                [{"day": today_d, "cnt": 2}],
                # path_mix
                [],
                # volume_by_path
                [],
                # hourly ingested + resolved
                [],
                [],
                # confidence histogram
                [],
                # sla_by_team
                [],
                # top intents
                [],
            ],
        )
        result = await service.get_overview(correlation_id="test-spark")

        assert result.kpi_sparklines.received_per_day[-1] == 1
        assert sum(result.kpi_sparklines.received_per_day) == 1
        assert result.kpi_sparklines.response_minutes_per_day[-1] == 12
        assert result.kpi_sparklines.breaches_per_day[-1] == 2


# ---------------------------------------------------------------------
# 9. Confidence histogram bucketing
# ---------------------------------------------------------------------


class TestConfidenceHistogram:
    @pytest.mark.asyncio
    async def test_bucketing_is_correct(self):
        service = _service()
        service._postgres.fetch = AsyncMock(
            return_value=[
                {"score": 0.05},  # 0.0-0.2
                {"score": 0.3},   # 0.2-0.4
                {"score": 0.55},  # 0.4-0.6
                {"score": 0.65},  # 0.6-0.8
                {"score": 0.85},  # 0.8-1.0
                {"score": 0.99},  # 0.8-1.0
            ]
        )
        bands = await service._confidence_histogram(datetime(2026, 4, 1))
        as_dict = {b.band: b.n for b in bands}
        assert as_dict["0.0-0.2"] == 1
        assert as_dict["0.2-0.4"] == 1
        assert as_dict["0.4-0.6"] == 1
        assert as_dict["0.6-0.8"] == 1
        assert as_dict["0.8-1.0"] == 2
