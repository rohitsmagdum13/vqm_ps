"""Module: models/admin_overview.py

Pydantic response models for the Admin Operations Overview API.

The Overview screen renders a single GET /admin/overview call. To keep
the page from making 8 parallel requests, the response bundles every
chart's data into one payload. Each section is its own model so the
frontend can pull just the slice it needs and so we can extend any one
section without breaking the others.

All models use frozen=True for immutability, matching the project pattern.
Window for headline KPIs and most series is the last 30 days; sparklines
are length 30 (oldest -> newest); hourly_throughput is length 24.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class HeadlineKPIs(BaseModel):
    """The four big numbers at the top of the Overview screen.

    Each value is paired with a delta_pct comparing the last 30 days
    against the prior 30 days (negative is a decrease).
    """

    model_config = ConfigDict(frozen=True)

    queries_received: int = Field(description="Total queries created in the last 30 days")
    queries_received_delta_pct: float = Field(
        description="Percent change vs. the prior 30-day window"
    )
    resolution_rate_pct: float = Field(
        description="Percent of queries currently in RESOLVED/CLOSED, last 30 days"
    )
    resolution_rate_delta_pct: float = Field(
        description="Percent change vs. the prior 30-day window"
    )
    avg_response_minutes: int = Field(
        description="Average time from intake to first state transition (rounded to minutes)"
    )
    avg_response_delta_pct: float = Field(
        description="Percent change vs. the prior 30-day window"
    )
    sla_breaches: int = Field(
        description="Count of SLA checkpoints that fired L2 (95%) in the last 30 days"
    )
    sla_breaches_delta_pct: float = Field(
        description="Percent change vs. the prior 30-day window"
    )


class KPISparklines(BaseModel):
    """Day-by-day series for each headline KPI, oldest -> newest. All
    arrays are length 30 (zero-filled for days with no activity)."""

    model_config = ConfigDict(frozen=True)

    received_per_day: list[int] = Field(description="Queries created per day (length 30)")
    resolution_rate_per_day: list[float] = Field(
        description="Resolution rate (0.0-1.0) per day, length 30"
    )
    response_minutes_per_day: list[int] = Field(
        description="Average response minutes per day, length 30"
    )
    breaches_per_day: list[int] = Field(
        description="L2 SLA breaches per day, length 30"
    )


class PathMix(BaseModel):
    """Total queries by routing path over the last 30 days."""

    model_config = ConfigDict(frozen=True)

    A: int = Field(description="Path A — AI-resolved")  # noqa: N815 (matches frontend literal)
    B: int = Field(description="Path B — human team resolved")  # noqa: N815
    C: int = Field(description="Path C — low-confidence triage")  # noqa: N815


class VolumeRow(BaseModel):
    """One day's stacked volume by path."""

    model_config = ConfigDict(frozen=True)

    date: str = Field(description="ISO date (YYYY-MM-DD)")
    A: int  # noqa: N815
    B: int  # noqa: N815
    C: int  # noqa: N815
    received: int = Field(description="Total received that day (sum of paths plus untriaged)")


class HourlyRow(BaseModel):
    """One hour bucket of intake vs. resolution counts (last 24h)."""

    model_config = ConfigDict(frozen=True)

    hour: str = Field(description="HH (00-23) IST")
    ingested: int = Field(description="Queries created in that hour")
    resolved: int = Field(description="Queries that reached RESOLVED/CLOSED in that hour")


class ConfidenceBand(BaseModel):
    """A confidence histogram band."""

    model_config = ConfigDict(frozen=True)

    band: str = Field(description="Display label, e.g. '0.0-0.2'")
    n: int = Field(description="Number of queries whose analysis confidence falls in this band")


class TeamSLA(BaseModel):
    """SLA performance for a single assigned team over the last 30 days."""

    model_config = ConfigDict(frozen=True)

    team: str = Field(description="Team name from routing_decision.assigned_team")
    on_time: int = Field(description="Queries that closed before SLA deadline")
    breached: int = Field(description="Queries that fired L2 SLA breach")


class IntentBucket(BaseModel):
    """One row of the top-intents leaderboard."""

    model_config = ConfigDict(frozen=True)

    intent: str = Field(description="Intent / routing category")
    n: int = Field(description="Count over the last 30 days")


class AdminOverviewResponse(BaseModel):
    """Bundle of every chart on the Operations Overview page.

    Returned by GET /admin/overview. Designed as a single round-trip so
    the page can render in one render pass instead of eight network calls.
    """

    model_config = ConfigDict(frozen=True)

    kpis: HeadlineKPIs
    kpi_sparklines: KPISparklines
    path_mix: PathMix
    volume_by_path: list[VolumeRow] = Field(description="Stacked daily volume, length 30")
    hourly_throughput: list[HourlyRow] = Field(description="Last 24h hourly buckets, length 24")
    confidence_histogram: list[ConfidenceBand] = Field(
        description="Five bands: 0-0.2, 0.2-0.4, 0.4-0.6, 0.6-0.8, 0.8-1.0"
    )
    sla_by_team: list[TeamSLA] = Field(description="Per-team SLA performance, last 30 days")
    top_intents: list[IntentBucket] = Field(
        description="Top six intents by count, descending, last 30 days"
    )
