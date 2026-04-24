"""Module: db/connection/queries.py

Database query operations for the PostgreSQL connector.

Covers:
- execute / fetch / fetchrow — the low-level CRUD helpers.
- check_idempotency + mark_idempotency_complete + release_idempotency_claim
  — claim-check pattern. A claim is written BEFORE processing and flipped
  to COMPLETED only after the full pipeline (including SQS enqueue)
  succeeds. Crashes between claim and completion leave the row with a
  short TTL, so the next poll reclaims the message instead of losing it.
- transaction() — async context manager yielding a connection that
  commits on exit and rolls back on exception. Used by services that
  must write multiple rows atomically.
- enqueue_outbox / mark_outbox_sent / fetch_unsent_outbox — transactional
  outbox. Callers write their domain rows AND an outbox row in one
  transaction, then publish. A background drainer cleans up rows that
  were committed but never successfully published (e.g. SQS outage).
- cache_read — TTL-aware cache read helper.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

import orjson
import structlog

from utils.helpers import TimeHelper
from utils.log_types import LOG_TYPE_INTEGRATION

if TYPE_CHECKING:
    import asyncpg

logger = structlog.get_logger(__name__)

# How long a worker has to finish processing before another worker is
# allowed to take over its idempotency claim. Short enough that a
# crashed worker doesn't hold emails hostage, long enough that a slow
# path (attachments, vendor lookup, LLM) finishes comfortably.
_CLAIM_TTL_SECONDS = 600  # 10 minutes


class QueryMixin:
    """Database query methods for the PostgreSQL connector.

    Mixed into PostgresConnector. Expects self._get_pool()
    from PostgresClient.
    """

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    async def execute(self, query: str, *args) -> str:
        """Execute a SQL statement and return the status string.

        Args:
            query: SQL query with $1, $2, ... placeholders.
            *args: Values for the placeholders.

        Returns:
            Command status string (e.g., "INSERT 0 1", "CREATE TABLE").
        """
        pool = self._get_pool()
        async with pool.acquire() as conn:
            return await conn.execute(query, *args)

    async def fetch(self, query: str, *args) -> list[dict]:
        """Execute a query and return all rows as dicts."""
        pool = self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows]

    async def fetchrow(self, query: str, *args) -> dict | None:
        """Execute a query and return the first row as a dict, or None."""
        pool = self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
            return dict(row) if row else None

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator["asyncpg.Connection"]:
        """Yield a connection inside a DB transaction.

        The transaction commits when the ``async with`` block exits
        normally and rolls back if any exception escapes. Callers that
        need to write multiple related rows atomically should use this
        instead of the pool-level execute helpers.

        Usage:
            async with postgres.transaction() as tx:
                await tx.execute(...)
                await tx.execute(...)
        """
        pool = self._get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                yield conn

    # ------------------------------------------------------------------
    # Claim-check idempotency
    # ------------------------------------------------------------------

    async def check_idempotency(
        self, key: str, source: str, correlation_id: str
    ) -> bool:
        """Claim-check idempotency — returns True iff this worker now owns
        a PROCESSING claim on the key.

        Atomically does one of:
          (a) INSERT a new claim (no existing row) → return True
          (b) Take over an expired PROCESSING claim (worker crashed before
              completing) → return True
          (c) Refuse the claim because the row is COMPLETED (true duplicate)
              or a PROCESSING claim is still within its TTL → return False

        Only callers that got True are allowed to process the message.
        They MUST call either ``mark_idempotency_complete`` on success or
        ``release_idempotency_claim`` on failure, otherwise the claim will
        sit around and fall back to case (b) after its TTL expires.

        Args:
            key: Unique key (e.g., Exchange message_id).
            source: Origin — "email" or "portal".
            correlation_id: Tracing ID for this attempt.

        Returns:
            True if we hold the claim; False if another worker holds it
            or it is already COMPLETED.
        """
        pool = self._get_pool()
        async with pool.acquire() as conn:
            # One atomic statement:
            # - INSERT if no row exists for this key.
            # - UPDATE (re-claim) only when the existing row is a STALE
            #   PROCESSING claim. For COMPLETED rows or fresh PROCESSING
            #   claims, the WHERE in DO UPDATE evaluates false and the
            #   row is left untouched → RETURNING emits nothing.
            row = await conn.fetchrow(
                f"""
                INSERT INTO cache.idempotency_keys
                    (key, source, correlation_id, status,
                     claim_expires_at, created_at)
                VALUES (
                    $1, $2, $3, 'PROCESSING',
                    NOW() + INTERVAL '{_CLAIM_TTL_SECONDS} seconds',
                    NOW()
                )
                ON CONFLICT (key) DO UPDATE
                   SET correlation_id   = EXCLUDED.correlation_id,
                       claim_expires_at = EXCLUDED.claim_expires_at,
                       status           = 'PROCESSING'
                 WHERE cache.idempotency_keys.status = 'PROCESSING'
                   AND cache.idempotency_keys.claim_expires_at < NOW()
                RETURNING id
                """,
                key,
                source,
                correlation_id,
            )

            if row is not None:
                return True

            # No row returned — either COMPLETED duplicate or in-flight
            # claim still valid. Both mean "skip".
            logger.info(
                "Idempotency claim refused — duplicate or in-flight",
                log_type=LOG_TYPE_INTEGRATION,
                tool="postgresql",
                key=key,
                source=source,
                correlation_id=correlation_id,
            )
            return False

    async def mark_idempotency_complete(
        self, key: str, correlation_id: str
    ) -> None:
        """Finalize a claim: flip status to COMPLETED.

        Called after the full ingestion pipeline (including SQS enqueue)
        succeeds. A COMPLETED row permanently blocks future attempts.

        Idempotent — calling twice is a no-op.
        """
        pool = self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE cache.idempotency_keys
                   SET status = 'COMPLETED',
                       claim_expires_at = NULL
                 WHERE key = $1
                """,
                key,
            )
        logger.debug(
            "Idempotency claim marked complete",
            log_type=LOG_TYPE_INTEGRATION,
            tool="postgresql",
            key=key,
            correlation_id=correlation_id,
        )

    async def release_idempotency_claim(
        self, key: str, correlation_id: str
    ) -> None:
        """Release a PROCESSING claim so the next attempt can re-claim.

        Called when the pipeline fails AFTER we successfully claimed the
        key but BEFORE we reached the completion mark. Deleting the row
        is safer than letting it TTL out — the next poll reattempts
        immediately instead of waiting 10 minutes.

        COMPLETED rows are never deleted — only stale PROCESSING ones.
        """
        pool = self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM cache.idempotency_keys
                 WHERE key = $1 AND status = 'PROCESSING'
                """,
                key,
            )
        logger.info(
            "Idempotency claim released — retry will re-claim",
            log_type=LOG_TYPE_INTEGRATION,
            tool="postgresql",
            key=key,
            correlation_id=correlation_id,
        )

    # ------------------------------------------------------------------
    # Transactional outbox
    # ------------------------------------------------------------------

    @staticmethod
    async def enqueue_outbox(
        conn: "asyncpg.Connection",
        *,
        event_key: str,
        queue_url: str,
        payload: dict,
    ) -> None:
        """Write a row into cache.outbox_events within an existing txn.

        This must be called with the same connection that wrote the
        domain rows, inside the same transaction, so that either both
        commit or both roll back.

        Args:
            conn: asyncpg connection from ``transaction()``.
            event_key: Natural key to dedupe publishes (usually query_id).
            queue_url: Destination SQS queue URL.
            payload: JSON-serializable message body.
        """
        await conn.execute(
            """
            INSERT INTO cache.outbox_events (event_key, queue_url, payload)
            VALUES ($1, $2, $3::jsonb)
            ON CONFLICT (event_key) DO NOTHING
            """,
            event_key,
            queue_url,
            orjson.dumps(payload).decode("utf-8"),
        )

    async def mark_outbox_sent(self, event_key: str) -> None:
        """Mark an outbox row as successfully published.

        After this, the drainer will never re-publish it. COMPLETED rows
        can be purged by a periodic cleanup job (not implemented here).
        """
        pool = self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE cache.outbox_events
                   SET sent_at = NOW()
                 WHERE event_key = $1
                """,
                event_key,
            )

    async def record_outbox_failure(
        self, event_key: str, error_message: str
    ) -> None:
        """Record a publish failure on an outbox row.

        Increments ``attempt_count`` and stores the last error for
        diagnostics. Leaves ``sent_at`` NULL so the drainer retries.
        """
        pool = self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE cache.outbox_events
                   SET attempt_count = attempt_count + 1,
                       last_error = $2
                 WHERE event_key = $1
                """,
                event_key,
                error_message[:500],
            )

    async def fetch_unsent_outbox(self, limit: int = 50) -> list[dict]:
        """Fetch outbox rows awaiting publication, oldest first.

        Used by the reconciliation poller's drain pass to retry any
        messages that didn't make it out on the first attempt (e.g.
        transient SQS errors).
        """
        return await self.fetch(
            """
            SELECT id, event_key, queue_url, payload, attempt_count
              FROM cache.outbox_events
             WHERE sent_at IS NULL
             ORDER BY created_at ASC
             LIMIT $1
            """,
            limit,
        )

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    async def cache_read(
        self, table: str, key_column: str, key_value: str
    ) -> dict | None:
        """Read a cached value, respecting expires_at TTL."""
        now = TimeHelper.ist_now()
        row = await self.fetchrow(
            f"SELECT * FROM {table} WHERE {key_column} = $1 AND expires_at > $2",  # noqa: S608
            key_value,
            now,
        )
        return row if row else None
