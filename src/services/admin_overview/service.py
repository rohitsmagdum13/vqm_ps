"""Module: services/admin_overview/service.py

Admin Operations Overview Service — read-only aggregations over the
workflow + reporting tables to power the Operations Overview screen.

Strategy:
- One public method (`get_overview`) that runs every aggregation in
  sequence and returns a single AdminOverviewResponse. The frontend
  hits one URL and renders eight charts off the same payload.
- Each section is its own private helper so the SQL stays readable
  and we can add unit-tests per slice.
- All counts are scoped to the last 30 days (configurable). Headline
  KPIs include a delta vs. the prior 30-day window so the page can
  show "+12% vs previous 30d" without a second round-trip.
- Failures in any one section are isolated — we log + return safe
  zero-filled defaults for that slice so a slow team-SLA query can't
  blank out the whole dashboard.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import structlog

from db.connection import PostgresConnector
from models.admin_overview import (
    AdminOverviewResponse,
    ConfidenceBand,
    HeadlineKPIs,
    HourlyRow,
    IntentBucket,
    KPISparklines,
    PathMix,
    TeamSLA,
    VolumeRow,
)
from utils.decorators import log_service_call
from utils.helpers import TimeHelper

logger = structlog.get_logger(__name__)


# Confidence-histogram band edges (low inclusive, high exclusive except the
# top band which is closed on both ends so 1.00 lands somewhere).
_CONFIDENCE_BANDS: tuple[tuple[str, float, float], ...] = (
    ("0.0-0.2", 0.0, 0.2),
    ("0.2-0.4", 0.2, 0.4),
    ("0.4-0.6", 0.4, 0.6),
    ("0.6-0.8", 0.6, 0.8),
    ("0.8-1.0", 0.8, 1.0001),
)

_KPI_WINDOW_DAYS = 30
_HOURLY_WINDOW_HOURS = 24
_TOP_INTENTS_LIMIT = 6


class AdminOverviewService:
    """Read-only service for the Operations Overview screen.

    Queries workflow.case_execution, workflow.routing_decision, and
    workflow.sla_checkpoints. Never writes — every method is a SELECT.
    """

    def __init__(self, postgres: PostgresConnector) -> None:
        self._postgres = postgres

    # ------------------------------------------------------------------
    # Public entry
    # ------------------------------------------------------------------

    @log_service_call
    async def get_overview(
        self,
        *,
        correlation_id: str = "",
    ) -> AdminOverviewResponse:
        """Run every aggregation and bundle into one payload.

        Sections that fail are logged and replaced with zero-filled
        defaults — the page should never blank out because of a single
        slow query.
        """
        now = TimeHelper.ist_now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        window_start = today_start - timedelta(days=_KPI_WINDOW_DAYS - 1)
        prev_window_start = window_start - timedelta(days=_KPI_WINDOW_DAYS)

        kpis, kpi_sparklines = await self._safe(
            "kpis_and_sparklines",
            correlation_id,
            self._kpis_and_sparklines,
            window_start,
            prev_window_start,
            today_start.date(),
            default=(self._zero_kpis(), self._zero_sparklines()),
        )
        path_mix = await self._safe(
            "path_mix",
            correlation_id,
            self._path_mix,
            window_start,
            default=PathMix(A=0, B=0, C=0),
        )
        volume_by_path = await self._safe(
            "volume_by_path",
            correlation_id,
            self._volume_by_path,
            window_start,
            today_start.date(),
            default=self._zero_volume(today_start.date()),
        )
        hourly_throughput = await self._safe(
            "hourly_throughput",
            correlation_id,
            self._hourly_throughput,
            now,
            default=self._zero_hourly(),
        )
        confidence_histogram = await self._safe(
            "confidence_histogram",
            correlation_id,
            self._confidence_histogram,
            window_start,
            default=[ConfidenceBand(band=b[0], n=0) for b in _CONFIDENCE_BANDS],
        )
        sla_by_team = await self._safe(
            "sla_by_team",
            correlation_id,
            self._sla_by_team,
            window_start,
            default=[],
        )
        top_intents = await self._safe(
            "top_intents",
            correlation_id,
            self._top_intents,
            window_start,
            default=[],
        )

        return AdminOverviewResponse(
            kpis=kpis,
            kpi_sparklines=kpi_sparklines,
            path_mix=path_mix,
            volume_by_path=volume_by_path,
            hourly_throughput=hourly_throughput,
            confidence_histogram=confidence_histogram,
            sla_by_team=sla_by_team,
            top_intents=top_intents,
        )

    # ------------------------------------------------------------------
    # KPIs + sparklines (single helper because they share a window)
    # ------------------------------------------------------------------

    async def _kpis_and_sparklines(
        self,
        window_start: datetime,
        prev_window_start: datetime,
        end_date: date,
    ) -> tuple[HeadlineKPIs, KPISparklines]:
        # 1. Headline counts — current window
        cur_sql = (
            "SELECT "
            "COUNT(*) AS total, "
            "COUNT(*) FILTER (WHERE status IN ('RESOLVED','CLOSED')) AS resolved, "
            "COALESCE(AVG(EXTRACT(EPOCH FROM (updated_at - created_at)) / 60.0), 0)::int "
            "    AS avg_response_minutes "
            "FROM workflow.case_execution "
            "WHERE created_at >= $1"
        )
        cur = await self._postgres.fetchrow(cur_sql, window_start)

        # 2. Headline counts — prior window (for delta calculation)
        prev_sql = (
            "SELECT "
            "COUNT(*) AS total, "
            "COUNT(*) FILTER (WHERE status IN ('RESOLVED','CLOSED')) AS resolved, "
            "COALESCE(AVG(EXTRACT(EPOCH FROM (updated_at - created_at)) / 60.0), 0)::int "
            "    AS avg_response_minutes "
            "FROM workflow.case_execution "
            "WHERE created_at >= $1 AND created_at < $2"
        )
        prev = await self._postgres.fetchrow(prev_sql, prev_window_start, window_start)

        # 3. SLA breaches — l2_fired counts
        breach_sql = (
            "SELECT "
            "COUNT(*) FILTER (WHERE l2_fired AND updated_at >= $1) AS cur, "
            "COUNT(*) FILTER (WHERE l2_fired AND updated_at >= $2 AND updated_at < $1) AS prev "
            "FROM workflow.sla_checkpoints"
        )
        breach = await self._postgres.fetchrow(breach_sql, window_start, prev_window_start)

        cur_total = (cur or {}).get("total", 0) or 0
        cur_resolved = (cur or {}).get("resolved", 0) or 0
        cur_avg = (cur or {}).get("avg_response_minutes", 0) or 0
        prev_total = (prev or {}).get("total", 0) or 0
        prev_resolved = (prev or {}).get("resolved", 0) or 0
        prev_avg = (prev or {}).get("avg_response_minutes", 0) or 0
        cur_breaches = (breach or {}).get("cur", 0) or 0
        prev_breaches = (breach or {}).get("prev", 0) or 0

        cur_resolution_rate = (cur_resolved / cur_total * 100.0) if cur_total else 0.0
        prev_resolution_rate = (prev_resolved / prev_total * 100.0) if prev_total else 0.0

        kpis = HeadlineKPIs(
            queries_received=cur_total,
            queries_received_delta_pct=self._pct_delta(cur_total, prev_total),
            resolution_rate_pct=round(cur_resolution_rate, 2),
            resolution_rate_delta_pct=self._pct_delta(
                cur_resolution_rate, prev_resolution_rate
            ),
            avg_response_minutes=int(cur_avg),
            avg_response_delta_pct=self._pct_delta(cur_avg, prev_avg),
            sla_breaches=cur_breaches,
            sla_breaches_delta_pct=self._pct_delta(cur_breaches, prev_breaches),
        )

        # 4. Sparklines — daily series for each KPI
        daily_sql = (
            "SELECT "
            "date_trunc('day', created_at)::date AS day, "
            "COUNT(*) AS total, "
            "COUNT(*) FILTER (WHERE status IN ('RESOLVED','CLOSED')) AS resolved, "
            "COALESCE(AVG(EXTRACT(EPOCH FROM (updated_at - created_at)) / 60.0), 0)::int "
            "    AS avg_min "
            "FROM workflow.case_execution "
            "WHERE created_at >= $1 "
            "GROUP BY day"
        )
        daily_rows = await self._postgres.fetch(daily_sql, window_start)

        breaches_daily_sql = (
            "SELECT "
            "date_trunc('day', updated_at)::date AS day, "
            "COUNT(*) FILTER (WHERE l2_fired) AS cnt "
            "FROM workflow.sla_checkpoints "
            "WHERE updated_at >= $1 "
            "GROUP BY day"
        )
        breaches_daily = await self._postgres.fetch(breaches_daily_sql, window_start)

        # Project per-day rows onto length-30 arrays, oldest -> newest.
        days = self._day_index(end_date, _KPI_WINDOW_DAYS)
        by_day = {row["day"]: row for row in daily_rows}
        breaches_by_day = {row["day"]: row["cnt"] or 0 for row in breaches_daily}

        received_per_day = [int(by_day.get(d, {}).get("total", 0) or 0) for d in days]
        response_minutes_per_day = [
            int(by_day.get(d, {}).get("avg_min", 0) or 0) for d in days
        ]
        resolution_rate_per_day = []
        for d in days:
            row = by_day.get(d, {})
            t = row.get("total", 0) or 0
            r = row.get("resolved", 0) or 0
            resolution_rate_per_day.append(round(r / t, 4) if t else 0.0)
        breaches_per_day = [int(breaches_by_day.get(d, 0)) for d in days]

        sparklines = KPISparklines(
            received_per_day=received_per_day,
            resolution_rate_per_day=resolution_rate_per_day,
            response_minutes_per_day=response_minutes_per_day,
            breaches_per_day=breaches_per_day,
        )
        return kpis, sparklines

    # ------------------------------------------------------------------
    # Path mix (3 totals)
    # ------------------------------------------------------------------

    async def _path_mix(self, window_start: datetime) -> PathMix:
        sql = (
            "SELECT processing_path, COUNT(*) AS cnt "
            "FROM workflow.case_execution "
            "WHERE created_at >= $1 AND processing_path IN ('A','B','C') "
            "GROUP BY processing_path"
        )
        rows = await self._postgres.fetch(sql, window_start)
        out = {"A": 0, "B": 0, "C": 0}
        for row in rows:
            key = row["processing_path"]
            if key in out:
                out[key] = int(row["cnt"] or 0)
        return PathMix(A=out["A"], B=out["B"], C=out["C"])

    # ------------------------------------------------------------------
    # Volume by path — stacked daily series
    # ------------------------------------------------------------------

    async def _volume_by_path(
        self, window_start: datetime, end_date: date
    ) -> list[VolumeRow]:
        sql = (
            "SELECT "
            "date_trunc('day', created_at)::date AS day, "
            "COUNT(*) FILTER (WHERE processing_path = 'A') AS a, "
            "COUNT(*) FILTER (WHERE processing_path = 'B') AS b, "
            "COUNT(*) FILTER (WHERE processing_path = 'C') AS c, "
            "COUNT(*) AS received "
            "FROM workflow.case_execution "
            "WHERE created_at >= $1 "
            "GROUP BY day"
        )
        rows = await self._postgres.fetch(sql, window_start)
        by_day = {row["day"]: row for row in rows}
        days = self._day_index(end_date, _KPI_WINDOW_DAYS)

        return [
            VolumeRow(
                date=d.isoformat(),
                A=int((by_day.get(d) or {}).get("a", 0) or 0),
                B=int((by_day.get(d) or {}).get("b", 0) or 0),
                C=int((by_day.get(d) or {}).get("c", 0) or 0),
                received=int((by_day.get(d) or {}).get("received", 0) or 0),
            )
            for d in days
        ]

    # ------------------------------------------------------------------
    # Hourly throughput — last 24h
    # ------------------------------------------------------------------

    async def _hourly_throughput(self, now: datetime) -> list[HourlyRow]:
        twenty_four_hours_ago = now - timedelta(hours=_HOURLY_WINDOW_HOURS)

        ingested_sql = (
            "SELECT date_trunc('hour', created_at) AS hour_ts, COUNT(*) AS cnt "
            "FROM workflow.case_execution "
            "WHERE created_at >= $1 "
            "GROUP BY hour_ts"
        )
        resolved_sql = (
            "SELECT date_trunc('hour', updated_at) AS hour_ts, COUNT(*) AS cnt "
            "FROM workflow.case_execution "
            "WHERE updated_at >= $1 AND status IN ('RESOLVED', 'CLOSED') "
            "GROUP BY hour_ts"
        )
        ingested_rows = await self._postgres.fetch(ingested_sql, twenty_four_hours_ago)
        resolved_rows = await self._postgres.fetch(resolved_sql, twenty_four_hours_ago)
        ingested = {row["hour_ts"]: int(row["cnt"] or 0) for row in ingested_rows}
        resolved = {row["hour_ts"]: int(row["cnt"] or 0) for row in resolved_rows}

        # Build 24 buckets oldest -> newest, anchored to the start of the
        # current hour. This keeps "now" in the rightmost bucket.
        end_hour = now.replace(minute=0, second=0, microsecond=0)
        hours = [end_hour - timedelta(hours=offset) for offset in range(_HOURLY_WINDOW_HOURS - 1, -1, -1)]
        return [
            HourlyRow(
                hour=h.strftime("%H"),
                ingested=ingested.get(h, 0),
                resolved=resolved.get(h, 0),
            )
            for h in hours
        ]

    # ------------------------------------------------------------------
    # Confidence histogram — bucket analysis_result.confidence_score
    # ------------------------------------------------------------------

    async def _confidence_histogram(
        self, window_start: datetime
    ) -> list[ConfidenceBand]:
        # Confidence lives inside a JSONB column on case_execution. PG can
        # cast JSON text -> float natively; rows where the path is missing
        # or non-numeric simply fall outside every band and contribute zero.
        sql = (
            "SELECT (analysis_result->>'confidence_score')::float AS score "
            "FROM workflow.case_execution "
            "WHERE created_at >= $1 "
            "  AND analysis_result IS NOT NULL "
            "  AND analysis_result->>'confidence_score' ~ '^[0-9.]+$'"
        )
        rows = await self._postgres.fetch(sql, window_start)
        scores = [float(row["score"]) for row in rows if row["score"] is not None]

        bands: list[ConfidenceBand] = []
        for label, low, high in _CONFIDENCE_BANDS:
            n = sum(1 for s in scores if low <= s < high)
            bands.append(ConfidenceBand(band=label, n=n))
        return bands

    # ------------------------------------------------------------------
    # SLA performance by team
    # ------------------------------------------------------------------

    async def _sla_by_team(self, window_start: datetime) -> list[TeamSLA]:
        # Join routing_decision with sla_checkpoints. on_time = closed
        # before deadline AND not breached. breached = l2_fired.
        sql = (
            "SELECT "
            "rd.assigned_team AS team, "
            "COUNT(*) FILTER ("
            "  WHERE ce.status IN ('RESOLVED','CLOSED') "
            "  AND (sc.l2_fired IS NULL OR sc.l2_fired = FALSE)"
            ") AS on_time, "
            "COUNT(*) FILTER (WHERE sc.l2_fired) AS breached "
            "FROM workflow.routing_decision rd "
            "JOIN workflow.case_execution ce ON ce.query_id = rd.query_id "
            "LEFT JOIN workflow.sla_checkpoints sc ON sc.query_id = rd.query_id "
            "WHERE ce.created_at >= $1 "
            "GROUP BY rd.assigned_team "
            "ORDER BY (COUNT(*) FILTER (WHERE sc.l2_fired)) DESC, rd.assigned_team"
        )
        rows = await self._postgres.fetch(sql, window_start)
        return [
            TeamSLA(
                team=row["team"],
                on_time=int(row["on_time"] or 0),
                breached=int(row["breached"] or 0),
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Top intents (categories from routing_decision)
    # ------------------------------------------------------------------

    async def _top_intents(self, window_start: datetime) -> list[IntentBucket]:
        sql = (
            "SELECT rd.category AS intent, COUNT(*) AS cnt "
            "FROM workflow.routing_decision rd "
            "JOIN workflow.case_execution ce ON ce.query_id = rd.query_id "
            "WHERE ce.created_at >= $1 "
            "GROUP BY rd.category "
            "ORDER BY cnt DESC "
            "LIMIT $2"
        )
        rows = await self._postgres.fetch(sql, window_start, _TOP_INTENTS_LIMIT)
        return [IntentBucket(intent=row["intent"], n=int(row["cnt"] or 0)) for row in rows]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pct_delta(current: float, previous: float) -> float:
        """Percent change current vs previous, rounded to 1 dp.
        Previous = 0 with current > 0 returns 100.0 (any growth from
        nothing is "+100%" by convention). Both zero returns 0.0.
        """
        if previous == 0:
            return 100.0 if current else 0.0
        return round((current - previous) / previous * 100.0, 1)

    @staticmethod
    def _day_index(end_date: date, window_days: int) -> list[date]:
        """Length-`window_days` list of dates, oldest -> newest, ending
        on `end_date`."""
        return [
            end_date - timedelta(days=offset)
            for offset in range(window_days - 1, -1, -1)
        ]

    @staticmethod
    def _zero_kpis() -> HeadlineKPIs:
        return HeadlineKPIs(
            queries_received=0,
            queries_received_delta_pct=0.0,
            resolution_rate_pct=0.0,
            resolution_rate_delta_pct=0.0,
            avg_response_minutes=0,
            avg_response_delta_pct=0.0,
            sla_breaches=0,
            sla_breaches_delta_pct=0.0,
        )

    @staticmethod
    def _zero_sparklines() -> KPISparklines:
        return KPISparklines(
            received_per_day=[0] * _KPI_WINDOW_DAYS,
            resolution_rate_per_day=[0.0] * _KPI_WINDOW_DAYS,
            response_minutes_per_day=[0] * _KPI_WINDOW_DAYS,
            breaches_per_day=[0] * _KPI_WINDOW_DAYS,
        )

    @staticmethod
    def _zero_volume(end_date: date) -> list[VolumeRow]:
        return [
            VolumeRow(date=d.isoformat(), A=0, B=0, C=0, received=0)
            for d in AdminOverviewService._day_index(end_date, _KPI_WINDOW_DAYS)
        ]

    @staticmethod
    def _zero_hourly() -> list[HourlyRow]:
        # Anchored to UTC midnight so the shape is stable when the DB is empty.
        return [HourlyRow(hour=f"{h:02d}", ingested=0, resolved=0) for h in range(24)]

    async def _safe(
        self,
        section: str,
        correlation_id: str,
        fn,
        *args,
        default,
    ):
        """Run an aggregation with isolation — log + return default on
        failure so one slow query can't blank out the page."""
        try:
            return await fn(*args)
        except Exception:
            logger.exception(
                "admin_overview section failed",
                section=section,
                correlation_id=correlation_id,
            )
            return default
