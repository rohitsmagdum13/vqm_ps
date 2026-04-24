"""Script: mark_unread_mails_read.py

List every unread email in the configured mailbox and flip them all to
read via the Graph API.

Useful when:
- The inbox has piled up with old test mail you want to clear.
- You want to stop the reconciliation poller from re-picking up emails
  that were processed before ``mark_as_read`` was added to the pipeline.
- You're rehearsing a clean-slate demo and want the unread count at 0.

Does NOT run the ingestion pipeline — this is a pure Outlook housekeeper.
If you want to ingest + mark read, use ``scripts/test_email_ingestion.py``
instead.

Usage:
    # See what would be marked, but don't touch anything
    uv run python scripts/mark_unread_mails_read.py --dry-run

    # Mark the first 50 unread mails as read (default)
    uv run python scripts/mark_unread_mails_read.py

    # Mark up to 200
    uv run python scripts/mark_unread_mails_read.py --top 200

    # No summary noise per message — just totals
    uv run python scripts/mark_unread_mails_read.py --quiet
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

import structlog

# Make src/ importable when running as a script
sys.path.insert(0, ".")
sys.path.insert(0, "src")

from adapters.graph_api import GraphAPIConnector  # noqa: E402
from config.settings import get_settings  # noqa: E402
from utils.logger import LoggingSetup  # noqa: E402


def print_header(text: str) -> None:
    """Print a section header."""
    print(f"\n{'=' * 70}\n  {text}\n{'=' * 70}\n")


def print_message_row(index: int, msg: dict) -> None:
    """Compact one-line summary per message."""
    sender = msg.get("from", {}).get("emailAddress", {})
    sender_email = sender.get("address", "?")
    subject = (msg.get("subject") or "(no subject)").strip()
    received = msg.get("receivedDateTime", "?")
    subject_trim = subject[:70] + ("..." if len(subject) > 70 else "")
    print(f"  [{index:3d}] {received}  {sender_email:<40} {subject_trim}")


async def run(top: int, dry_run: bool, quiet: bool) -> int:
    """Fetch unread messages and (optionally) mark each as read.

    Each ``mark_as_read`` call is independent — one failure does not
    block the rest of the batch. Returns 0 when every message was
    handled successfully (or when dry-run just listed them), 1 if one
    or more marks failed.
    """
    LoggingSetup.configure()
    logger = structlog.get_logger("scripts.mark_unread_mails_read")

    settings = get_settings()
    if not settings.graph_api_tenant_id or not settings.graph_api_client_id:
        print("  [ERROR] GRAPH_API_TENANT_ID / GRAPH_API_CLIENT_ID not set in .env")
        return 1

    print_header("VQMS - Mark Unread Mails Read")
    print(f"  Tenant ID: {settings.graph_api_tenant_id}")
    print(f"  Client ID: {settings.graph_api_client_id}")
    print(f"  Mailbox:   {settings.graph_api_mailbox}")
    print(f"  Limit:     top {top}")
    print(f"  Mode:      {'DRY RUN (no Graph writes)' if dry_run else 'LIVE (will flip isRead=true)'}")
    print()

    graph = GraphAPIConnector(settings)
    started = time.perf_counter()

    success_count = 0
    failure_count = 0

    try:
        # Layer 1 filter (server-side) already drops auto-replies and NDRs.
        messages = await graph.list_unread_messages(
            top=top, correlation_id="mark-unread-batch"
        )

        if not messages:
            print("  No unread messages in the Inbox.\n")
            return 0

        print_header(f"Found {len(messages)} unread message(s)")

        # If quiet, skip per-message listing. Otherwise preview them first
        # so the user can see what's about to be touched.
        if not quiet:
            for i, msg in enumerate(messages, start=1):
                print_message_row(i, msg)
            print()

        if dry_run:
            print(
                f"  [DRY RUN] Would have marked {len(messages)} "
                "message(s) as read.\n"
            )
            return 0

        print_header("Marking as read")

        # Serial, not parallel. Graph API throttles per-user at ~4 QPS;
        # a sequential loop is simplest and predictably safe.
        for i, msg in enumerate(messages, start=1):
            message_id = msg.get("id")
            if not message_id:
                logger.warning(
                    "Skipping message with no id",
                    index=i,
                )
                continue

            try:
                await graph.mark_as_read(
                    message_id, correlation_id="mark-unread-batch"
                )
                success_count += 1
                if not quiet:
                    print(f"  [OK]   [{i:3d}] {message_id[:60]}...")
            except Exception as exc:  # noqa: BLE001
                failure_count += 1
                subject = (msg.get("subject") or "(no subject)")[:60]
                print(
                    f"  [FAIL] [{i:3d}] {subject}\n"
                    f"         {type(exc).__name__}: {exc}"
                )

    finally:
        await graph.close()

    elapsed_ms = (time.perf_counter() - started) * 1000

    print_header("Summary")
    print(f"  Marked as read : {success_count}")
    print(f"  Failed         : {failure_count}")
    print(f"  Elapsed        : {elapsed_ms:.0f}ms")
    print()

    return 0 if failure_count == 0 else 1


def main() -> None:
    """Parse CLI and run."""
    parser = argparse.ArgumentParser(
        description=(
            "Read every unread email in the VQMS mailbox and mark it as "
            "read. Does not run the ingestion pipeline."
        ),
    )
    parser.add_argument(
        "--top",
        type=int,
        default=50,
        help="Maximum number of unread mails to process (default: 50).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only list what would be marked; do not write to Graph.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Skip per-message listing; show only totals.",
    )
    args = parser.parse_args()

    sys.exit(asyncio.run(run(top=args.top, dry_run=args.dry_run, quiet=args.quiet)))


if __name__ == "__main__":
    main()
