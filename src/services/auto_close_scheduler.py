"""Module: services/auto_close_scheduler.py

Phase 6 — Auto-Close Scheduler.

Scans workflow.closure_tracking on a timer and calls
ClosureService.close_case(AUTO_CLOSED) for any row whose
auto_close_deadline has passed without a vendor confirmation.

Loop shape mirrors services/sla_monitor.py. The difference is that
this scheduler does not publish events directly — it delegates the
full closure (DB update, ServiceNow, event, episodic memory) to
ClosureService so there is exactly one code path that closes a case.

Runs hourly by default (settings.auto_close_interval_seconds = 3600).
The deadline is measured in business days so a more frequent scan
would just waste cycles.
"""

from __future__ import annotations

import asyncio

import structlog

from config.settings import Settings
from services.closure import ClosureService
from utils.decorators import log_service_call
from utils.helpers import IdGenerator, TimeHelper

logger = structlog.get_logger(__name__)


class AutoCloseScheduler:
    """Background scheduler that auto-closes stale resolutions.

    Usage:
        scheduler = AutoCloseScheduler(postgres, closure_service, settings)
        asyncio.create_task(scheduler.start_loop())
        ...
        scheduler.stop()
    """

    def __init__(
        self,
        *,
        postgres,
        closure_service: ClosureService,
        settings: Settings,
    ) -> None:
        """Wire up the dependencies.

        Args:
            postgres: PostgresConnector for the scan query.
            closure_service: ClosureService for the actual close_case call.
            settings: Application settings (scan interval).
        """
        self._postgres = postgres
        self._closure_service = closure_service
        self._settings = settings
        self._interval = settings.auto_close_interval_seconds
        self._running = False

    @log_service_call
    async def tick(self, *, correlation_id: str | None = None) -> int:
        """Run one scan cycle. Returns the number of cases closed.

        Errors on individual rows are logged and skipped so one bad
        row cannot stall the scheduler.
        """
        correlation_id = correlation_id or IdGenerator.generate_correlation_id()
        now = TimeHelper.ist_now()
        closed_count = 0

        try:
            rows = await self._postgres.fetch(
                """
                SELECT query_id, correlation_id
                FROM workflow.closure_tracking
                WHERE closed_at IS NULL
                  AND auto_close_deadline <= $1
                """,
                now,
            )
        except Exception:
            logger.exception(
                "Auto-close scheduler failed to fetch pending closures",
                correlation_id=correlation_id,
            )
            return 0

        for row in rows:
            query_id = row.get("query_id")
            row_correlation_id = row.get("correlation_id") or correlation_id
            if not query_id:
                continue
            try:
                await self._closure_service.close_case(
                    query_id=query_id,
                    reason="AUTO_CLOSED",
                    correlation_id=row_correlation_id,
                )
                closed_count += 1
            except Exception:
                logger.warning(
                    "Auto-close failed for row — skipping",
                    query_id=query_id,
                    correlation_id=row_correlation_id,
                )

        logger.info(
            "Auto-close tick complete",
            scanned=len(rows),
            closed=closed_count,
            correlation_id=correlation_id,
        )
        return closed_count

    async def start_loop(self) -> None:
        """Run the scheduler continuously until stop() is called."""
        self._running = True
        logger.info(
            "Auto-close scheduler started", interval_seconds=self._interval
        )

        while self._running:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Auto-close tick crashed — continuing")
            try:
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                raise

        logger.info("Auto-close scheduler stopped")

    def stop(self) -> None:
        """Signal the scheduler loop to stop after the current tick."""
        self._running = False
