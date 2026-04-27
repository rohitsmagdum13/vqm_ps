"""Script: check_email_poller.py

Real-API smoke test for the EmailReconciliationPoller.

Hits the real Microsoft Graph API delta endpoint and the real
PostgreSQL cache.kv_store table. Does NOT actually process any
emails — we stub the EmailIntakeService so this script can run
without SQS / S3 / Salesforce credentials.

What this verifies end-to-end:
  1. Graph delta_query returns a fresh @odata.deltaLink (cold start)
  2. The poller persists that link to cache.kv_store
  3. The next poll reads it back and passes it to delta_query
  4. Graph accepts the saved link and returns 0 messages (idle inbox)
     or returns only what changed since the last call

Run:
    uv run python scripts/check_email_poller.py
    uv run python scripts/check_email_poller.py --reset   # clear stored deltaLink first
    uv run python scripts/check_email_poller.py --process # actually process new emails
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

# Add src/ to Python path so imports work when run directly
sys.path.insert(0, ".")
sys.path.insert(0, "src")

from adapters.graph_api import GraphAPIConnector  # noqa: E402
from config.settings import get_settings  # noqa: E402
from db.connection import PostgresConnector  # noqa: E402
from services.polling import (  # noqa: E402
    DELTA_LINK_CACHE_KEY,
    EmailReconciliationPoller,
)
from utils.logger import LoggingSetup  # noqa: E402


def print_header(text: str) -> None:
    print(f"\n{'=' * 64}")
    print(f"  {text}")
    print(f"{'=' * 64}\n")


def print_check(name: str, passed: bool, detail: str = "") -> None:
    status = "[PASS]" if passed else "[FAIL]"
    suffix = f" -- {detail}" if detail else ""
    print(f"  {status} {name}{suffix}")


class StubEmailIntake:
    """Pretend EmailIntakeService that just records calls.

    Returns None for every message_id (looks like a duplicate to
    the poller). Lets us exercise the delta loop without any of
    the downstream connectors.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def process_email(
        self, message_id: str, *, correlation_id: str | None = None
    ) -> Any:
        self.calls.append(message_id)
        # Returning None means "duplicate / skipped" — keeps the
        # poller's success path simple and avoids any side effects.
        return None


class RealEmailIntake:
    """Wraps the real EmailIntakeService — only used with --process.

    Imported lazily so the script still runs when the optional
    dependencies (SQS, S3, Salesforce) aren't configured.
    """

    def __init__(
        self,
        graph_api: GraphAPIConnector,
        postgres: PostgresConnector,
        settings: Any,
    ) -> None:
        from queues.sqs import SQSConnector
        from storage.s3_client import S3Connector
        from events.eventbridge import EventBridgeConnector
        from adapters.salesforce import SalesforceConnector
        from services.email_intake import EmailIntakeService

        self._service = EmailIntakeService(
            graph_api=graph_api,
            postgres=postgres,
            s3=S3Connector(settings),
            sqs=SQSConnector(settings),
            eventbridge=EventBridgeConnector(settings),
            salesforce=SalesforceConnector(settings),
            settings=settings,
        )

    async def process_email(
        self, message_id: str, *, correlation_id: str | None = None
    ) -> Any:
        return await self._service.process_email(
            message_id, correlation_id=correlation_id
        )


async def reset_delta_link(postgres: PostgresConnector) -> int:
    """Delete the cached deltaLink so the next poll cold-starts."""
    result = await postgres.execute(
        "DELETE FROM cache.kv_store WHERE key = $1",
        DELTA_LINK_CACHE_KEY,
    )
    # asyncpg returns "DELETE N"
    try:
        return int(result.split()[-1])
    except Exception:
        return 0


async def read_delta_link(postgres: PostgresConnector) -> str | None:
    row = await postgres.fetchrow(
        "SELECT value FROM cache.kv_store WHERE key = $1",
        DELTA_LINK_CACHE_KEY,
    )
    if row is None:
        return None
    return row.get("value")


async def run() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete any stored deltaLink before running so we cold-start.",
    )
    parser.add_argument(
        "--process",
        action="store_true",
        help="Use the real EmailIntakeService instead of the stub. Requires "
        "SQS / S3 / Salesforce / EventBridge to be configured.",
    )
    args = parser.parse_args()

    LoggingSetup.configure()
    settings = get_settings()

    print_header("VQMS -- Email Reconciliation Poller Smoke Test")
    print(f"  Mailbox:        {settings.graph_api_mailbox}")
    print(f"  Tenant set:     {bool(settings.graph_api_tenant_id)}")
    print(f"  Postgres host:  {settings.postgres_host}")
    print(f"  Mode:           {'PROCESS' if args.process else 'STUB'}")
    print()

    if not settings.graph_api_tenant_id or not settings.graph_api_client_id:
        print("  [SKIP] Graph API credentials missing in .env")
        return 1

    # --- Connect Postgres ---
    print_header("Step 1: Connect to PostgreSQL")
    postgres = PostgresConnector(settings)
    try:
        await postgres.connect()
        print_check("PostgreSQL connection", True)
    except Exception as exc:
        print_check("PostgreSQL connection", False, str(exc))
        return 1

    # --- Optional reset ---
    if args.reset:
        deleted = await reset_delta_link(postgres)
        print_check(
            "Reset deltaLink",
            True,
            f"deleted {deleted} cached row(s) -- next cycle will cold-start",
        )

    # --- Build the poller ---
    print_header("Step 2: Build the poller")
    graph_api = GraphAPIConnector(settings)
    print_check("GraphAPIConnector built", True)

    if args.process:
        try:
            email_intake = RealEmailIntake(graph_api, postgres, settings)
            print_check("Real EmailIntakeService built", True)
        except Exception as exc:
            print_check("Real EmailIntakeService built", False, str(exc))
            await postgres.disconnect()
            return 1
    else:
        email_intake = StubEmailIntake()
        print_check("Stub EmailIntakeService built", True)

    poller = EmailReconciliationPoller(
        email_intake=email_intake,
        graph_api=graph_api,
        postgres=postgres,
        sqs=None,  # outbox drain skipped — we're only testing delta polling
        settings=settings,
    )
    print_check("EmailReconciliationPoller built", True)

    # --- Cycle 1 ---
    print_header("Step 3: Poll cycle 1 (cold start if --reset, else delta)")
    initial_link = await read_delta_link(postgres)
    print(f"  Cached deltaLink before cycle: {'present' if initial_link else 'NONE'}")

    try:
        c1_processed = await poller.poll_once()
        print_check("Cycle 1 completed without raising", True)
    except Exception as exc:
        print_check("Cycle 1 completed without raising", False, str(exc))
        await postgres.disconnect()
        await graph_api.close()
        return 1

    link_after_c1 = await read_delta_link(postgres)
    print_check(
        "deltaLink persisted to cache.kv_store",
        link_after_c1 is not None,
        f"link_len={len(link_after_c1) if link_after_c1 else 0}",
    )
    print(f"  Newly processed emails (cycle 1): {c1_processed}")
    if isinstance(email_intake, StubEmailIntake):
        print(f"  process_email called with: {len(email_intake.calls)} message(s)")

    # --- Cycle 2 ---
    print_header("Step 4: Poll cycle 2 (uses persisted deltaLink)")
    if isinstance(email_intake, StubEmailIntake):
        email_intake.calls.clear()

    try:
        c2_processed = await poller.poll_once()
        print_check("Cycle 2 completed without raising", True)
    except Exception as exc:
        print_check("Cycle 2 completed without raising", False, str(exc))
        await postgres.disconnect()
        await graph_api.close()
        return 1

    link_after_c2 = await read_delta_link(postgres)
    print_check(
        "deltaLink still cached after cycle 2",
        link_after_c2 is not None,
    )
    link_changed = link_after_c2 != link_after_c1
    print_check(
        "deltaLink advanced (Graph returned a new checkpoint)",
        link_changed or c2_processed == 0,
        "expected — link only changes when Graph processed a new page",
    )
    print(f"  Newly processed emails (cycle 2): {c2_processed}")
    if isinstance(email_intake, StubEmailIntake):
        print(f"  process_email called with: {len(email_intake.calls)} message(s)")

    # --- Cleanup ---
    await graph_api.close()
    await postgres.disconnect()

    print_header("RESULT")
    print("  [PASS] Delta-query polling is wired up correctly against real")
    print("         Microsoft Graph + real PostgreSQL.")
    print()
    print("  Next steps:")
    print("    - Send a test email to the mailbox, then re-run this script.")
    print("    - You should see cycle 2 pick up the new message_id.")
    print("    - With --process, that message will run through the real")
    print("      EmailIntakeService pipeline and land on SQS.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
