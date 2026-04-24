"""Script: check_thread_correlation.py

Verify the thread-correlation JOIN against live RDS.

Runs the same SQL that ``ThreadCorrelator.determine_thread_status`` now
uses, against a conversation_id taken from the most recent email we
ingested. Before the fix this returned nothing (and the bare except
swallowed an UndefinedColumnError); after the fix it should return the
latest case row.

Usage:
    uv run python scripts/check_thread_correlation.py
    uv run python scripts/check_thread_correlation.py --conversation-id <id>
"""

from __future__ import annotations

import argparse
import asyncio
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "src")

from config.settings import get_settings  # noqa: E402
from db.connection import PostgresConnector  # noqa: E402
from utils.logger import LoggingSetup  # noqa: E402


def header(text: str) -> None:
    print(f"\n{'=' * 70}\n  {text}\n{'=' * 70}")


async def run(conversation_id: str | None) -> int:
    LoggingSetup.configure()
    postgres = PostgresConnector(get_settings())
    await postgres.connect()

    try:
        if not conversation_id:
            header("Picking most recent email with a conversation_id")
            row = await postgres.fetchrow(
                """
                SELECT conversation_id, query_id, subject
                  FROM intake.email_messages
                 WHERE conversation_id IS NOT NULL
                 ORDER BY received_at DESC
                 LIMIT 1
                """
            )
            if row is None:
                print("  No emails with conversation_id in DB. Run the e2e script first.")
                return 1
            conversation_id = row["conversation_id"]
            print(f"  Found query_id={row['query_id']}")
            print(f"  Subject:         {row['subject'][:70]}")
            print(f"  Conversation ID: {conversation_id}")

        header("Running the new JOIN query")
        print("  SQL:")
        print(
            "    SELECT ce.query_id, ce.status\n"
            "      FROM workflow.case_execution ce\n"
            "      JOIN intake.email_messages em\n"
            "        ON em.query_id = ce.query_id\n"
            "     WHERE em.conversation_id = $1\n"
            "     ORDER BY ce.created_at DESC LIMIT 1"
        )
        row = await postgres.fetchrow(
            """
            SELECT ce.query_id, ce.status
              FROM workflow.case_execution ce
              JOIN intake.email_messages em
                ON em.query_id = ce.query_id
             WHERE em.conversation_id = $1
             ORDER BY ce.created_at DESC
             LIMIT 1
            """,
            conversation_id,
        )

        header("Result")
        if row is None:
            print("  No matching case — thread_status would be NEW")
            return 0
        query_id = row["query_id"]
        status = (row.get("status") or "").upper()
        predicted_thread_status = (
            "REPLY_TO_CLOSED"
            if status in ("CLOSED", "RESOLVED")
            else "EXISTING_OPEN"
        )
        print(f"  query_id:             {query_id}")
        print(f"  case status:          {status}")
        print(f"  thread_status result: {predicted_thread_status}")
        print()
        print(
            "  [OK] JOIN works against live DB — thread correlation is "
            "now actually functional."
        )
        return 0
    finally:
        await postgres.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify the thread-correlation JOIN against live RDS."
    )
    parser.add_argument(
        "--conversation-id",
        default=None,
        help="Conversation ID to probe (default: most recent in DB).",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.conversation_id)))


if __name__ == "__main__":
    main()
