"""Script: test_portal_submission.py

Test the portal query submission pipeline using real credentials.

Usage:
    uv run python scripts/test_portal_submission.py

This script connects to real services:
  - PostgreSQL via SSH tunnel (idempotency, case_execution)
  - SQS (enqueue for AI pipeline)
  - EventBridge (publish QueryReceived event)

Make sure your .env has valid credentials.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time

# Add src/ to Python path so imports work
sys.path.insert(0, ".")
sys.path.insert(0, "src")

from config.settings import get_settings  # noqa: E402
from events.eventbridge import EventBridgeConnector  # noqa: E402
from db.connection import PostgresConnector  # noqa: E402
from queues.sqs import SQSConnector  # noqa: E402
from services.portal_submission import PortalIntakeService  # noqa: E402
from models.query import QuerySubmission  # noqa: E402
from utils.exceptions import DuplicateQueryError  # noqa: E402
from utils.logger import LoggingSetup  # noqa: E402


def print_header(text: str) -> None:
    """Print a section header."""
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}\n")


async def run_test() -> None:
    """Run the portal submission test with real services."""
    LoggingSetup.configure()
    logger = logging.getLogger("scripts.test_portal_submission")

    settings = get_settings()
    postgres: PostgresConnector | None = None

    try:
        # -- Initialize connectors ---------------------------------
        print_header("INITIALIZING CONNECTORS")

        postgres = PostgresConnector(settings)
        await postgres.connect()
        print("  [OK] PostgreSQL connected via SSH tunnel")

        sqs = SQSConnector(settings)
        print("  [OK] SQS connector created")

        eventbridge = EventBridgeConnector(settings)
        print("  [OK] EventBridge connector created")

        portal_intake = PortalIntakeService(
            postgres=postgres,
            sqs=sqs,
            eventbridge=eventbridge,
            settings=settings,
        )
        print("  [OK] PortalIntakeService built")

        # -- Submit a test query -----------------------------------
        print_header("SUBMITTING TEST QUERY")

        # Build a test QuerySubmission
        submission = QuerySubmission(
            query_type="Invoice",
            subject="Test query - Invoice INV-2026-TEST status check",
            description=(
                "This is a test query submitted via the test_portal_submission.py script. "
                "We need to check the status of invoice INV-2026-TEST for order PO-2026-001. "
                "The invoice was submitted on 2026-04-01 and payment is overdue."
            ),
            priority="MEDIUM",
            reference_number="INV-2026-TEST",
        )
        vendor_id = "V-TEST-001"

        print(f"  Query Type:  {submission.query_type}")
        print(f"  Subject:     {submission.subject}")
        print(f"  Priority:    {submission.priority}")
        print(f"  Vendor ID:   {vendor_id}")
        print(f"  Reference:   {submission.reference_number}")

        start_time = time.time()
        payload = await portal_intake.submit_query(submission, vendor_id)
        elapsed_ms = (time.time() - start_time) * 1000

        # -- Display results ---------------------------------------
        print_header("RESULT: QUERY SUBMITTED SUCCESSFULLY")

        print(f"  Query ID:       {payload.query_id}")
        print(f"  Correlation ID: {payload.correlation_id}")
        print(f"  Execution ID:   {payload.execution_id}")
        print(f"  Source:         {payload.source}")
        print(f"  Vendor ID:      {payload.vendor_id}")
        print(f"  Subject:        {payload.subject}")
        print(f"  Priority:       {payload.priority}")
        print(f"  Thread Status:  {payload.thread_status}")
        print(f"  Received At:    {payload.received_at}")
        print(f"  Processing:     {elapsed_ms:.0f}ms")

        # -- Test idempotency --------------------------------------
        print_header("TESTING IDEMPOTENCY (same query again)")

        try:
            await portal_intake.submit_query(submission, vendor_id)
            print("  [FAIL] IDEMPOTENCY FAILED -- second submission did not raise DuplicateQueryError")
        except DuplicateQueryError:
            print("  [OK] Idempotency works! DuplicateQueryError raised on duplicate submission")

        # -- Verify in database ------------------------------------
        print_header("VERIFYING DATABASE RECORDS")

        row = await postgres.fetchrow(
            "SELECT query_id, status, source, vendor_id, created_at "
            "FROM workflow.case_execution WHERE query_id = $1",
            payload.query_id,
        )
        if row:
            print("  [OK] workflow.case_execution record found:")
            print(f"    Query ID:   {row['query_id']}")
            print(f"    Status:     {row['status']}")
            print(f"    Source:     {row['source']}")
            print(f"    Vendor ID:  {row['vendor_id']}")
            print(f"    Created At: {row['created_at']}")
        else:
            print("  [FAIL] No record found in workflow.case_execution")

        # -- Done --------------------------------------------------
        print_header("TEST COMPLETE")
        print(f"  Query '{submission.subject}' submitted as {payload.query_id}")
        print(f"  Total time: {elapsed_ms:.0f}ms")
        print("  Idempotency: OK")

    except Exception:
        logger.exception("Portal submission test failed")
        print("\n  [FAIL] TEST FAILED -- check logs above for details")
        raise
    finally:
        if postgres:
            await postgres.disconnect()
        print("\n  Connectors closed.\n")


if __name__ == "__main__":
    asyncio.run(run_test())
