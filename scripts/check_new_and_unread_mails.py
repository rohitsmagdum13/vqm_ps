"""Script: check_new_and_unread_mails.py

Check new (recently received) and unread emails from the configured
mailbox using the Graph API connector.

Two independent sections in the output:
  1. Unread mails in Inbox (isRead == false, via list_unread_messages)
  2. New mails received in the last N hours (regardless of read status)

Usage:
    uv run python scripts/check_new_and_unread_mails.py
    uv run python scripts/check_new_and_unread_mails.py --hours 2 --top 10
    uv run python scripts/check_new_and_unread_mails.py --hours 24 --top 20
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone

import structlog

# Add src/ to Python path so imports work when run directly
sys.path.insert(0, ".")
sys.path.insert(0, "src")

from adapters.graph_api import GraphAPIConnector  # noqa: E402
from adapters.graph_api.client import GRAPH_BASE_URL  # noqa: E402
from config.settings import get_settings  # noqa: E402
from utils.logger import LoggingSetup  # noqa: E402


def print_header(text: str) -> None:
    """Print a section header."""
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}\n")


def print_message_row(index: int, msg: dict) -> None:
    """Pretty-print one message summary."""
    sender = msg.get("from", {}).get("emailAddress", {})
    sender_name = sender.get("name", "?")
    sender_email = sender.get("address", "?")
    subject = msg.get("subject", "(no subject)")
    received = msg.get("receivedDateTime", "?")
    message_id = msg.get("id", "?")
    is_read = msg.get("isRead")
    has_attachments = msg.get("hasAttachments")

    read_flag = ""
    if is_read is True:
        read_flag = "  [read]"
    elif is_read is False:
        read_flag = "  [unread]"

    att_flag = ""
    if has_attachments is True:
        att_flag = "  [has attachments]"

    print(f"  [{index}] {subject}{read_flag}{att_flag}")
    print(f"      From:     {sender_name} <{sender_email}>")
    print(f"      Received: {received}")
    print(f"      ID:       {message_id}")
    print()


async def check_unread(graph: GraphAPIConnector, top: int) -> int:
    """List unread messages in the Inbox.

    Uses the adapter's list_unread_messages(), which applies the same
    auto-reply / NDR subject filter used in production polling.

    Returns:
        Count of unread messages found.
    """
    print_header(f"Unread mails in Inbox (top {top})")

    messages = await graph.list_unread_messages(
        top=top,
        correlation_id="check-new-unread",
    )

    if not messages:
        print("  No unread messages.")
        return 0

    print(f"  Found {len(messages)} unread message(s):\n")
    for i, msg in enumerate(messages, start=1):
        print_message_row(i, msg)

    return len(messages)


async def check_recent(
    graph: GraphAPIConnector,
    mailbox: str,
    hours: int,
    top: int,
) -> int:
    """List recent mails received in the last `hours` hours.

    Hits Graph directly with a receivedDateTime filter so we can show
    BOTH read and unread recent mail (the adapter's list_unread_messages
    only returns unread).

    Returns:
        Count of recent messages found.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    cutoff_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

    print_header(f"New mails in last {hours}h (top {top})")
    print(f"  Since (UTC): {cutoff_iso}\n")

    url = f"{GRAPH_BASE_URL}/users/{mailbox}/mailFolders/Inbox/messages"
    response = await graph._request(
        "GET",
        url,
        params={
            "$filter": f"receivedDateTime ge {cutoff_iso}",
            "$top": str(top),
            "$orderby": "receivedDateTime desc",
            "$select": (
                "id,subject,from,receivedDateTime,isRead,"
                "hasAttachments,conversationId"
            ),
        },
        correlation_id="check-new-unread",
    )
    messages = response.json().get("value", [])

    if not messages:
        print("  No new messages in this window.")
        return 0

    print(f"  Found {len(messages)} message(s):\n")
    for i, msg in enumerate(messages, start=1):
        print_message_row(i, msg)

    return len(messages)


async def run(hours: int, top: int) -> None:
    """Run both checks and print a combined summary."""
    LoggingSetup.configure()
    logger = structlog.get_logger("scripts.check_new_and_unread_mails")

    settings = get_settings()

    if not settings.graph_api_tenant_id or not settings.graph_api_client_id:
        print("  [ERROR] GRAPH_API_TENANT_ID / GRAPH_API_CLIENT_ID not set in .env")
        sys.exit(1)

    print_header("VQMS - New + Unread Mail Check")
    print(f"  Tenant ID: {settings.graph_api_tenant_id}")
    print(f"  Client ID: {settings.graph_api_client_id}")
    print(f"  Mailbox:   {settings.graph_api_mailbox}")
    print(f"  Window:    last {hours} hour(s), top {top}")

    logger.info(
        "starting_mail_check",
        mailbox=settings.graph_api_mailbox,
        hours=hours,
        top=top,
    )

    graph = GraphAPIConnector(settings)

    try:
        unread_count = await check_unread(graph, top=top)
        recent_count = await check_recent(
            graph,
            mailbox=settings.graph_api_mailbox,
            hours=hours,
            top=top,
        )
    finally:
        await graph.close()

    print_header("Summary")
    print(f"  Unread in Inbox:      {unread_count}")
    print(f"  Received in last {hours}h: {recent_count}")
    print()


def main() -> None:
    """Parse CLI args and run the checks."""
    parser = argparse.ArgumentParser(
        description=(
            "Check new (recent) and unread mail from the VQMS mailbox "
            "via Microsoft Graph API."
        ),
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=1,
        help="Lookback window in hours for 'new' mail (default: 1).",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Maximum messages to fetch per section (default: 10).",
    )
    args = parser.parse_args()

    asyncio.run(run(hours=args.hours, top=args.top))


if __name__ == "__main__":
    main()
