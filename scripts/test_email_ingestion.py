"""Script: test_email_ingestion.py

Test the full 10-step email ingestion pipeline using real credentials.

Usage:
    # Process the first unread email from the mailbox
    uv run python scripts/test_email_ingestion.py

    # Process a specific email by message_id
    uv run python scripts/test_email_ingestion.py --message-id "AAMkAGI2TG93AAA="

    # Skip Salesforce vendor lookup (if SF credentials not available)
    uv run python scripts/test_email_ingestion.py --skip-salesforce

This script connects to ALL real services:
  - Microsoft Graph API (fetch email)
  - PostgreSQL via SSH tunnel (idempotency, metadata, case_execution)
  - S3 (raw email storage, attachments)
  - SQS (enqueue for AI pipeline)
  - EventBridge (publish EmailParsed event)
  - Salesforce (vendor identification)

Make sure your .env has valid credentials for all services.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from unittest.mock import AsyncMock

# Add src/ to Python path so imports work
sys.path.insert(0, ".")
sys.path.insert(0, "src")

from dotenv import load_dotenv  # noqa: E402

# Load .env BEFORE any connector imports so boto3 can find
# AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in os.environ
load_dotenv(override=True)

from config.settings import get_settings  # noqa: E402
from events.eventbridge import EventBridgeConnector  # noqa: E402
from adapters.graph_api import GraphAPIConnector  # noqa: E402
from db.connection import PostgresConnector  # noqa: E402
from storage.s3_client import S3Connector  # noqa: E402
from adapters.salesforce import SalesforceConnector  # noqa: E402
from queues.sqs import SQSConnector  # noqa: E402
from services.email_intake import EmailIntakeService  # noqa: E402
from utils.logger import LoggingSetup  # noqa: E402


def print_header(text: str) -> None:
    """Print a section header."""
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}\n")


async def run_test(
    message_id: str | None = None,
    skip_salesforce: bool = False,
) -> None:
    """Run the full email ingestion test with real services."""
    LoggingSetup.configure()
    logger = logging.getLogger("scripts.test_email_ingestion")

    # Suppress noisy third-party loggers (pdfplumber, pdfminer, msal, httpx)
    for noisy_logger in ("pdfminer", "pdfplumber", "msal", "httpx", "httpcore"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    settings = get_settings()

    # Track which connectors we created (for cleanup)
    graph_api: GraphAPIConnector | None = None
    postgres: PostgresConnector | None = None

    try:
        # -- Step 0: Initialize all connectors ---------------------
        print_header("INITIALIZING CONNECTORS")

        # PostgreSQL (SSH tunnel -> RDS)
        print("  Connecting to PostgreSQL via SSH tunnel...")
        postgres = PostgresConnector(settings)
        await postgres.connect()
        print("  [OK] PostgreSQL connected")

        # S3
        s3 = S3Connector(settings)
        print("  [OK] S3 connector created")

        # SQS
        sqs = SQSConnector(settings)
        print("  [OK] SQS connector created")

        # EventBridge
        eventbridge = EventBridgeConnector(settings)
        print("  [OK] EventBridge connector created")

        # Graph API
        graph_api = GraphAPIConnector(settings)
        print(f"  [OK] Graph API connector created (mailbox: {settings.graph_api_mailbox})")

        # Salesforce (or mock if skipped)
        if skip_salesforce:
            salesforce = AsyncMock()
            salesforce.identify_vendor.return_value = None
            print("  [SKIP] Salesforce SKIPPED (using mock -- vendor will be None)")
        else:
            salesforce = SalesforceConnector(settings)
            print("  [OK] Salesforce connector created")

        # Build the EmailIntakeService
        email_intake = EmailIntakeService(
            graph_api=graph_api,
            postgres=postgres,
            s3=s3,
            sqs=sqs,
            eventbridge=eventbridge,
            salesforce=salesforce,
            settings=settings,
        )
        print("\n  [OK] EmailIntakeService built with all connectors")

        # -- Step 1: Get message_id (from arg or list unread) ------
        print_header("FINDING EMAIL TO PROCESS")

        result = None
        elapsed_ms = 0.0
        skipped_message_ids: list[str] = []

        if message_id:
            # Explicit --message-id — run exactly once, no iteration.
            print(f"  Using provided message_id: {message_id[:50]}...")
            print_header("RUNNING 10-STEP EMAIL INGESTION PIPELINE")
            start_time = time.time()
            result = await email_intake.process_email(
                message_id, correlation_id=None,
            )
            elapsed_ms = (time.time() - start_time) * 1000
        else:
            # No message_id — walk newest-first through the Inbox and
            # process the first email that isn't already in the
            # idempotency table. Each iteration calls the full 10-step
            # pipeline; process_email() returns None for duplicates,
            # ParsedEmailPayload for fresh emails.
            print("  No message_id provided. Listing unread emails (newest first)...")
            messages = await graph_api.list_unread_messages(top=50)

            if not messages:
                print("  [FAIL] No unread emails found in the mailbox!")
                print("  Send a test email to the mailbox and try again.")
                return

            print(f"  Found {len(messages)} unread email(s). "
                  "Walking newest-first until a fresh one is found.\n")

            print_header("RUNNING 10-STEP EMAIL INGESTION PIPELINE")

            for idx, msg in enumerate(messages, start=1):
                candidate_id = msg["id"]
                sender = msg.get("from", {}).get("emailAddress", {})
                subject = msg.get("subject", "(no subject)")
                print(f"  [{idx}/{len(messages)}] Trying: {subject[:70]}")
                print(f"         From: {sender.get('name','N/A')} <{sender.get('address','N/A')}>")

                start_time = time.time()
                candidate_result = await email_intake.process_email(
                    candidate_id, correlation_id=None,
                )
                elapsed_ms = (time.time() - start_time) * 1000

                if candidate_result is None:
                    # Already processed — skip and try the next recent one.
                    print(f"         [SKIP] Already processed ({elapsed_ms:.0f}ms) — "
                          "trying next recent email\n")
                    skipped_message_ids.append(candidate_id)
                    continue

                # Fresh email processed — stop here.
                message_id = candidate_id
                result = candidate_result
                print(f"         [NEW]  Processed in {elapsed_ms:.0f}ms\n")
                break

            if result is None:
                print_header("RESULT: ALL UNREAD EMAILS ALREADY PROCESSED")
                print(f"  Tried {len(skipped_message_ids)} email(s) — every one was a "
                      "duplicate in cache.idempotency_keys.")
                print("\n  Options to get a fresh run:")
                print("  1. Send a new email to the mailbox, then re-run this script.")
                print("  2. Clear the idempotency table:")
                print("       DELETE FROM cache.idempotency_keys WHERE source='email';")
                print("  3. Target a specific message_id explicitly:")
                print("       uv run python scripts/test_email_ingestion.py --message-id <id>")
                return

        # -- Step 3: Display results -------------------------------
        if result is None:
            # Only reachable when --message-id points to an already-processed email.
            print_header("RESULT: DUPLICATE EMAIL")
            print("  The email was already processed (idempotency check returned False).")
            print("  Pass a different --message-id, or clear its row from "
                  "cache.idempotency_keys to re-run.")
        else:
            print_header("RESULT: EMAIL PROCESSED SUCCESSFULLY")

            print(f"  Query ID:         {result.query_id}")
            print(f"  Correlation ID:   {result.correlation_id}")
            print(f"  Sender:           {result.sender_name} <{result.sender_email}>")
            print(f"  Subject:          {result.subject}")
            print(f"  Body (first 200): {result.body_text[:200]}...")
            print(f"  Received At:      {result.received_at}")
            print(f"  Parsed At:        {result.parsed_at}")
            print(f"  Thread Status:    {result.thread_status}")
            print(f"  Conversation ID:  {result.conversation_id}")
            print(f"  Vendor ID:        {result.vendor_id or 'None (unresolved)'}")
            print(f"  Match Method:     {result.vendor_match_method or 'N/A'}")
            print(f"  Attachments:      {len(result.attachments)}")
            print(f"  S3 Raw Key:       {result.s3_raw_email_key or 'None'}")
            print(f"  Source:           {result.source}")
            print(f"  Processing Time:  {elapsed_ms:.0f}ms")

            if result.attachments:
                print(f"\n  --- Attachments ({len(result.attachments)}) ---")
                for att in result.attachments:
                    print(f"    - {att.filename} ({att.content_type}, {att.size_bytes} bytes)")
                    print(f"      S3 Key: {att.s3_key or 'N/A'}")
                    print(f"      Extraction: {att.extraction_status}")
                    if att.extracted_text:
                        print(f"      Text (first 100): {att.extracted_text[:100]}...")

        # -- Step 4: Test idempotency ------------------------------
        print_header("TESTING IDEMPOTENCY (same email again)")

        result2 = await email_intake.process_email(message_id)

        if result2 is None:
            print("  [OK] Idempotency works! Second call returned None (duplicate detected)")
        else:
            print("  [FAIL] IDEMPOTENCY FAILED -- second call returned a result instead of None")
            print(f"    Query ID: {result2.query_id}")

        # -- Step 5: Verify in database ----------------------------
        if result is not None:
            print_header("VERIFYING DATABASE RECORDS")

            # Check case_execution
            row = await postgres.fetchrow(
                "SELECT query_id, status, source, vendor_id, created_at "
                "FROM workflow.case_execution WHERE query_id = $1",
                result.query_id,
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

            # Check idempotency key
            idem_row = await postgres.fetchrow(
                "SELECT key, source, created_at "
                "FROM cache.idempotency_keys WHERE key = $1",
                message_id,
            )
            if idem_row:
                print("\n  [OK] cache.idempotency_keys record found:")
                print(f"    Key:        {idem_row['key'][:50]}...")
                print(f"    Source:     {idem_row['source']}")
                print(f"    Created At: {idem_row['created_at']}")
            else:
                print("\n  [FAIL] No record found in cache.idempotency_keys")

            # Check email_attachments
            att_rows = await postgres.fetch(
                "SELECT attachment_id, filename, content_type, size_bytes, "
                "s3_key, extraction_status, created_at "
                "FROM intake.email_attachments WHERE query_id = $1 "
                "ORDER BY id ASC",
                result.query_id,
            )
            if att_rows:
                print(f"\n  [OK] intake.email_attachments: {len(att_rows)} record(s):")
                for att_row in att_rows:
                    print(f"    - {att_row['filename']} ({att_row['content_type']})")
                    print(f"      ID:         {att_row['attachment_id']}")
                    print(f"      Size:       {att_row['size_bytes']} bytes")
                    print(f"      S3 Key:     {att_row['s3_key'] or 'N/A'}")
                    print(f"      Extraction: {att_row['extraction_status']}")
                    print(f"      Created At: {att_row['created_at']}")
            else:
                if result.attachments:
                    print(f"\n  [FAIL] No records in intake.email_attachments "
                          f"(expected {len(result.attachments)})")
                else:
                    print("\n  [INFO] No attachments in this email — table correctly empty")

        # -- Done --------------------------------------------------
        print_header("TEST COMPLETE")
        if result:
            print(f"  Email '{result.subject}' processed as {result.query_id}")
            print(f"  Total time: {elapsed_ms:.0f}ms")
        print("  Idempotency: OK")

    except Exception:
        logger.exception("Email ingestion test failed")
        print("\n  [FAIL] TEST FAILED -- check logs above for details")
        raise
    finally:
        # Cleanup
        if graph_api:
            await graph_api.close()
        if postgres:
            await postgres.disconnect()
        print("\n  Connectors closed.\n")


def main() -> None:
    """Parse args and run."""
    parser = argparse.ArgumentParser(
        description="Test the full email ingestion pipeline with real services"
    )
    parser.add_argument(
        "--message-id",
        type=str,
        default=None,
        help="Specific email message_id to process. If omitted, uses the first unread email.",
    )
    parser.add_argument(
        "--skip-salesforce",
        action="store_true",
        help="Skip Salesforce vendor lookup (use if SF credentials are not available)",
    )
    args = parser.parse_args()

    asyncio.run(run_test(message_id=args.message_id, skip_salesforce=args.skip_salesforce))


if __name__ == "__main__":
    main()
