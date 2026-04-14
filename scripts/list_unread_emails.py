"""Script: list_unread_emails.py

List unread emails from the configured mailbox using real Graph API credentials.

Usage:
    uv run python scripts/list_unread_emails.py
    uv run python scripts/list_unread_emails.py --top 10

This is a quick utility to see what's in the inbox before running
the full email ingestion test. No database or AWS services needed —
only Graph API credentials in .env.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

# Add src/ to Python path so imports work
sys.path.insert(0, ".")
sys.path.insert(0, "src")

from config.settings import get_settings  # noqa: E402
from adapters.graph_api import GraphAPIConnector  # noqa: E402
from utils.logger import LoggingSetup  # noqa: E402


async def list_unread(top: int = 5) -> None:
    """Fetch and display unread emails from the configured mailbox."""
    LoggingSetup.configure()
    logger = logging.getLogger("scripts.list_unread")

    settings = get_settings()
    logger.info(
        "Connecting to Graph API for mailbox: %s",
        settings.graph_api_mailbox,
    )

    graph_api = GraphAPIConnector(settings)

    try:
        messages = await graph_api.list_unread_messages(top=top)

        if not messages:
            print("\n--- No unread emails found ---\n")
            return

        print(f"\n--- {len(messages)} Unread Email(s) ---\n")

        for i, msg in enumerate(messages, start=1):
            sender = msg.get("from", {}).get("emailAddress", {})
            sender_email = sender.get("address", "N/A")
            sender_name = sender.get("name", "N/A")
            subject = msg.get("subject", "(no subject)")
            message_id = msg.get("id", "N/A")
            received = msg.get("receivedDateTime", "N/A")
            has_attachments = msg.get("hasAttachments", False)
            conversation_id = msg.get("conversationId", "N/A")

            print(f"  [{i}] Message ID: {message_id}")
            print(f"      From:        {sender_name} <{sender_email}>")
            print(f"      Subject:     {subject}")
            print(f"      Received:    {received}")
            print(f"      Attachments: {'Yes' if has_attachments else 'No'}")
            print(f"      Conv ID:     {conversation_id}")
            print()

        print("--- Copy a Message ID above to use with test_email_ingestion.py ---\n")

    except Exception:
        logger.exception("Failed to list unread emails")
        raise
    finally:
        await graph_api.close()


def main() -> None:
    """Parse args and run."""
    parser = argparse.ArgumentParser(description="List unread emails from the VQMS mailbox")
    parser.add_argument("--top", type=int, default=5, help="Number of emails to fetch (default: 5)")
    args = parser.parse_args()

    asyncio.run(list_unread(top=args.top))


if __name__ == "__main__":
    main()
