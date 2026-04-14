"""Module: services/polling.py

Reconciliation Poller for VQMS.

Polls the shared mailbox every 5 minutes via Microsoft Graph API
to catch any emails that the webhook might have missed. This is
Layer 1 of the defense-in-depth strategy (dual detection).

Each email found goes through the same process_email pipeline,
which includes idempotency check — so duplicates (already
processed via webhook) are silently skipped.

Usage:
    poller = ReconciliationPoller(email_intake, graph_api, settings)
    count = await poller.poll_once()  # Process unread emails
    await poller.start_polling_loop()  # Run continuously
"""

from __future__ import annotations

import asyncio

import structlog

from config.settings import Settings
from adapters.graph_api import GraphAPIConnector
from services.email_intake import EmailIntakeService
from utils.decorators import log_service_call
from utils.helpers import IdGenerator

logger = structlog.get_logger(__name__)


class ReconciliationPoller:
    """Polls the shared mailbox for unread emails.

    Runs as a background task, calling list_unread_messages every
    poll_interval seconds. Each unread message is passed to
    EmailIntakeService.process_email, which handles idempotency.
    """

    def __init__(
        self,
        email_intake: EmailIntakeService,
        graph_api: GraphAPIConnector,
        settings: Settings,
    ) -> None:
        """Initialize with required services and settings.

        Args:
            email_intake: The email intake service for processing.
            graph_api: Graph API connector for listing unread messages.
            settings: Application settings (poll interval).
        """
        self._email_intake = email_intake
        self._graph_api = graph_api
        self._poll_interval = settings.graph_api_poll_interval_seconds
        self._running = False

    @log_service_call
    async def poll_once(
        self,
        *,
        correlation_id: str | None = None,
    ) -> int:
        """Fetch unread messages and process each one.

        Errors on individual messages are logged and skipped —
        the poller continues to the next message. Duplicates
        (already processed via webhook) return None from
        process_email, which is expected and counted separately.

        Args:
            correlation_id: Tracing ID for this poll cycle.

        Returns:
            Count of newly processed emails (excludes duplicates).
        """
        correlation_id = correlation_id or IdGenerator.generate_correlation_id()
        processed_count = 0

        try:
            unread_messages = await self._graph_api.list_unread_messages(
                top=50, correlation_id=correlation_id
            )
        except Exception:
            logger.exception(
                "Failed to list unread messages",
                correlation_id=correlation_id,
            )
            return 0

        logger.info(
            "Poller found unread messages",
            unread_count=len(unread_messages),
            correlation_id=correlation_id,
        )

        for message in unread_messages:
            message_id = message.get("id")
            if not message_id:
                continue

            try:
                result = await self._email_intake.process_email(
                    message_id, correlation_id=correlation_id
                )
                if result is not None:
                    processed_count += 1
                # result is None for duplicates — expected and silent
            except Exception:
                # Log and continue to next message — don't let one
                # bad email block the entire polling cycle
                logger.warning(
                    "Poller failed to process message — skipping",
                    message_id=message_id,
                    correlation_id=correlation_id,
                )

        logger.info(
            "Poller cycle complete",
            processed_count=processed_count,
            total_unread=len(unread_messages),
            correlation_id=correlation_id,
        )
        return processed_count

    async def start_polling_loop(self) -> None:
        """Run the polling loop continuously.

        Polls every poll_interval seconds until stop() is called.
        Each cycle is independent — errors don't stop the loop.
        """
        self._running = True
        logger.info(
            "Reconciliation poller started",
            interval_seconds=self._poll_interval,
        )

        while self._running:
            await self.poll_once()
            await asyncio.sleep(self._poll_interval)

        logger.info("Reconciliation poller stopped")

    def stop(self) -> None:
        """Signal the polling loop to stop after the current cycle."""
        self._running = False
