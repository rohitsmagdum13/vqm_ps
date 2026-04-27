"""Module: services/portal_intake/service.py

PortalIntakeService — orchestrates portal query submission with attachments.

Replaces the older standalone services/portal_submission.py. The flow is:
  1. Idempotency check (SHA-256 of vendor + subject + description + filenames)
  2. Generate IDs and SLA deadline
  3. Persist case_execution + portal_queries rows
  4. Process attachments (S3 upload + Textract/library text extraction)
  5. LLM entity extraction → JSON
  6. Update portal_queries.extracted_entities (JSONB)
  7. Publish QueryReceived event + enqueue UnifiedQueryPayload to SQS
  8. Append the 'intake / portal_submitted' audit row

Each external write is best-effort or idempotent so a partial failure
never leaves the system in an unrecoverable state.
"""

from __future__ import annotations

import hashlib
import json

import structlog
from fastapi import UploadFile

from config.settings import Settings
from events.eventbridge import EventBridgeConnector
from models.query import (
    ExtractedEntities,
    QueryAttachment,
    QuerySubmission,
    UnifiedQueryPayload,
)
from queues.sqs import SQSConnector
from services.portal_intake.attachment_processor import PortalAttachmentProcessor
from services.portal_intake.entity_extractor import EntityExtractor
from services.portal_intake.text_extractor import TextExtractor
from utils.decorators import log_service_call
from utils.exceptions import DuplicateQueryError
from utils.helpers import IdGenerator, TimeHelper
from utils.trail import record_node

logger = structlog.get_logger(__name__)

# Default SLA window per priority — matches the legacy portal_submission
# service. These are configurable in production.
_SLA_HOURS_BY_PRIORITY: dict[str, int] = {
    "LOW": 48,
    "MEDIUM": 24,
    "HIGH": 8,
    "CRITICAL": 4,
}


class PortalIntakeService:
    """Handles portal query submission, attachment processing, and entity extraction."""

    def __init__(
        self,
        postgres: object,  # PostgresConnector
        sqs: SQSConnector,
        eventbridge: EventBridgeConnector,
        settings: Settings,
        *,
        s3: object | None = None,  # S3Connector — None disables attachments
        llm_gateway: object | None = None,
        textract: object | None = None,
    ) -> None:
        """Initialize with all connectors needed for the full pipeline.

        Args:
            postgres: PostgreSQL connector.
            sqs: SQS connector for the AI pipeline queue.
            eventbridge: EventBridge connector for the QueryReceived event.
            s3: S3 connector for attachment storage. May be None — when
                None, attachments cannot be uploaded so they are recorded
                with extraction_status='failed'.
            llm_gateway: LLM gateway for entity extraction. May be None —
                when None, ExtractedEntities is returned empty.
            textract: Optional Textract connector. When None, PDFs go
                straight to pdfplumber.
            settings: Application settings.
        """
        self._postgres = postgres
        self._sqs = sqs
        self._eventbridge = eventbridge
        self._s3 = s3
        self._settings = settings

        self._attachment_processor: PortalAttachmentProcessor | None = None
        if s3 is not None:
            self._attachment_processor = PortalAttachmentProcessor(
                s3=s3,
                text_extractor=TextExtractor(textract),
                postgres=postgres,
                settings=settings,
            )

        self._entity_extractor: EntityExtractor | None = None
        if llm_gateway is not None:
            self._entity_extractor = EntityExtractor(llm_gateway)

    @log_service_call
    async def submit_query(
        self,
        submission: QuerySubmission,
        vendor_id: str,
        *,
        files: list[UploadFile] | None = None,
        correlation_id: str | None = None,
    ) -> UnifiedQueryPayload:
        """Submit a vendor query, optionally with file attachments.

        Args:
            submission: Validated query submission from the portal form.
            vendor_id: Vendor ID extracted from JWT claims (NOT from payload).
            files: Optional list of FastAPI UploadFile objects (0..N).
            correlation_id: Tracing ID. Generated if not provided.

        Returns:
            UnifiedQueryPayload including attachments and extracted entities.

        Raises:
            DuplicateQueryError: If the same vendor + subject + description
                + filename set has already been submitted.
        """
        files = files or []
        correlation_id = correlation_id or IdGenerator.generate_correlation_id()

        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

        idempotency_key = self._build_idempotency_key(submission, vendor_id, files)

        is_new = await self._postgres.check_idempotency(
            idempotency_key, "portal", correlation_id
        )
        if not is_new:
            raise DuplicateQueryError(
                idempotency_key, correlation_id=correlation_id
            )

        query_id = IdGenerator.generate_query_id()
        execution_id = IdGenerator.generate_execution_id()
        now = TimeHelper.ist_now()
        sla_hours = _SLA_HOURS_BY_PRIORITY.get(submission.priority, 24)
        sla_deadline = TimeHelper.ist_now_offset(hours=sla_hours)

        await self._insert_case_execution(
            query_id=query_id,
            correlation_id=correlation_id,
            execution_id=execution_id,
            vendor_id=vendor_id,
            now=now,
        )
        await self._insert_portal_query(
            query_id=query_id,
            vendor_id=vendor_id,
            submission=submission,
            sla_deadline=sla_deadline,
            now=now,
        )

        attachments = await self._process_attachments(query_id, files, correlation_id)

        entities = await self._extract_entities(submission, attachments, correlation_id)

        await self._persist_entities(query_id, entities, correlation_id)

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
            attachments=attachments,
            thread_status="NEW",
            metadata={
                "query_type": submission.query_type,
                "reference_number": submission.reference_number,
                "extracted_entities": entities.model_dump(),
            },
        )

        await self._publish_event(query_id, vendor_id, submission, attachments, entities, correlation_id)
        await self._enqueue_payload(payload, query_id, correlation_id)

        logger.info(
            "Portal query submitted",
            query_id=query_id,
            vendor_id=vendor_id,
            query_type=submission.query_type,
            priority=submission.priority,
            attachment_count=len(attachments),
            entity_summary_present=bool(entities.summary),
            correlation_id=correlation_id,
        )

        await record_node(
            query_id=query_id,
            correlation_id=correlation_id,
            step_name="intake",
            action="portal_submitted",
            status="success",
            details={
                "source": "portal",
                "vendor_id": vendor_id,
                "query_type": submission.query_type,
                "priority": submission.priority,
                "sla_hours": sla_hours,
                "attachment_count": len(attachments),
                "extraction_methods": [a.extraction_method for a in attachments],
            },
        )
        return payload

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_idempotency_key(
        submission: QuerySubmission,
        vendor_id: str,
        files: list[UploadFile],
    ) -> str:
        """SHA-256 over vendor + subject + description + sorted filenames.

        Filenames are folded in so re-submitting an identical text but
        with a new attachment is treated as a new query, which matches
        what a vendor expects.
        """
        filenames = sorted(f.filename or "" for f in files)
        raw = (
            f"{vendor_id}:{submission.subject}:{submission.description}"
            f":{'|'.join(filenames)}"
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    async def _insert_case_execution(
        self,
        *,
        query_id: str,
        correlation_id: str,
        execution_id: str,
        vendor_id: str,
        now,
    ) -> None:
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

    async def _insert_portal_query(
        self,
        *,
        query_id: str,
        vendor_id: str,
        submission: QuerySubmission,
        sla_deadline,
        now,
    ) -> None:
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

    async def _process_attachments(
        self,
        query_id: str,
        files: list[UploadFile],
        correlation_id: str,
    ) -> list[QueryAttachment]:
        """Run the attachment processor when both files and S3 are available."""
        if not files:
            return []
        if self._attachment_processor is None:
            logger.warning(
                "Files uploaded but S3 connector is unavailable — skipping",
                correlation_id=correlation_id,
            )
            return []
        return await self._attachment_processor.process(
            files, query_id, correlation_id
        )

    async def _extract_entities(
        self,
        submission: QuerySubmission,
        attachments: list[QueryAttachment],
        correlation_id: str,
    ) -> ExtractedEntities:
        """Run the LLM entity-extraction call when the gateway is available."""
        if self._entity_extractor is None:
            return ExtractedEntities()
        return await self._entity_extractor.extract(
            submission, attachments, correlation_id
        )

    async def _persist_entities(
        self,
        query_id: str,
        entities: ExtractedEntities,
        correlation_id: str,
    ) -> None:
        """Write the extracted JSON back onto intake.portal_queries. Best-effort."""
        try:
            await self._postgres.execute(
                """
                UPDATE intake.portal_queries
                SET extracted_entities = $1::jsonb, updated_at = NOW()
                WHERE query_id = $2
                """,
                json.dumps(entities.model_dump()),
                query_id,
            )
        except Exception:
            logger.warning(
                "Failed to persist extracted_entities — continuing",
                query_id=query_id,
                correlation_id=correlation_id,
            )

    async def _publish_event(
        self,
        query_id: str,
        vendor_id: str,
        submission: QuerySubmission,
        attachments: list[QueryAttachment],
        entities: ExtractedEntities,
        correlation_id: str,
    ) -> None:
        try:
            await self._eventbridge.publish_event(
                "QueryReceived",
                {
                    "query_id": query_id,
                    "vendor_id": vendor_id,
                    "source": "portal",
                    "query_type": submission.query_type,
                    "attachment_count": len(attachments),
                    "has_entities": bool(entities.summary)
                    or any(
                        getattr(entities, field)
                        for field in (
                            "invoice_numbers",
                            "po_numbers",
                            "amounts",
                            "dates",
                        )
                    ),
                },
                correlation_id=correlation_id,
            )
        except Exception:
            logger.warning(
                "EventBridge publish failed — continuing",
                query_id=query_id,
                correlation_id=correlation_id,
            )

    async def _enqueue_payload(
        self,
        payload: UnifiedQueryPayload,
        query_id: str,
        correlation_id: str,
    ) -> None:
        try:
            await self._sqs.send_message(
                self._settings.sqs_query_intake_queue_url,
                payload.model_dump(mode="json"),
                correlation_id=correlation_id,
            )
        except Exception:
            logger.warning(
                "SQS enqueue failed — query persisted, AI pipeline will not pick it up automatically",
                query_id=query_id,
                correlation_id=correlation_id,
            )
