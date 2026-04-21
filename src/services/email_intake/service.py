"""Module: services/email_intake/service.py

Email Ingestion Service — main orchestrator.

Coordinates the 10-step email ingestion pipeline by delegating
to focused helper classes: EmailParser, AttachmentProcessor,
VendorIdentifier, ThreadCorrelator, and EmailStorage.

Corresponds to Steps E1-E2.9 in the VQMS Solution Flow Document.

Usage:
    service = EmailIntakeService(graph_api, postgres, s3, sqs, eventbridge, salesforce, settings)
    result = await service.process_email("AAMkAGI2...", correlation_id="abc-123")
"""

from __future__ import annotations

import structlog

from config.settings import Settings
from events.eventbridge import EventBridgeConnector
from adapters.graph_api import GraphAPIConnector
from storage.s3_client import S3Connector
from adapters.salesforce import SalesforceConnector
from queues.sqs import SQSConnector
from models.email import ParsedEmailPayload
from models.query import UnifiedQueryPayload
from services.email_intake.attachment_processor import AttachmentProcessor
from services.email_intake.parser import EmailParser
from services.email_intake.storage import EmailStorage
from services.email_intake.thread_correlator import ThreadCorrelator
from services.email_intake.vendor_identifier import VendorIdentifier
from utils.decorators import log_service_call
from utils.helpers import IdGenerator, TimeHelper

logger = structlog.get_logger(__name__)


class EmailIntakeError(Exception):
    """Raised when email ingestion fails at a critical step."""


class EmailIntakeService:
    """Handles the full email ingestion pipeline.

    Implements the 10-step email ingestion flow with critical
    vs non-critical step classification. Critical steps propagate
    errors (SQS retries the message). Non-critical steps log
    warnings and continue with safe defaults.

    Delegates to focused helper classes for each concern:
    - EmailParser: MIME field extraction and HTML-to-text
    - AttachmentProcessor: validation, S3 storage, text extraction
    - VendorIdentifier: Salesforce 3-step fallback lookup
    - ThreadCorrelator: conversation thread detection
    - EmailStorage: S3 raw storage and PostgreSQL metadata writes
    """

    def __init__(
        self,
        graph_api: GraphAPIConnector,
        postgres: object,  # PostgresConnector (typed as object to avoid circular import)
        s3: S3Connector,
        sqs: SQSConnector,
        eventbridge: EventBridgeConnector,
        salesforce: SalesforceConnector,
        settings: Settings,
        closure_service: object | None = None,
    ) -> None:
        """Initialize with all required connectors.

        Args:
            graph_api: Microsoft Graph API connector for email fetch.
            postgres: PostgreSQL connector for metadata and idempotency.
            s3: S3 connector for raw email and attachment storage.
            sqs: SQS connector for enqueueing to the AI pipeline.
            eventbridge: EventBridge connector for event publishing.
            salesforce: Salesforce connector for vendor identification.
            settings: Application settings.
            closure_service: Optional Phase 6 ClosureService. When present,
                replies on EXISTING_OPEN / REPLY_TO_CLOSED threads are run
                through confirmation keyword matching and reopen handling.
        """
        self._graph_api = graph_api
        self._postgres = postgres
        self._sqs = sqs
        self._eventbridge = eventbridge
        self._settings = settings
        self._closure_service = closure_service

        # Compose helper classes
        self._attachment_processor = AttachmentProcessor(s3, settings)
        self._vendor_identifier = VendorIdentifier(salesforce)
        self._thread_correlator = ThreadCorrelator(postgres)
        self._storage = EmailStorage(postgres, s3, settings)

    @log_service_call
    async def process_email(
        self,
        message_id: str,
        *,
        correlation_id: str | None = None,
    ) -> ParsedEmailPayload | None:
        """Process a single email through the full ingestion pipeline.

        This is the main entry point. It handles the 10-step flow:
        E2.1 Idempotency check, E1 Fetch email, E2.2 Parse fields,
        E2.7 Generate IDs, E2.3 Store raw in S3, E2.4 Process attachments,
        E2.5 Vendor identification, E2.6 Thread correlation,
        E2.8 Write to DB, E2.9a EventBridge, E2.9b SQS enqueue.

        Args:
            message_id: Exchange Online message ID to process.
            correlation_id: Tracing ID. Generated if not provided.

        Returns:
            ParsedEmailPayload with all extracted fields, or None
            if the email was a duplicate (already processed).

        Raises:
            EmailIntakeError: If a critical step fails.
        """
        correlation_id = correlation_id or IdGenerator.generate_correlation_id()

        # Bind correlation_id to structlog contextvars so all downstream
        # log calls (including in connectors) automatically include it
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

        # E2.1 [CRITICAL] Idempotency check — prevent duplicate processing
        is_new = await self._postgres.check_idempotency(
            message_id, "email", correlation_id
        )
        if not is_new:
            logger.info(
                "Duplicate email skipped",
                message_id=message_id,
                correlation_id=correlation_id,
            )
            return None

        # E1 [CRITICAL] Fetch email from Graph API
        raw_email = await self._graph_api.fetch_email(
            message_id, correlation_id=correlation_id
        )

        # E2.2 [CRITICAL] Parse email fields
        parsed = EmailParser.parse_email_fields(raw_email)

        # E2.7 [CRITICAL] Generate IDs
        query_id = IdGenerator.generate_query_id()
        execution_id = IdGenerator.generate_execution_id()
        now = TimeHelper.ist_now()

        # E2.3 [NON-CRITICAL] Store raw email in S3
        s3_raw_key = await self._storage.store_raw_email(
            raw_email, query_id, correlation_id
        )

        # E2.4 [NON-CRITICAL] Process attachments
        attachments = await self._attachment_processor.process_attachments(
            raw_email, query_id, correlation_id
        )

        # E2.5 [NON-CRITICAL] Vendor identification via Salesforce
        vendor_id, vendor_match_method = await self._vendor_identifier.identify_vendor(
            parsed, correlation_id
        )

        # E2.6 [NON-CRITICAL] Thread correlation
        thread_status = await self._thread_correlator.determine_thread_status(
            raw_email, correlation_id
        )

        # E2.8 [CRITICAL] Write metadata to database
        await self._storage.store_email_metadata(
            message_id=message_id,
            query_id=query_id,
            correlation_id=correlation_id,
            parsed=parsed,
            s3_raw_key=s3_raw_key,
            vendor_id=vendor_id,
            vendor_match_method=vendor_match_method,
            thread_status=thread_status,
            now=now,
        )
        # Write attachment metadata to intake.email_attachments
        # Must happen AFTER email_messages INSERT because of the foreign key
        await self._storage.store_attachment_metadata(
            message_id=message_id,
            query_id=query_id,
            attachments=attachments,
            correlation_id=correlation_id,
        )
        await self._storage.create_case_execution(
            query_id=query_id,
            correlation_id=correlation_id,
            execution_id=execution_id,
            vendor_id=vendor_id,
            now=now,
        )

        # E2.9a [NON-CRITICAL] Publish EventBridge event
        try:
            await self._eventbridge.publish_event(
                "EmailParsed",
                {
                    "query_id": query_id,
                    "message_id": message_id,
                    "sender_email": parsed["sender_email"],
                    "vendor_id": vendor_id,
                },
                correlation_id=correlation_id,
            )
        except Exception:
            logger.warning(
                "EventBridge publish failed — continuing",
                query_id=query_id,
                correlation_id=correlation_id,
            )

        # E2.9b [CRITICAL] Enqueue to SQS for AI pipeline
        body_text = parsed.get("body_text", "") or parsed.get("body_preview", "")
        payload = UnifiedQueryPayload(
            query_id=query_id,
            correlation_id=correlation_id,
            execution_id=execution_id,
            source="email",
            vendor_id=vendor_id,
            subject=parsed["subject"],
            body=body_text,
            priority="MEDIUM",  # Default; Query Analysis Agent sets final priority
            received_at=now,
            attachments=attachments,
            thread_status=thread_status,
            metadata={
                "message_id": message_id,
                "sender_email": parsed["sender_email"],
                "sender_name": parsed.get("sender_name"),
                "vendor_match_method": vendor_match_method,
                "conversation_id": parsed.get("conversation_id"),
            },
        )
        await self._sqs.send_message(
            self._settings.sqs_email_intake_queue_url,
            payload.model_dump(mode="json"),
            correlation_id=correlation_id,
        )

        # Phase 6 closure / reopen detection — non-critical.
        # A reply landing on an existing thread may be a vendor confirmation
        # (closes the prior case) or a reopen (inside-window: flip back to
        # AWAITING_RESOLUTION; outside-window: link new case to prior).
        if (
            self._closure_service is not None
            and thread_status in ("EXISTING_OPEN", "REPLY_TO_CLOSED")
        ):
            await self._run_closure_detection(
                thread_status=thread_status,
                conversation_id=parsed.get("conversation_id"),
                body_text=body_text,
                new_query_id=query_id,
                correlation_id=correlation_id,
            )

        # Build the full parsed payload for the return value
        result = ParsedEmailPayload(
            message_id=message_id,
            correlation_id=correlation_id,
            query_id=query_id,
            sender_email=parsed["sender_email"],
            sender_name=parsed.get("sender_name"),
            recipients=parsed.get("recipients", []),
            subject=parsed["subject"],
            body_text=body_text,
            body_html=parsed.get("body_html"),
            received_at=now,
            parsed_at=TimeHelper.ist_now(),
            in_reply_to=parsed.get("in_reply_to"),
            references=parsed.get("references", []),
            conversation_id=parsed.get("conversation_id"),
            thread_status=thread_status,
            vendor_id=vendor_id,
            vendor_match_method=vendor_match_method,
            attachments=attachments,
            s3_raw_email_key=s3_raw_key,
        )

        logger.info(
            "Email processed successfully",
            query_id=query_id,
            message_id=message_id,
            vendor_id=vendor_id,
            thread_status=thread_status,
            attachment_count=len(attachments),
            correlation_id=correlation_id,
        )
        return result

    async def _run_closure_detection(
        self,
        *,
        thread_status: str,
        conversation_id: str | None,
        body_text: str,
        new_query_id: str,
        correlation_id: str,
    ) -> None:
        """Hand off confirmation / reopen decisions to ClosureService.

        Non-critical: any failure is logged and swallowed so a broken
        closure path cannot roll back successful email ingestion.
        """
        try:
            was_confirmation = await self._closure_service.detect_confirmation(
                conversation_id=conversation_id,
                body_text=body_text,
                correlation_id=correlation_id,
            )
        except Exception:
            logger.warning(
                "Confirmation detection failed — continuing",
                new_query_id=new_query_id,
                correlation_id=correlation_id,
            )
            was_confirmation = False

        if thread_status == "REPLY_TO_CLOSED" and not was_confirmation:
            try:
                await self._closure_service.handle_reopen(
                    conversation_id=conversation_id,
                    new_query_id=new_query_id,
                    correlation_id=correlation_id,
                )
            except Exception:
                logger.warning(
                    "Reopen handling failed — continuing",
                    new_query_id=new_query_id,
                    correlation_id=correlation_id,
                )
