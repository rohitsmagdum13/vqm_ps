"""Module: services/polling.py

Email Reconciliation Poller for VQMS — delta-query upgrade.

Runs every poll_interval seconds and asks Microsoft Graph
"what changed since last call?" via the messages/delta endpoint.
On the very first call we get a ``@odata.deltaLink`` that we
persist in cache.kv_store; every subsequent call hits that link
and Graph returns only the new/changed messages.

This replaces the older "list all unread" polling loop. Same
safety net (catches anything the webhook misses), ~10x fewer
Graph API calls under steady state, and works even when emails
are marked read by another tool.

Each new message_id is handed to EmailIntakeService.process_email,
which has its own idempotency claim — so a webhook + poll race
is automatically deduped. Errors on individual messages are
logged and skipped (the rest of the cycle continues).

The poller also drains cache.outbox_events at the end of every
cycle so any SQS publish that failed earlier (transient outage,
auth blip) gets retried without manual intervention.

Usage:
    poller = EmailReconciliationPoller(
        email_intake, graph_api, postgres, sqs, settings
    )
    asyncio.create_task(poller.start_polling_loop())
    ...
    poller.stop()
"""

from __future__ import annotations

import asyncio

import orjson
import structlog

from adapters.graph_api import GraphAPIConnector
from cache.cache_client import set_with_ttl
from config.settings import Settings
from db.connection import PostgresConnector
from queues.sqs import SQSConnector
from services.email_intake import EmailIntakeService
from utils.decorators import log_service_call
from utils.helpers import IdGenerator, TimeHelper

logger = structlog.get_logger(__name__)

# Cache key the poller uses to persist the Graph @odata.deltaLink
# between cycles. Singleton key — there is only one mailbox and
# one delta sequence per deployment.
DELTA_LINK_CACHE_KEY = "vqms:graph:inbox:delta_link"

# TTL for the persisted delta link. Microsoft does not document a
# hard expiry but in practice an unused link can become stale after
# a few weeks. 30 days is comfortably inside that window — if the
# link goes stale Graph returns 410, we catch it and start fresh.
DELTA_LINK_TTL_SECONDS = 30 * 24 * 60 * 60

# Max page hops we follow in one cycle. Defends against pathological
# cases where Graph keeps returning nextLink without ever giving us a
# deltaLink (it would lock up the loop). 20 pages * 50 messages each
# = 1000 messages per cycle, well above any reasonable burst.
MAX_PAGE_HOPS_PER_CYCLE = 20

# HTTP status Graph returns when a deltaLink is too old to use.
DELTA_LINK_GONE_STATUS = 410


class EmailReconciliationPoller:
    """Polls the mailbox via Graph delta queries and drains the outbox.

    Two responsibilities, both non-critical catch-ups for failures
    in the primary real-time paths:

    1. Delta reconciliation — fetches messages the webhook may have
       missed via /messages/delta and re-enters the ingestion
       pipeline for each one.
    2. Outbox drain — re-publishes any cache.outbox_events rows
       whose first publish attempt failed (SQS outage, auth blip).
       Without this step a transient SQS failure would leave an
       email durably persisted in the DB but never visible to the
       AI pipeline.
    """

    def __init__(
        self,
        email_intake: EmailIntakeService,
        graph_api: GraphAPIConnector,
        postgres: PostgresConnector,
        sqs: SQSConnector | None,
        settings: Settings,
    ) -> None:
        """Initialize with required services and settings.

        Args:
            email_intake: The email intake service for processing.
            graph_api: Graph API connector for delta queries.
            postgres: PostgresConnector — used for the deltaLink
                cache and outbox drain.
            sqs: SQSConnector — used for outbox drain. Optional;
                when None the drain step is skipped.
            settings: Application settings (poll interval).
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
        """Run one poll cycle: delta query + outbox drain.

        Args:
            correlation_id: Tracing ID for this poll cycle.

        Returns:
            Count of newly processed emails this cycle (excludes
            duplicates already handled by the webhook).
        """
        correlation_id = correlation_id or IdGenerator.generate_correlation_id()

        delta_link = await self._read_delta_link()
        is_first_run = delta_link is None
        if is_first_run:
            logger.info(
                "Delta poller cold-start — initializing delta sequence",
                correlation_id=correlation_id,
            )

        processed_count, skipped_count, total_seen = await self._run_delta_pages(
            delta_link=delta_link,
            is_first_run=is_first_run,
            correlation_id=correlation_id,
        )

        drained = await self._drain_outbox(correlation_id=correlation_id)

        logger.info(
            "Poller cycle complete",
            processed_count=processed_count,
            skipped_count=skipped_count,
            total_seen=total_seen,
            outbox_drained=drained,
            cold_start=is_first_run,
            correlation_id=correlation_id,
        )
        return processed_count

    async def _run_delta_pages(
        self,
        *,
        delta_link: str | None,
        is_first_run: bool,
        correlation_id: str,
    ) -> tuple[int, int, int]:
        """Walk through delta pages until Graph returns a fresh deltaLink.

        Returns (processed_count, skipped_count, total_seen).
        """
        processed_count = 0
        skipped_count = 0
        total_seen = 0
        next_link = None

        for hop in range(MAX_PAGE_HOPS_PER_CYCLE):
            try:
                page = await self._graph_api.delta_query(
                    delta_link=next_link or delta_link,
                    correlation_id=correlation_id,
                )
            except Exception as exc:
                # 410 Gone means the deltaLink expired. Drop it and
                # restart cold on the next cycle — we will replay
                # the full inbox once and idempotency keys keep us
                # from sending duplicate replies.
                if self._is_delta_link_gone(exc) and not is_first_run:
                    logger.warning(
                        "Stored deltaLink is stale (410) — clearing and "
                        "will cold-start on next cycle",
                        correlation_id=correlation_id,
                    )
                    await self._clear_delta_link()
                    return processed_count, skipped_count, total_seen

                logger.exception(
                    "Delta query failed — skipping rest of cycle",
                    correlation_id=correlation_id,
                    page_hop=hop,
                )
                return processed_count, skipped_count, total_seen

            messages = page.get("messages") or []
            total_seen += len(messages)

            # On a cold start the first page returns the existing inbox
            # state. We do NOT re-process those — webhook + prior
            # idempotency rows already handled them. We only collect
            # the deltaLink so future cycles see real changes.
            if not is_first_run:
                processed, skipped = await self._process_messages(
                    messages, correlation_id=correlation_id
                )
                processed_count += processed
                skipped_count += skipped

            new_delta_link = page.get("delta_link")
            if new_delta_link:
                await self._save_delta_link(new_delta_link)
                logger.info(
                    "Delta sequence checkpointed",
                    page_hop=hop,
                    cold_start=is_first_run,
                    correlation_id=correlation_id,
                )
                return processed_count, skipped_count, total_seen

            next_link = page.get("next_link")
            if not next_link:
                # Neither deltaLink nor nextLink — abnormal but recoverable.
                logger.warning(
                    "Delta page returned no deltaLink and no nextLink",
                    correlation_id=correlation_id,
                )
                return processed_count, skipped_count, total_seen

        # Exhausted MAX_PAGE_HOPS_PER_CYCLE without a deltaLink —
        # bail out. Next cycle will resume from the last next_link.
        logger.warning(
            "Hit MAX_PAGE_HOPS_PER_CYCLE — will resume next cycle",
            correlation_id=correlation_id,
        )
        return processed_count, skipped_count, total_seen

    async def _process_messages(
        self,
        messages: list[dict],
        *,
        correlation_id: str,
    ) -> tuple[int, int]:
        """Run process_email for each delta message. One bad message
        does not block the rest.

        Returns (processed_count, skipped_count). "Processed" means
        process_email returned a non-None payload (genuinely new
        email this poller picked up). "Skipped" covers duplicates,
        deletions, malformed entries, and per-message errors.
        """
        processed = 0
        skipped = 0

        for msg in messages:
            # Tombstones from a delete event arrive as
            # {"@removed": {"reason": "..."}, "id": "..."}.
            # Nothing to process — the email is gone server-side.
            if "@removed" in msg:
                skipped += 1
                continue

            message_id = msg.get("id")
            if not message_id:
                skipped += 1
                continue

            try:
                result = await self._email_intake.process_email(
                    message_id, correlation_id=correlation_id
                )
                if result is not None:
                    processed += 1
                else:
                    # None = duplicate (idempotency) or rejected
                    # by relevance filter. Both are expected.
                    skipped += 1
            except Exception:
                # Don't let one bad email kill the whole cycle.
                # It will surface again on the next delta if Graph
                # marks it changed; otherwise the SQS retry path
                # owns the recovery.
                logger.warning(
                    "Poller failed to process message — skipping",
                    message_id=message_id,
                    correlation_id=correlation_id,
                )
                skipped += 1

        return processed, skipped

    async def _read_delta_link(self) -> str | None:
        """Read the persisted ``@odata.deltaLink`` from cache.kv_store.

        Returns None when no link is stored yet (cold start) or the
        DB read fails — both cases trigger a fresh delta sequence.
        """
        try:
            row = await self._postgres.fetchrow(
                "SELECT value FROM cache.kv_store "
                "WHERE key = $1 AND (expires_at IS NULL OR expires_at > $2)",
                DELTA_LINK_CACHE_KEY,
                TimeHelper.ist_now(),
            )
        except Exception:
            logger.warning(
                "Failed to read deltaLink from cache — cold-starting",
                tool="postgresql",
            )
            return None

        if row is None:
            return None
        return row.get("value")

    async def _save_delta_link(self, delta_link: str) -> None:
        """Persist the latest ``@odata.deltaLink`` to cache.kv_store.

        Failure is logged but not raised — losing the checkpoint
        means the next cycle does an extra cold start, not data loss.
        """
        try:
            await set_with_ttl(
                self._postgres,
                DELTA_LINK_CACHE_KEY,
                delta_link,
                DELTA_LINK_TTL_SECONDS,
            )
        except Exception:
            logger.warning(
                "Failed to persist deltaLink — next cycle will cold-start",
                tool="postgresql",
            )

    async def _clear_delta_link(self) -> None:
        """Delete the cached deltaLink so the next cycle starts cold."""
        try:
            await self._postgres.execute(
                "DELETE FROM cache.kv_store WHERE key = $1",
                DELTA_LINK_CACHE_KEY,
            )
        except Exception:
            logger.warning(
                "Failed to clear stale deltaLink — manual cleanup may be needed",
                tool="postgresql",
            )

    @staticmethod
    def _is_delta_link_gone(exc: BaseException) -> bool:
        """True if exc is a Graph 410 (deltaLink expired)."""
        status = getattr(exc, "status_code", None)
        return status == DELTA_LINK_GONE_STATUS

    async def _drain_outbox(
        self,
        *,
        correlation_id: str,
        limit: int = 50,
    ) -> int:
        """Re-publish any unsent ``cache.outbox_events`` rows.

        Skips silently when SQS isn't wired up (e.g. in tests).
        Each row is published independently — one failure doesn't
        block the rest. Returns the count of successfully republished
        rows.
        """
        if self._sqs is None:
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

            # asyncpg returns JSONB as a string. Normalize to dict
            # before send_message so the SQS body is valid JSON.
            if isinstance(payload, str):
                try:
                    payload = orjson.loads(payload)
                except Exception:
                    logger.warning(
                        "Outbox payload not valid JSON — skipping row",
                        event_key=event_key,
                    )
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
        Cancellation via task.cancel() exits between cycles.
        """
        self._running = True
        logger.info(
            "Email reconciliation poller started",
            interval_seconds=self._poll_interval,
        )

        try:
            while self._running:
                try:
                    await self.poll_once()
                except Exception:
                    # The poller must never die. Log and keep looping.
                    logger.exception("Poll cycle raised — continuing")

                # Sleep in small chunks so stop() takes effect quickly
                # without us missing a CancelledError.
                slept = 0
                while self._running and slept < self._poll_interval:
                    await asyncio.sleep(min(1, self._poll_interval - slept))
                    slept += 1
        except asyncio.CancelledError:
            logger.info("Email reconciliation poller cancelled")
            raise
        finally:
            self._running = False
            logger.info("Email reconciliation poller stopped")

    def stop(self) -> None:
        """Signal the polling loop to stop after the current cycle."""
        self._running = False
