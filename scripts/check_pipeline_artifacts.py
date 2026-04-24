"""Script: check_pipeline_artifacts.py

Quick verification that the new correctness fixes left the DB in the
expected state after the last email ingestion run.

Inspects:
  1. cache.idempotency_keys — recent rows and their status/claim fields.
  2. cache.outbox_events     — recent rows, sent_at state.
  3. workflow.case_execution — most recent query_id.

Usage:
    uv run python scripts/check_pipeline_artifacts.py
"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "src")

from config.settings import get_settings  # noqa: E402
from db.connection import PostgresConnector  # noqa: E402
from utils.logger import LoggingSetup  # noqa: E402


def header(text: str) -> None:
    print(f"\n{'=' * 70}\n  {text}\n{'=' * 70}")


async def run() -> None:
    LoggingSetup.configure()
    postgres = PostgresConnector(get_settings())
    await postgres.connect()

    try:
        header("cache.idempotency_keys — 5 most recent")
        rows = await postgres.fetch(
            """
            SELECT key, status, correlation_id, claim_expires_at, created_at
              FROM cache.idempotency_keys
             ORDER BY created_at DESC
             LIMIT 5
            """
        )
        if not rows:
            print("  (no rows)")
        for r in rows:
            print(
                f"  status={r['status']:<10} "
                f"created={r['created_at']}  "
                f"claim_exp={r['claim_expires_at']}\n"
                f"    key={r['key'][:60]}..."
            )

        header("cache.outbox_events — 5 most recent")
        rows = await postgres.fetch(
            """
            SELECT event_key, queue_url, sent_at, attempt_count,
                   last_error, created_at
              FROM cache.outbox_events
             ORDER BY created_at DESC
             LIMIT 5
            """
        )
        if not rows:
            print("  (no rows yet — no emails processed since migration 014)")
        for r in rows:
            sent_marker = "SENT" if r["sent_at"] else "PENDING"
            print(
                f"  [{sent_marker}] event_key={r['event_key']}\n"
                f"    sent_at={r['sent_at']}  attempts={r['attempt_count']}\n"
                f"    queue={r['queue_url']}\n"
                f"    last_error={r['last_error'] or '(none)'}"
            )

        header("workflow.case_execution — 3 most recent email rows")
        rows = await postgres.fetch(
            """
            SELECT query_id, status, source, vendor_id, created_at
              FROM workflow.case_execution
             WHERE source = 'email'
             ORDER BY created_at DESC
             LIMIT 3
            """
        )
        if not rows:
            print("  (no rows)")
        for r in rows:
            print(
                f"  {r['query_id']}  status={r['status']}  "
                f"vendor={r['vendor_id']}  created={r['created_at']}"
            )

        header("Consistency check")
        # Any outbox rows older than 5 min that never published are a
        # reliability signal — the drainer hasn't picked them up or SQS
        # is persistently broken.
        stuck = await postgres.fetchrow(
            """
            SELECT COUNT(*) AS stuck_count
              FROM cache.outbox_events
             WHERE sent_at IS NULL
               AND created_at < NOW() - INTERVAL '5 minutes'
            """
        )
        stuck_count = stuck["stuck_count"] if stuck else 0
        marker = "[OK]" if stuck_count == 0 else "[WARN]"
        print(f"  {marker} outbox rows older than 5min with sent_at IS NULL: {stuck_count}")

        # Any idempotency PROCESSING claims that expired — means a worker
        # crashed and the drain cycle hasn't reclaimed yet. Under normal
        # load this should be 0 or 1; many indicates a stuck pipeline.
        stale = await postgres.fetchrow(
            """
            SELECT COUNT(*) AS stale_count
              FROM cache.idempotency_keys
             WHERE status = 'PROCESSING'
               AND claim_expires_at < NOW()
            """
        )
        stale_count = stale["stale_count"] if stale else 0
        marker = "[OK]" if stale_count == 0 else "[WARN]"
        print(f"  {marker} idempotency rows PROCESSING with expired claim: {stale_count}")

        print()
    finally:
        await postgres.disconnect()


if __name__ == "__main__":
    asyncio.run(run())
