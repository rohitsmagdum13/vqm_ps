"""Module: services/polling.py

Reconciliation Poller for VQMS.

Polls the shared mailbox every 5 minutes via Microsoft Graph API
to catch any emails that the webhook might have missed. This is
Layer 1 of the defense-in-depth strategy (dual detection).

Each email found goes through the same process_email pipeline,
which includes idempotency check — so duplicates (already
processed via webhook) are silently skipped.

Usage:
    poller = ReconciliationPoller(email_intake, graph_api, settings)
    count = await poller.poll_once()  # Process unread emails
    await poller.start_polling_loop()  # Run continuously
"""

from __future__ import annotations

import asyncio

import structlog

from config.settings import Settings
from adapters.graph_api import GraphAPIConnector
from queues.sqs import SQSConnector
from services.email_intake import EmailIntakeService
from utils.decorators import log_service_call
from utils.helpers import IdGenerator

logger = structlog.get_logger(__name__)


class ReconciliationPoller:
    """Polls the shared mailbox for unread emails AND drains the outbox.

    Two responsibilities, both non-critical catch-ups for failures in
    the primary real-time paths:

    1. Unread email reconciliation — fetches messages the webhook may
       have missed and re-enters the ingestion pipeline for them.

    2. Outbox drain — re-publishes any ``cache.outbox_events`` rows
       whose first publish attempt failed (SQS outage, auth blip).
       Without this step a transient SQS failure would leave an email
       durably persisted in the DB but never visible to the AI pipeline.
    """

    def __init__(
        self,
        email_intake: EmailIntakeService,
        graph_api: GraphAPIConnector,
        settings: Settings,
        postgres: object | None = None,
        sqs: SQSConnector | None = None,
    ) -> None:
        """Initialize with required services and settings.

        Args:
            email_intake: The email intake service for processing.
            graph_api: Graph API connector for listing unread messages.
            settings: Application settings (poll interval).
            postgres: PostgresConnector — required for outbox drain.
                Optional so older call-sites that only want unread
                reconciliation still work.
            sqs: SQSConnector — required for outbox drain.
        """
        self._email_intake = email_intake
        self._graph_api = graph_api
        self._postgres = postgres
        self._sqs = sqs
        self._poll_interval = settings.graph_api_poll_interval_seconds
        self._running = False

    @log_service_call
    async def poll_once(
        self,
        *,
        correlation_id: str | None = None,
    ) -> int:
        """Fetch unread messages and process each one.

        Errors on individual messages are logged and skipped —
        the poller continues to the next message. Duplicates
        (already processed via webhook) return None from
        process_email, which is expected and counted separately.

        Args:
            correlation_id: Tracing ID for this poll cycle.

        Returns:
            Count of newly processed emails (excludes duplicates).
        """
        correlation_id = correlation_id or IdGenerator.generate_correlation_id()
        processed_count = 0

        try:
            unread_messages = await self._graph_api.list_unread_messages(
                top=50, correlation_id=correlation_id
            )
        except Exception:
            logger.exception(
                "Failed to list unread messages",
                correlation_id=correlation_id,
            )
            return 0

        logger.info(
            "Poller found unread messages",
            unread_count=len(unread_messages),
            correlation_id=correlation_id,
        )

        for message in unread_messages:
            message_id = message.get("id")
            if not message_id:
                continue

            try:
                result = await self._email_intake.process_email(
                    message_id, correlation_id=correlation_id
                )
                if result is not None:
                    processed_count += 1
                # result is None for duplicates — expected and silent
            except Exception:
                # Log and continue to next message — don't let one
                # bad email block the entire polling cycle
                logger.warning(
                    "Poller failed to process message — skipping",
                    message_id=message_id,
                    correlation_id=correlation_id,
                )

        # After the unread reconciliation, try to flush anything stuck
        # in the outbox from prior failed publish attempts. This runs
        # last so a slow drain never delays finding new unread mail.
        drained = await self._drain_outbox(correlation_id=correlation_id)

        logger.info(
            "Poller cycle complete",
            processed_count=processed_count,
            total_unread=len(unread_messages),
            outbox_drained=drained,
            correlation_id=correlation_id,
        )
        return processed_count

    async def _drain_outbox(
        self,
        *,
        correlation_id: str,
        limit: int = 50,
    ) -> int:
        """Re-publish any unsent cache.outbox_events rows.

        Skips silently when postgres/sqs weren't wired up (e.g. in
        tests). Each row is published independently — one failure
        doesn't block the rest.

        Returns the count of successfully re-published rows.
        """
        if self._postgres is None or self._sqs is None:
            return 0

        try:
            rows = await self._postgres.fetch_unsent_outbox(limit=limit)
        except Exception:
            logger.warning(
                "Outbox fetch failed — skipping drain this cycle",
                correlation_id=correlation_id,
            )
            return 0

        if not rows:
            return 0

        sent = 0
        for row in rows:
            event_key = row.get("event_key")
            queue_url = row.get("queue_url")
            payload = row.get("payload")
            if not event_key or not queue_url or payload is None:
                continue

            try:
                await self._sqs.send_message(
                    queue_url, payload, correlation_id=correlation_id
                )
                await self._postgres.mark_outbox_sent(event_key)
                sent += 1
            except Exception as exc:
                try:
                    await self._postgres.record_outbox_failure(
                        event_key, str(exc)
                    )
                except Exception:
                    pass  # best-effort
                logger.warning(
                    "Outbox drain publish failed — will retry next cycle",
                    event_key=event_key,
                    error=str(exc),
                    correlation_id=correlation_id,
                )

        if sent:
            logger.info(
                "Outbox drain published messages",
                sent=sent,
                attempted=len(rows),
                correlation_id=correlation_id,
            )
        return sent

    async def start_polling_loop(self) -> None:
        """Run the polling loop continuously.

        Polls every poll_interval seconds until stop() is called.
        Each cycle is independent — errors don't stop the loop.
        """
        self._running = True
        logger.info(
            "Reconciliation poller started",
            interval_seconds=self._poll_interval,
        )

        while self._running:
            await self.poll_once()
            await asyncio.sleep(self._poll_interval)

        logger.info("Reconciliation poller stopped")

    def stop(self) -> None:
        """Signal the polling loop to stop after the current cycle."""
        self._running = False
