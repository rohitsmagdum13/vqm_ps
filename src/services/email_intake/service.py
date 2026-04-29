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
from adapters.bedrock import BedrockConnector
from adapters.graph_api import GraphAPIConnector
from storage.s3_client import S3Connector
from adapters.salesforce import SalesforceConnector
from queues.sqs import SQSConnector
from models.email import ParsedEmailPayload, RelevanceDecision
from models.query import UnifiedQueryPayload
from services.email_intake.attachment_processor import AttachmentProcessor
from services.email_intake.parser import EmailParser
from services.email_intake.relevance_filter import EmailRelevanceFilter
from services.email_intake.storage import EmailStorage
from services.email_intake.thread_correlator import ThreadCorrelator
from services.email_intake.vendor_identifier import VendorIdentifier
from utils.decorators import log_service_call
from utils.helpers import IdGenerator, TimeHelper
from utils.log_types import LOG_TYPE_SERVICE
from utils.trail import record_node

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
        bedrock: BedrockConnector | None = None,
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
            bedrock: Optional BedrockConnector used by the relevance
                filter's Layer 4 classifier. Required only when
                ``email_filter_use_llm_classifier`` is true.
        """
        self._graph_api = graph_api
        self._postgres = postgres
        self._sqs = sqs
        self._eventbridge = eventbridge
        self._settings = settings
        self._closure_service = closure_service

        # Compose helper classes
        self._attachment_processor = AttachmentProcessor(s3, settings, graph_api)
        self._vendor_identifier = VendorIdentifier(salesforce)
        self._thread_correlator = ThreadCorrelator(postgres)
        self._storage = EmailStorage(postgres, s3, settings)
        self._relevance_filter = EmailRelevanceFilter(settings, bedrock)

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

        # E2.1 [CRITICAL] Idempotency claim — claim-check pattern.
        # Returns True only when this worker newly holds a PROCESSING
        # claim (either inserted or reclaimed a stale one). Any error
        # before mark_idempotency_complete releases the claim so the
        # next attempt can retry — no more silent email loss if Graph
        # or SQS blips after the claim was written.
        claimed = await self._postgres.check_idempotency(
            message_id, "email", correlation_id
        )
        if not claimed:
            logger.info(
                "Duplicate email skipped",
                log_type=LOG_TYPE_SERVICE,
                message_id=message_id,
                correlation_id=correlation_id,
            )
            # A duplicate or in-flight claim still needs to leave the
            # poller's unread view. Safe on both COMPLETED rows (mark
            # is a no-op at the Graph side for already-read mail) and
            # on in-flight ones (the active worker will also mark it).
            await self._mark_read_safe(message_id, correlation_id)
            return None

        # Everything between here and mark_idempotency_complete runs
        # inside a try/except that releases the claim on failure.
        try:
            return await self._run_claimed_pipeline(
                message_id=message_id,
                correlation_id=correlation_id,
            )
        except Exception:
            # Free the claim immediately so the next poll cycle
            # reattempts instead of waiting for the 10-minute TTL.
            await self._postgres.release_idempotency_claim(
                message_id, correlation_id
            )
            raise

    async def _run_claimed_pipeline(
        self,
        *,
        message_id: str,
        correlation_id: str,
    ) -> ParsedEmailPayload | None:
        """Run the full pipeline under an already-acquired idempotency claim.

        Split from ``process_email`` so the try/except around the claim
        stays shallow and readable. Every exit path either marks the
        claim COMPLETED (success) or raises — the outer catch in
        ``process_email`` releases the claim on raise.
        """
        # E1 [CRITICAL] Fetch email from Graph API
        raw_email = await self._graph_api.fetch_email(
            message_id, correlation_id=correlation_id
        )

        # E2.2 [CRITICAL] Parse email fields
        parsed = EmailParser.parse_email_fields(raw_email)

        # E2.5 [NON-CRITICAL] Vendor identification (moved up so the
        # relevance filter can reject unknown senders before we spend
        # cycles on storage, attachments, or Bedrock).
        vendor_id, vendor_match_method = await self._vendor_identifier.identify_vendor(
            parsed, correlation_id
        )

        # E2.1b [CRITICAL] Relevance filter — drop noise (hello-only emails,
        # auto-replies, newsletters, unknown senders) before we write any
        # artifacts or enqueue to the AI pipeline.
        decision = await self._relevance_filter.evaluate(
            parsed=parsed,
            raw_email=raw_email,
            vendor_id=vendor_id,
            vendor_match_method=vendor_match_method,
            correlation_id=correlation_id,
        )
        if not decision.accept:
            await self._handle_rejected_email(
                decision=decision,
                parsed=parsed,
                message_id=message_id,
                correlation_id=correlation_id,
            )
            # Rejected mail is a legitimate terminal state: nothing will
            # re-process it. Mark the claim COMPLETED so the key stays as
            # a permanent duplicate guard, then mark the Outlook mail read
            # so the poller doesn't re-evaluate it on every cycle.
            await self._postgres.mark_idempotency_complete(
                message_id, correlation_id
            )
            await self._mark_read_safe(message_id, correlation_id)
            return None

        # E2.7 [CRITICAL] Generate IDs
        query_id = IdGenerator.generate_query_id()
        execution_id = IdGenerator.generate_execution_id()
        now = TimeHelper.ist_now()

        # E2.3 [NON-CRITICAL] Store raw email in S3
        s3_raw_key = await self._storage.store_raw_email(
            raw_email, query_id, correlation_id
        )

        # E2.4 [NON-CRITICAL] Process attachments (passes message_id so the
        # processor can fall back to /$value download for large files that
        # Graph doesn't inline).
        attachments = await self._attachment_processor.process_attachments(
            raw_email, query_id, correlation_id, message_id=message_id
        )

        # E2.6 [NON-CRITICAL] Thread correlation
        thread_status = await self._thread_correlator.determine_thread_status(
            raw_email, correlation_id
        )

        # Build the SQS payload up front so we can hand it to both the
        # outbox INSERT and the immediate publish attempt without
        # rebuilding it.
        body_text = parsed.get("body_text", "") or parsed.get("body_preview", "")

        # Carry forward the original recipient lists so the Delivery node
        # can reply-all (vendor + everyone they CC'd). BCC is intentionally
        # not propagated — Microsoft Graph does not return bccRecipients
        # on inbound mail (BCC is stripped by the sender's mail server
        # before delivery to non-BCC'd recipients), so there is nothing
        # to replicate. Drop our own mailbox out of to_recipients so the
        # reply does not loop back to vendor-support@.
        own_mailbox = (self._settings.graph_api_mailbox or "").lower()
        cc_emails = [
            r["email"] for r in parsed.get("cc_recipients", [])
            if r.get("email") and r["email"].lower() != own_mailbox
        ]
        extra_to_emails = [
            r["email"] for r in parsed.get("to_recipients", [])
            if r.get("email") and r["email"].lower() != own_mailbox
        ]

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
                "cc_emails": cc_emails,
                "extra_to_emails": extra_to_emails,
            },
        )
        payload_json = payload.model_dump(mode="json")
        queue_url = self._settings.sqs_email_intake_queue_url

        # E2.8 [CRITICAL] Atomic DB write: email_messages + attachments +
        # case_execution + outbox row in one transaction. Either all four
        # commit or none does — no more orphaned case_execution rows when
        # SQS is down.
        await self._storage.persist_email_atomically(
            message_id=message_id,
            query_id=query_id,
            execution_id=execution_id,
            correlation_id=correlation_id,
            parsed=parsed,
            s3_raw_key=s3_raw_key,
            vendor_id=vendor_id,
            vendor_match_method=vendor_match_method,
            thread_status=thread_status,
            attachments=attachments,
            now=now,
            outbox_queue_url=queue_url,
            outbox_payload=payload_json,
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

        # E2.9b Immediate publish attempt. Outbox already holds the
        # payload, so a failure here is recoverable: the reconciliation
        # poller's drain pass will retry it. We mark the claim COMPLETED
        # regardless — the email is durably persisted, so re-processing
        # it would only produce a duplicate case_execution.
        await self._publish_from_outbox(
            event_key=query_id,
            queue_url=queue_url,
            payload=payload_json,
            correlation_id=correlation_id,
        )

        # Happy path: the message is durably in the system. Flip the
        # idempotency claim to COMPLETED so it becomes a permanent
        # duplicate guard.
        await self._postgres.mark_idempotency_complete(
            message_id, correlation_id
        )

        # Mark the Outlook mail read last — if this fails the poller will
        # see the email again, but check_idempotency will skip it.
        await self._mark_read_safe(message_id, correlation_id)

        # Phase 6 closure / reopen / follow-up detection — non-critical.
        # A reply landing on an existing thread may be:
        #   - a vendor confirmation (closes the prior case),
        #   - a reopen of a closed case (inside-window: flip back to
        #     AWAITING_RESOLUTION; outside-window: link new case to prior),
        #   - a follow-up with missing info on a still-open case (merge
        #     into prior — no duplicate ticket / duplicate LLM run).
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
                attachments=attachments,
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

        # Audit row — first entry on the query's pipeline timeline.
        await record_node(
            query_id=query_id,
            correlation_id=correlation_id,
            step_name="intake",
            action="email_processed",
            status="success",
            details={
                "source": "email",
                "vendor_id": vendor_id,
                "thread_status": thread_status,
                "attachment_count": len(attachments),
                "vendor_match_method": vendor_match_method,
            },
        )
        return result

    async def _publish_from_outbox(
        self,
        *,
        event_key: str,
        queue_url: str,
        payload: dict,
        correlation_id: str,
    ) -> None:
        """Publish a staged outbox payload to SQS, updating its state.

        Success → mark the outbox row sent.
        Failure → record the error on the outbox row and keep going.
        The drainer pass retries any rows still unsent.

        This is deliberately non-raising: the outbox is the source of
        truth, so a publish failure here never loses data — it just
        delays delivery by one poll cycle.
        """
        try:
            await self._sqs.send_message(
                queue_url,
                payload,
                correlation_id=correlation_id,
            )
        except Exception as exc:
            logger.warning(
                "Outbox publish failed — drainer will retry",
                tool="email_intake",
                event_key=event_key,
                error=str(exc),
                correlation_id=correlation_id,
            )
            try:
                await self._postgres.record_outbox_failure(
                    event_key, str(exc)
                )
            except Exception:
                # Recording the failure isn't critical; the drainer
                # finds unsent rows by sent_at IS NULL, not by error.
                logger.warning(
                    "record_outbox_failure itself failed — continuing",
                    tool="email_intake",
                    event_key=event_key,
                    correlation_id=correlation_id,
                )
            return

        try:
            await self._postgres.mark_outbox_sent(event_key)
        except Exception:
            # If we sent to SQS but couldn't flip sent_at, the drainer
            # will re-send on its next pass — duplicates are safe
            # because the downstream consumer idempotency keys on
            # query_id.
            logger.warning(
                "mark_outbox_sent failed — drainer will re-send (safe duplicate)",
                tool="email_intake",
                event_key=event_key,
                correlation_id=correlation_id,
            )

    async def _mark_read_safe(
        self,
        message_id: str,
        correlation_id: str,
    ) -> None:
        """Mark the email as read; swallow and log any failure.

        This is a housekeeping call and must never block or fail the
        main pipeline. A transient 429 or a closed httpx client during
        shutdown should not turn a successful ingestion into an error.
        """
        try:
            await self._graph_api.mark_as_read(
                message_id, correlation_id=correlation_id
            )
        except Exception:
            logger.warning(
                "mark_as_read failed — email will remain unread in Outlook",
                tool="email_intake",
                message_id=message_id,
                correlation_id=correlation_id,
            )

    async def _handle_rejected_email(
        self,
        *,
        decision: RelevanceDecision,
        parsed: dict,
        message_id: str,
        correlation_id: str,
    ) -> None:
        """Post-reject side effects — auto-replies, audit hook.

        Always non-critical: a failure here must not surface as an
        EmailIntakeError because the idempotency key is already written
        and SQS would just retry forever. We log and swallow.
        """
        if decision.action == "auto_reply_ask_details":
            recipient = parsed.get("sender_email")
            if recipient:
                try:
                    await self._graph_api.send_email(
                        to=recipient,
                        subject="Could you share a bit more detail?",
                        body_html=(
                            "<p>Hi,</p>"
                            "<p>Thanks for writing in. We couldn't identify a "
                            "specific question in your message. Could you reply "
                            "with a short description of what you need — for "
                            "example, the invoice/PO number, the amount, and "
                            "what's wrong?</p>"
                            "<p>— Vendor Support</p>"
                        ),
                        correlation_id=correlation_id,
                    )
                except Exception:
                    logger.warning(
                        "Auto-reply send failed — continuing",
                        tool="email_intake",
                        message_id=message_id,
                        correlation_id=correlation_id,
                    )

        # thread_only is handled in a later iteration — for now we
        # log and let the vendor's reply sit. Existing reconciliation
        # polling can still surface the parent thread's state.
        logger.info(
            "Email rejected — no SQS enqueue",
            tool="email_intake",
            layer=decision.layer,
            reason=decision.reason,
            action=decision.action,
            message_id=message_id,
            correlation_id=correlation_id,
        )

    async def _run_closure_detection(
        self,
        *,
        thread_status: str,
        conversation_id: str | None,
        body_text: str,
        new_query_id: str,
        correlation_id: str,
        attachments: list,
    ) -> None:
        """Hand off confirmation / reopen / follow-up decisions to ClosureService.

        The same reply can only ever be one of:
          - a confirmation ("thanks, resolved")
          - a reopen of a closed case
          - a follow-up with missing info on a still-open case

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

        if was_confirmation:
            return

        if thread_status == "REPLY_TO_CLOSED":
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
            return

        # EXISTING_OPEN + not a confirmation = the vendor is sending more
        # info on a query we are still working. Merge into the prior case
        # so we don't double-ticket / double-analyze.
        if thread_status == "EXISTING_OPEN":
            try:
                await self._closure_service.handle_followup_info(
                    conversation_id=conversation_id,
                    new_query_id=new_query_id,
                    body_text=body_text,
                    attachments_summary=[
                        {
                            "filename": a.filename,
                            "content_type": a.content_type,
                            "size_bytes": a.size_bytes,
                            "s3_key": a.s3_key,
                            "extraction_status": a.extraction_status,
                        }
                        for a in attachments
                    ],
                    correlation_id=correlation_id,
                )
            except Exception:
                logger.warning(
                    "Follow-up info handling failed — continuing",
                    new_query_id=new_query_id,
                    correlation_id=correlation_id,
                )
