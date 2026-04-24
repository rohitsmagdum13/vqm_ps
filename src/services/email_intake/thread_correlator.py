"""Module: services/email_intake/thread_correlator.py

Thread correlation for email conversations.

Checks if an incoming email is part of an existing thread by
looking up the conversationId in workflow.case_execution.
Returns: NEW, EXISTING_OPEN, or REPLY_TO_CLOSED.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


class ThreadCorrelator:
    """Determines thread status for incoming emails.

    Checks workflow.case_execution to see if the email's
    conversationId matches an existing case.
    """

    def __init__(self, postgres: object) -> None:
        """Initialize with PostgreSQL connector.

        Args:
            postgres: PostgresConnector for database lookups.
        """
        self._postgres = postgres

    async def determine_thread_status(
        self, raw_email: dict, correlation_id: str
    ) -> str:
        """Check if this email is part of an existing thread.

        conversation_id lives on ``intake.email_messages`` (the source
        of truth for thread identity) while workflow state lives on
        ``workflow.case_execution``. We JOIN the two by query_id and
        pick the most recently created case for this conversation.

        Returns:
            "NEW"             — no prior email in this conversation,
                                or the email has no conversationId.
            "EXISTING_OPEN"   — latest case for this conversation is
                                still in flight.
            "REPLY_TO_CLOSED" — latest case is CLOSED or RESOLVED.

        Non-critical — returns "NEW" on any DB error (logged).
        """
        conversation_id = raw_email.get("conversationId")
        if not conversation_id:
            return "NEW"

        try:
            row = await self._postgres.fetchrow(
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
            if row is None:
                return "NEW"
            status = (row.get("status") or "").upper()
            if status in ("CLOSED", "RESOLVED"):
                return "REPLY_TO_CLOSED"
            return "EXISTING_OPEN"
        except Exception:
            logger.warning(
                "Thread correlation failed — defaulting to NEW",
                conversation_id=conversation_id,
                correlation_id=correlation_id,
            )
            return "NEW"
