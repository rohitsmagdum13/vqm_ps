"""Module: services/sla_monitor.py

Phase 6 — SLA Monitor.

Scans workflow.sla_checkpoints on a timer and publishes
SLAWarning70 / SLAEscalation85 / SLAEscalation95 events the first
time each threshold is crossed. The _fired boolean columns are
idempotency guards — once set, the monitor never republishes.

Loop shape mirrors ReconciliationPoller (services/polling.py):
start_monitor_loop() calls tick() every sla_monitor_interval_seconds
until stop() is invoked. Errors on a single row are logged and
skipped — the monitor does not let one bad row stall the whole cycle.

Event publish failures are non-critical: we log but do NOT flip the
corresponding _fired flag, so the next tick retries. This keeps
EventBridge outages from silently losing escalations.
"""

from __future__ import annotations

import asyncio

import structlog

from config.settings import Settings
from events.eventbridge import EventBridgeConnector
from models.sla import SlaThresholdCrossed
from utils.decorators import log_service_call
from utils.helpers import IdGenerator, TimeHelper

logger = structlog.get_logger(__name__)


class SlaMonitor:
    """Background SLA threshold monitor.

    Usage:
        monitor = SlaMonitor(postgres, eventbridge, settings)
        # Start in lifespan:
        asyncio.create_task(monitor.start_monitor_loop())
        # Stop in shutdown:
        monitor.stop()
    """

    def __init__(
        self,
        postgres,
        eventbridge: EventBridgeConnector,
        settings: Settings,
    ) -> None:
        """Initialize with required services and settings.

        Args:
            postgres: PostgresConnector for reading / updating checkpoints.
            eventbridge: EventBridge client for publishing SLA events.
            settings: Application settings (thresholds + scan interval).
        """
        self._postgres = postgres
        self._eventbridge = eventbridge
        self._settings = settings
        self._interval = settings.sla_monitor_interval_seconds
        self._running = False

    def compute_threshold_crossed(
        self,
        elapsed_percent: float,
        warning_fired: bool,
        l1_fired: bool,
        l2_fired: bool,
    ) -> SlaThresholdCrossed:
        """Return the highest uncrossed threshold that `elapsed_percent` crosses.

        Checked in descending order (L2, L1, WARNING) so a single tick that
        skips multiple thresholds still publishes the most severe one first
        — the next tick will pick up any lower ones whose flags are still
        False.
        """
        settings = self._settings
        if elapsed_percent >= settings.sla_l2_escalation_threshold_percent and not l2_fired:
            return SlaThresholdCrossed.L2
        if elapsed_percent >= settings.sla_l1_escalation_threshold_percent and not l1_fired:
            return SlaThresholdCrossed.L1
        if elapsed_percent >= settings.sla_warning_threshold_percent and not warning_fired:
            return SlaThresholdCrossed.WARNING
        return SlaThresholdCrossed.NONE

    @log_service_call
    async def tick(self, *, correlation_id: str | None = None) -> int:
        """Run one scan cycle. Returns the number of events published.

        Errors on individual rows are logged and skipped — the loop
        continues so one bad row can't block the rest.
        """
        correlation_id = correlation_id or IdGenerator.generate_correlation_id()
        events_published = 0

        try:
            rows = await self._postgres.fetch(
                """
                SELECT query_id, correlation_id, sla_started_at, sla_deadline,
                       sla_target_hours, warning_fired, l1_fired, l2_fired
                FROM workflow.sla_checkpoints
                WHERE last_status = 'ACTIVE'
                  AND sla_deadline IS NOT NULL
                """,
            )
        except Exception:
            logger.exception(
                "SLA monitor failed to fetch active checkpoints",
                correlation_id=correlation_id,
            )
            return 0

        now = TimeHelper.ist_now()

        for row in rows:
            try:
                event_published = await self._process_row(row, now)
                if event_published:
                    events_published += 1
            except Exception:
                logger.warning(
                    "SLA monitor failed to process row — skipping",
                    query_id=row.get("query_id"),
                    correlation_id=correlation_id,
                )

        # Bump last_checked_at for every row scanned — purely informational
        if rows:
            try:
                await self._postgres.execute(
                    """
                    UPDATE workflow.sla_checkpoints
                    SET last_checked_at = $1, updated_at = $1
                    WHERE last_status = 'ACTIVE'
                    """,
                    now,
                )
            except Exception:
                logger.warning(
                    "SLA monitor failed to bump last_checked_at",
                    correlation_id=correlation_id,
                )

        logger.info(
            "SLA monitor tick complete",
            scanned=len(rows),
            events_published=events_published,
            correlation_id=correlation_id,
        )
        return events_published

    async def _process_row(self, row: dict, now) -> bool:
        """Decide + publish + flip flag for one checkpoint row.

        Returns True if an event was published, False otherwise.
        """
        started = row["sla_started_at"]
        deadline = row["sla_deadline"]
        total_seconds = (deadline - started).total_seconds()
        if total_seconds <= 0:
            return False
        elapsed_seconds = (now - started).total_seconds()
        elapsed_percent = (elapsed_seconds / total_seconds) * 100

        crossed = self.compute_threshold_crossed(
            elapsed_percent,
            row["warning_fired"],
            row["l1_fired"],
            row["l2_fired"],
        )
        if crossed is SlaThresholdCrossed.NONE:
            return False

        query_id = row["query_id"]
        cid = row["correlation_id"]

        event_type = {
            SlaThresholdCrossed.WARNING: "SLAWarning70",
            SlaThresholdCrossed.L1: "SLAEscalation85",
            SlaThresholdCrossed.L2: "SLAEscalation95",
        }[crossed]
        flag_column = {
            SlaThresholdCrossed.WARNING: "warning_fired",
            SlaThresholdCrossed.L1: "l1_fired",
            SlaThresholdCrossed.L2: "l2_fired",
        }[crossed]

        # Publish first — only flip the flag if publish succeeded. This way
        # an EventBridge outage doesn't silently mark the threshold fired.
        try:
            await self._eventbridge.publish_event(
                event_type,
                {
                    "query_id": query_id,
                    "elapsed_percent": round(elapsed_percent, 2),
                    "sla_deadline": deadline.isoformat(),
                    "sla_target_hours": row["sla_target_hours"],
                },
                correlation_id=cid,
            )
        except Exception:
            logger.warning(
                "SLA monitor failed to publish event — will retry next tick",
                query_id=query_id,
                event_type=event_type,
                correlation_id=cid,
            )
            return False

        await self._postgres.execute(
            f"UPDATE workflow.sla_checkpoints SET {flag_column} = TRUE, updated_at = $1 WHERE query_id = $2",  # noqa: S608
            now,
            query_id,
        )
        logger.info(
            "SLA threshold crossed",
            query_id=query_id,
            event_type=event_type,
            elapsed_percent=round(elapsed_percent, 2),
            correlation_id=cid,
        )
        return True

    async def start_monitor_loop(self) -> None:
        """Run the monitor loop continuously until stop() is called."""
        self._running = True
        logger.info("SLA monitor started", interval_seconds=self._interval)

        while self._running:
            try:
                await self.tick()
            except asyncio.CancelledError:
                # Propagate cancellation so the task shuts down cleanly
                raise
            except Exception:
                logger.exception("SLA monitor tick crashed — continuing")
            try:
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                raise

        logger.info("SLA monitor stopped")

    def stop(self) -> None:
        """Signal the monitor loop to stop after the current tick."""
        self._running = False
