"""Module: services/portal_submission.py

Portal Intake Service for VQMS.

Handles vendor query submissions from the VQMS web portal.
Validates input, generates IDs, checks idempotency (SHA-256 hash
of vendor_id + subject + description), writes to database,
publishes events, and enqueues to SQS for the AI pipeline.

Corresponds to Steps P1-P6 in the VQMS Solution Flow Document.

Usage:
    service = PortalIntakeService(postgres, sqs, eventbridge, settings)
    payload = await service.submit_query(submission, vendor_id="V-001")
"""

from __future__ import annotations

import hashlib

import structlog

from config.settings import Settings
from events.eventbridge import EventBridgeConnector
from queues.sqs import SQSConnector
from models.query import QuerySubmission, UnifiedQueryPayload
from utils.decorators import log_service_call
from utils.exceptions import DuplicateQueryError
from utils.helpers import IdGenerator, TimeHelper

logger = structlog.get_logger(__name__)


class PortalIntakeService:
    """Handles portal query submission and ingestion.

    Validates the submission, generates IDs, performs idempotency
    check, writes to the database, publishes events, and enqueues
    the query for the AI pipeline.
    """

    def __init__(
        self,
        postgres: object,  # PostgresConnector
        sqs: SQSConnector,
        eventbridge: EventBridgeConnector,
        settings: Settings,
    ) -> None:
        """Initialize with required connectors.

        Args:
            postgres: PostgreSQL connector for DB writes and idempotency.
            sqs: SQS connector for enqueueing to the AI pipeline.
            eventbridge: EventBridge connector for event publishing.
            settings: Application settings.
        """
        self._postgres = postgres
        self._sqs = sqs
        self._eventbridge = eventbridge
        self._settings = settings

    @log_service_call
    async def submit_query(
        self,
        submission: QuerySubmission,
        vendor_id: str,
        *,
        correlation_id: str | None = None,
    ) -> UnifiedQueryPayload:
        """Submit a vendor query from the portal.

        Args:
            submission: Validated query submission from the portal form.
            vendor_id: Vendor ID extracted from JWT claims (NOT from payload).
            correlation_id: Tracing ID. Generated if not provided.

        Returns:
            UnifiedQueryPayload with the generated query_id and all fields.

        Raises:
            DuplicateQueryError: If the same vendor+subject+description
                has already been submitted (idempotency check fails).
        """
        correlation_id = correlation_id or IdGenerator.generate_correlation_id()

        # Bind correlation_id to structlog contextvars so all downstream
        # log calls (including in connectors) automatically include it
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

        # Idempotency: SHA-256 hash of vendor_id + subject + description
        # This prevents the same vendor from submitting identical queries
        idempotency_key = hashlib.sha256(
            f"{vendor_id}:{submission.subject}:{submission.description}".encode()
        ).hexdigest()

        is_new = await self._postgres.check_idempotency(
            idempotency_key, "portal", correlation_id
        )
        if not is_new:
            raise DuplicateQueryError(
                idempotency_key, correlation_id=correlation_id
            )

        # Generate IDs
        query_id = IdGenerator.generate_query_id()
        execution_id = IdGenerator.generate_execution_id()
        now = TimeHelper.ist_now()

        # Calculate SLA deadline based on priority
        # These are default SLA hours — configurable in production
        sla_hours_by_priority = {
            "LOW": 48,
            "MEDIUM": 24,
            "HIGH": 8,
            "CRITICAL": 4,
        }
        sla_hours = sla_hours_by_priority.get(submission.priority, 24)
        sla_deadline = TimeHelper.ist_now_offset(hours=sla_hours)

        # Write case_execution record (workflow state tracking)
        await self._postgres.execute(
            """
            INSERT INTO workflow.case_execution
            (query_id, correlation_id, execution_id, vendor_id, source, status,
             created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            query_id,
            correlation_id,
            execution_id,
            vendor_id,
            "portal",
            "RECEIVED",
            now,
            now,
        )

        # Write portal query details (intake data — what the vendor submitted)
        # Separate from workflow state, same pattern as intake.email_messages
        await self._postgres.execute(
            """
            INSERT INTO intake.portal_queries
            (query_id, vendor_id, query_type, subject, description,
             priority, reference_number, sla_deadline, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            query_id,
            vendor_id,
            submission.query_type,
            submission.subject,
            submission.description,
            submission.priority,
            submission.reference_number,
            sla_deadline,
            now,
            now,
        )

        # Build the unified payload
        payload = UnifiedQueryPayload(
            query_id=query_id,
            correlation_id=correlation_id,
            execution_id=execution_id,
            source="portal",
            vendor_id=vendor_id,
            subject=submission.subject,
            body=submission.description,
            priority=submission.priority,
            received_at=now,
            thread_status="NEW",  # Portal queries are always NEW
            metadata={
                "query_type": submission.query_type,
                "reference_number": submission.reference_number,
            },
        )

        # EventBridge [NON-CRITICAL]
        try:
            await self._eventbridge.publish_event(
                "QueryReceived",
                {
                    "query_id": query_id,
                    "vendor_id": vendor_id,
                    "source": "portal",
                    "query_type": submission.query_type,
                },
                correlation_id=correlation_id,
            )
        except Exception:
            logger.warning(
                "EventBridge publish failed — continuing",
                query_id=query_id,
                correlation_id=correlation_id,
            )

        # SQS [CRITICAL]
        await self._sqs.send_message(
            self._settings.sqs_query_intake_queue_url,
            payload.model_dump(mode="json"),
            correlation_id=correlation_id,
        )

        logger.info(
            "Portal query submitted",
            query_id=query_id,
            vendor_id=vendor_id,
            query_type=submission.query_type,
            priority=submission.priority,
            correlation_id=correlation_id,
        )
        return payload
