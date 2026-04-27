"""Module: services/closure.py

Phase 6 — Closure Service.

Owns the post-resolution lifecycle of a VQMS case:

  1. register_resolution_sent — called by delivery.py after the resolution
     email ships. Inserts a row in workflow.closure_tracking with an
     auto_close_deadline computed from business-day arithmetic. From that
     moment the auto-close timer is running.

  2. detect_confirmation — called by email_intake after thread correlation
     identifies an EXISTING_OPEN or REPLY_TO_CLOSED reply. Runs a simple
     case-insensitive substring match against settings.confirmation_keywords
     on the email body. On a hit we call close_case(VENDOR_CONFIRMED).

  3. handle_reopen — called for a REPLY_TO_CLOSED reply that was NOT a
     confirmation. Inside settings.closure_reopen_window_days we flip the
     prior case back to AWAITING_RESOLUTION and republish. Outside the
     window we leave the prior case closed and link the new query_id to
     it via workflow.case_execution.linked_query_id.

  4. handle_followup_info — called for an EXISTING_OPEN reply that was
     NOT a confirmation. Merges the new reply (body + attachments) into
     the prior case rather than letting it spawn a duplicate ticket and
     duplicate LLM run. Branches on the prior case's pipeline status
     so a mid-pipeline merge writes additional_context, a Path B case
     gets a ServiceNow work note, and a Path C / approval-gated case
     just queues the new info for the next checkpoint.

  5. close_case — the single write-path that actually closes a case. Used
     by detect_confirmation (VENDOR_CONFIRMED) and AutoCloseScheduler
     (AUTO_CLOSED). Updates case_execution + closure_tracking, flips the
     ServiceNow ticket to Closed, publishes TicketClosed, and writes an
     episodic_memory row so future queries from the same vendor get this
     case as context.

Design notes:
  * ServiceNow update, EventBridge publish, and episodic_memory write
    are all non-critical. A failure in any one is logged but does NOT
    roll back the database closure. The vendor-facing state (case
    closed) is the source of truth; auxiliary systems can be retried or
    reconciled later.
  * Keyword matching is intentionally dumb. LLM-based intent on every
    reply would be expensive and slower than the human reviewer could
    spot a false positive. The keyword list is configurable so ops can
    adjust without a code change.
"""

from __future__ import annotations

import orjson
import structlog

from config.settings import Settings
from events.eventbridge import EventBridgeConnector
from queues.sqs import SQSConnector
from services.episodic_memory import EpisodicMemoryWriter
from utils.decorators import log_service_call
from utils.helpers import DateHelper, TimeHelper

logger = structlog.get_logger(__name__)


class ClosureService:
    """Post-resolution lifecycle for VQMS cases.

    One instance per process, wired in app/lifespan.py and reused by
    delivery.py, email_intake/service.py, and AutoCloseScheduler.
    """

    def __init__(
        self,
        *,
        postgres,
        servicenow,
        eventbridge: EventBridgeConnector | None,
        sqs: SQSConnector | None,
        episodic_memory_writer: EpisodicMemoryWriter | None,
        settings: Settings,
    ) -> None:
        """Wire up the dependencies.

        Args:
            postgres: PostgresConnector for workflow schema reads/writes.
            servicenow: ServiceNow connector for ticket status updates.
            eventbridge: Optional EventBridge for TicketClosed / TicketReopened.
            sqs: Optional SQS connector for re-enqueueing on reopen.
            episodic_memory_writer: Optional writer that persists a summary
                row per closure so context_loading can surface it later.
            settings: Application settings (keywords, window, deadlines).
        """
        self._postgres = postgres
        self._servicenow = servicenow
        self._eventbridge = eventbridge
        self._sqs = sqs
        self._episodic_memory_writer = episodic_memory_writer
        self._settings = settings

    # ------------------------------------------------------------------
    # 1. register_resolution_sent — called by delivery.py
    # ------------------------------------------------------------------

    @log_service_call
    async def register_resolution_sent(
        self,
        *,
        query_id: str,
        correlation_id: str = "",
    ) -> bool:
        """Insert a closure_tracking row after a resolution email is sent.

        Idempotent via INSERT ON CONFLICT DO NOTHING — SQS retries or a
        reopen-then-resend will not overwrite the original deadline.

        Args:
            query_id: VQMS query ID that just had its resolution sent.
            correlation_id: Tracing ID carried through from delivery.

        Returns:
            True on successful insert (or row already existed), False on
            database failure. Non-critical: the caller (delivery.py) logs
            but does not raise.
        """
        if not query_id:
            return False

        now = TimeHelper.ist_now()
        deadline = DateHelper.add_business_days(
            now, self._settings.auto_close_business_days
        )

        try:
            await self._postgres.execute(
                """
                INSERT INTO workflow.closure_tracking (
                    query_id, correlation_id, resolution_sent_at,
                    auto_close_deadline, created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $5)
                ON CONFLICT (query_id) DO NOTHING
                """,
                query_id,
                correlation_id or "",
                now,
                deadline,
                now,
            )
        except Exception:
            logger.warning(
                "Failed to register resolution_sent (non-critical)",
                query_id=query_id,
                correlation_id=correlation_id,
            )
            return False

        logger.info(
            "Closure tracking row created",
            query_id=query_id,
            auto_close_deadline=deadline.isoformat(),
            business_days=self._settings.auto_close_business_days,
            correlation_id=correlation_id,
        )
        return True

    # ------------------------------------------------------------------
    # 2. detect_confirmation — called by email_intake on EXISTING_OPEN / REPLY_TO_CLOSED
    # ------------------------------------------------------------------

    @log_service_call
    async def detect_confirmation(
        self,
        *,
        conversation_id: str | None,
        body_text: str,
        correlation_id: str = "",
    ) -> bool:
        """If the reply body matches a confirmation keyword, close the prior case.

        Runs only when thread correlation placed the reply in an existing
        thread. Uses the conversation_id to find the most recent case on
        that thread, then checks whether closure_tracking has an open
        (not-yet-closed) row for it. On a keyword hit calls close_case
        with reason=VENDOR_CONFIRMED.

        Returns True iff a case was actually closed.
        """
        if not conversation_id or not body_text:
            return False

        prior_query_id = await self._find_prior_query_by_conversation(
            conversation_id, correlation_id
        )
        if not prior_query_id:
            return False

        tracking = await self._fetch_closure_tracking(prior_query_id)
        if tracking is None:
            return False
        if tracking.get("closed_at") is not None:
            return False

        if not self._matches_confirmation(body_text):
            return False

        logger.info(
            "Confirmation keyword detected — closing case",
            query_id=prior_query_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
        )
        await self.close_case(
            query_id=prior_query_id,
            reason="VENDOR_CONFIRMED",
            correlation_id=correlation_id,
        )
        return True

    # ------------------------------------------------------------------
    # 3. handle_reopen — called for REPLY_TO_CLOSED that was NOT a confirmation
    # ------------------------------------------------------------------

    @log_service_call
    async def handle_reopen(
        self,
        *,
        conversation_id: str | None,
        new_query_id: str,
        correlation_id: str = "",
    ) -> str:
        """Decide whether to reopen the prior case or link a new one.

        Inside settings.closure_reopen_window_days the reply counts as a
        continuation of the same case. Outside the window we treat it as
        a fresh query that happens to reference an older one.

        Returns one of:
            "REOPENED_SAME_CASE" — prior case flipped back to AWAITING_RESOLUTION
            "LINKED_NEW_CASE"    — new case linked via linked_query_id
            "SKIPPED"            — nothing to do (no prior, or prior not closed)
        """
        if not conversation_id or not new_query_id:
            return "SKIPPED"

        prior_query_id = await self._find_prior_query_by_conversation(
            conversation_id, correlation_id
        )
        if not prior_query_id:
            return "SKIPPED"

        tracking = await self._fetch_closure_tracking(prior_query_id)
        closed_at = tracking.get("closed_at") if tracking else None
        if closed_at is None:
            return "SKIPPED"

        now = TimeHelper.ist_now()
        days_since_close = (now - closed_at).days
        window = self._settings.closure_reopen_window_days

        if days_since_close <= window:
            await self._reopen_case(
                query_id=prior_query_id, correlation_id=correlation_id
            )
            return "REOPENED_SAME_CASE"

        await self._link_new_case(
            new_query_id=new_query_id,
            prior_query_id=prior_query_id,
            correlation_id=correlation_id,
        )
        return "LINKED_NEW_CASE"

    # ------------------------------------------------------------------
    # 4. handle_followup_info — called for EXISTING_OPEN that was NOT a confirmation
    # ------------------------------------------------------------------

    # Statuses where the prior case is still actively moving through the
    # pipeline (or paused waiting on a human). Merging the new info here
    # is safe because no resolution email has gone out yet.
    _MERGEABLE_STATUSES: frozenset[str] = frozenset(
        {
            "RECEIVED",
            "ANALYZING",
            "ROUTING",
            "DRAFTING",
            "VALIDATING",
            "DELIVERING",
            "PAUSED",  # Path C parked at human review
            "PENDING_APPROVAL",  # Path A parked at admin approval
            "AWAITING_RESOLUTION",  # Path B handed off to human team
        }
    )

    @log_service_call
    async def handle_followup_info(
        self,
        *,
        conversation_id: str | None,
        new_query_id: str,
        body_text: str,
        attachments_summary: list[dict] | None = None,
        correlation_id: str = "",
    ) -> str:
        """Merge a follow-up reply into the prior open case on the same thread.

        Vendors routinely realise they forgot a PDF or a clarifying detail
        and reply on the same thread. Without this method the reply spawns
        a duplicate query_id, ticket, and LLM run. This method:

          1. Finds the prior query_id on the same conversation_id.
          2. Reads its current pipeline status.
          3. If the status is in ``_MERGEABLE_STATUSES``, appends the new
             body + attachments_summary to ``case_execution.additional_context``
             on the prior case. Marks the new query_id as MERGED_INTO_PARENT
             and points its ``parent_query_id`` at the prior one so the
             SQS-triggered pipeline run for the new query_id is a no-op.
             For Path B (AWAITING_RESOLUTION) also adds a ServiceNow work
             note so the human team sees the new info on the existing
             ticket without a second incident being opened.
          4. If the prior case is RESOLVED / CLOSED / unknown — does
             nothing here; the existing handle_reopen path covers
             post-resolution replies.

        Returns one of:
            "MERGED_MID_PIPELINE" — additional_context written, child marked
            "MERGED_PATH_B"       — additional_context written + ServiceNow work note added
            "SKIPPED"             — prior not mergeable (closed / unknown / no prior)

        Non-critical: any failure is caught by the caller (email_intake)
        and logged. The new query_id always remains a valid standalone
        case so a partial merge is recoverable.
        """
        if not conversation_id or not new_query_id:
            return "SKIPPED"

        prior_query_id = await self._find_prior_query_by_conversation(
            conversation_id, correlation_id
        )
        if not prior_query_id:
            return "SKIPPED"
        if prior_query_id == new_query_id:
            # Defensive: should never happen because the new row hasn't
            # been linked to the conversation yet, but if our SELECT
            # picks it up we must not merge a case into itself.
            return "SKIPPED"

        prior_status = await self._fetch_case_status(prior_query_id)
        if prior_status is None or prior_status not in self._MERGEABLE_STATUSES:
            return "SKIPPED"

        appended = await self._append_additional_context(
            prior_query_id=prior_query_id,
            new_query_id=new_query_id,
            body_text=body_text,
            attachments_summary=attachments_summary or [],
            correlation_id=correlation_id,
        )
        if not appended:
            return "SKIPPED"

        await self._mark_child_merged(
            new_query_id=new_query_id,
            prior_query_id=prior_query_id,
            correlation_id=correlation_id,
        )

        await self._record_followup_audit(
            prior_query_id=prior_query_id,
            new_query_id=new_query_id,
            prior_status=prior_status,
            attachments_count=len(attachments_summary or []),
            correlation_id=correlation_id,
        )

        if prior_status == "AWAITING_RESOLUTION":
            await self._add_servicenow_followup_note(
                prior_query_id=prior_query_id,
                new_query_id=new_query_id,
                body_text=body_text,
                attachments_summary=attachments_summary or [],
                correlation_id=correlation_id,
            )
            logger.info(
                "Follow-up info merged into Path B case",
                prior_query_id=prior_query_id,
                new_query_id=new_query_id,
                correlation_id=correlation_id,
            )
            return "MERGED_PATH_B"

        logger.info(
            "Follow-up info merged into mid-pipeline case",
            prior_query_id=prior_query_id,
            new_query_id=new_query_id,
            prior_status=prior_status,
            correlation_id=correlation_id,
        )
        return "MERGED_MID_PIPELINE"

    # ------------------------------------------------------------------
    # 5. close_case — the single write-path for closing a case
    # ------------------------------------------------------------------

    @log_service_call
    async def close_case(
        self,
        *,
        query_id: str,
        reason: str,
        correlation_id: str = "",
    ) -> None:
        """Close a case end-to-end (DB + ServiceNow + event + memory).

        Steps:
          1. [CRITICAL] UPDATE workflow.case_execution.status = 'CLOSED'
          2. [CRITICAL] UPDATE workflow.closure_tracking.closed_at / reason
          3. [NON-CRITICAL] ServiceNow ticket status → Closed
          4. [NON-CRITICAL] EventBridge TicketClosed
          5. [NON-CRITICAL] EpisodicMemoryWriter.save_closure
        """
        now = TimeHelper.ist_now()

        # 1 + 2 [CRITICAL] — DB writes first; everything else hangs off these
        await self._postgres.execute(
            """
            UPDATE workflow.case_execution
            SET status = 'CLOSED', updated_at = $1
            WHERE query_id = $2
            """,
            now,
            query_id,
        )

        if reason == "VENDOR_CONFIRMED":
            await self._postgres.execute(
                """
                UPDATE workflow.closure_tracking
                SET closed_at = $1,
                    closed_reason = $2,
                    vendor_confirmation_detected_at = $1,
                    updated_at = $1
                WHERE query_id = $3
                """,
                now,
                reason,
                query_id,
            )
        else:
            await self._postgres.execute(
                """
                UPDATE workflow.closure_tracking
                SET closed_at = $1,
                    closed_reason = $2,
                    updated_at = $1
                WHERE query_id = $3
                """,
                now,
                reason,
                query_id,
            )

        # 3 [NON-CRITICAL] — flip ServiceNow to Closed
        await self._close_servicenow_ticket(query_id, reason, correlation_id)

        # 4 [NON-CRITICAL] — broadcast TicketClosed
        if self._eventbridge is not None:
            try:
                await self._eventbridge.publish_event(
                    "TicketClosed",
                    {
                        "query_id": query_id,
                        "closed_reason": reason,
                        "closed_at": now.isoformat(),
                    },
                    correlation_id=correlation_id,
                )
            except Exception:
                logger.warning(
                    "Failed to publish TicketClosed (non-critical)",
                    query_id=query_id,
                    correlation_id=correlation_id,
                )

        # 5 [NON-CRITICAL] — write episodic memory for future context
        if self._episodic_memory_writer is not None:
            try:
                await self._episodic_memory_writer.save_closure(
                    query_id=query_id,
                    correlation_id=correlation_id,
                    reason=reason,
                )
            except Exception:
                logger.warning(
                    "Failed to save episodic memory (non-critical)",
                    query_id=query_id,
                    correlation_id=correlation_id,
                )

        logger.info(
            "Case closed",
            query_id=query_id,
            reason=reason,
            correlation_id=correlation_id,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _find_prior_query_by_conversation(
        self, conversation_id: str, correlation_id: str = ""
    ) -> str | None:
        """Return the most recent query_id for the given conversation.

        conversation_id is stored on ``intake.email_messages`` (not
        on ``workflow.case_execution`` — the workflow schema stays
        source-agnostic). We JOIN by query_id to get the latest
        workflow row for this thread.

        Returns None on DB failure — caller treats that as
        "nothing to do".
        """
        try:
            row = await self._postgres.fetchrow(
                """
                SELECT ce.query_id
                  FROM workflow.case_execution ce
                  JOIN intake.email_messages em
                    ON em.query_id = ce.query_id
                 WHERE em.conversation_id = $1
                 ORDER BY ce.created_at DESC
                 LIMIT 1
                """,
                conversation_id,
            )
        except Exception:
            logger.warning(
                "case_execution lookup by conversation_id failed",
                conversation_id=conversation_id,
                correlation_id=correlation_id,
            )
            return None
        if row is None:
            return None
        return row.get("query_id")

    async def _fetch_closure_tracking(self, query_id: str) -> dict | None:
        """Return the closure_tracking row for a query, or None."""
        try:
            return await self._postgres.fetchrow(
                """
                SELECT query_id, resolution_sent_at, auto_close_deadline,
                       closed_at, closed_reason
                FROM workflow.closure_tracking
                WHERE query_id = $1
                """,
                query_id,
            )
        except Exception:
            logger.warning(
                "closure_tracking lookup failed",
                query_id=query_id,
            )
            return None

    def _matches_confirmation(self, body_text: str) -> bool:
        """Case-insensitive substring match against the configured keywords."""
        if not body_text:
            return False
        haystack = body_text.lower()
        for keyword in self._settings.confirmation_keywords:
            if keyword.lower() in haystack:
                return True
        return False

    async def _close_servicenow_ticket(
        self, query_id: str, reason: str, correlation_id: str
    ) -> None:
        """Resolve the ServiceNow ticket linked to this query, if any."""
        if self._servicenow is None:
            return
        try:
            row = await self._postgres.fetchrow(
                """
                SELECT ticket_id
                FROM workflow.ticket_link
                WHERE query_id = $1
                ORDER BY created_at DESC
                LIMIT 1
                """,
                query_id,
            )
        except Exception:
            logger.warning(
                "ticket_link lookup failed — ServiceNow not updated",
                query_id=query_id,
                correlation_id=correlation_id,
            )
            return

        ticket_id = row.get("ticket_id") if row else None
        if not ticket_id:
            return

        try:
            await self._servicenow.update_ticket_status(
                ticket_id,
                "Closed",
                work_notes=f"Closed by VQMS: {reason}",
                correlation_id=correlation_id,
            )
        except Exception:
            logger.warning(
                "ServiceNow close update failed (non-critical)",
                query_id=query_id,
                ticket_id=ticket_id,
                correlation_id=correlation_id,
            )

    async def _reopen_case(
        self, *, query_id: str, correlation_id: str
    ) -> None:
        """Flip a closed case back to AWAITING_RESOLUTION and republish.

        Inside-window reopen path. Updates case_execution status,
        flips closure_tracking.closed_reason to REOPENED, publishes
        TicketReopened, and re-enqueues the query to intake SQS so
        the graph picks it up with resume_context.is_reopen=True.
        """
        now = TimeHelper.ist_now()

        await self._postgres.execute(
            """
            UPDATE workflow.case_execution
            SET status = 'AWAITING_RESOLUTION', updated_at = $1
            WHERE query_id = $2
            """,
            now,
            query_id,
        )
        await self._postgres.execute(
            """
            UPDATE workflow.closure_tracking
            SET closed_reason = 'REOPENED', updated_at = $1
            WHERE query_id = $2
            """,
            now,
            query_id,
        )

        if self._eventbridge is not None:
            try:
                await self._eventbridge.publish_event(
                    "TicketReopened",
                    {
                        "query_id": query_id,
                        "reopened_at": now.isoformat(),
                    },
                    correlation_id=correlation_id,
                )
            except Exception:
                logger.warning(
                    "Failed to publish TicketReopened (non-critical)",
                    query_id=query_id,
                    correlation_id=correlation_id,
                )

        await self._reenqueue_for_reopen(
            query_id=query_id, correlation_id=correlation_id
        )

        logger.info(
            "Case reopened inside window",
            query_id=query_id,
            correlation_id=correlation_id,
        )

    async def _reenqueue_for_reopen(
        self, *, query_id: str, correlation_id: str
    ) -> None:
        """Push the reopen signal back onto the intake queue.

        Non-critical — if SQS is unavailable the case is still reopened
        in the DB, and a human reviewer can pick it up via the dashboard.
        """
        if self._sqs is None:
            return
        queue_url = self._settings.sqs_query_intake_queue_url
        if not queue_url:
            logger.warning(
                "No intake queue configured — reopen not re-enqueued",
                query_id=query_id,
                correlation_id=correlation_id,
            )
            return

        message = {
            "query_id": query_id,
            "correlation_id": correlation_id,
            "resume_context": {
                "is_reopen": True,
                "action": "resume_reopen",
            },
        }
        try:
            await self._sqs.send_message(
                queue_url, message, correlation_id=correlation_id
            )
        except Exception:
            logger.warning(
                "Reopen re-enqueue failed (non-critical)",
                query_id=query_id,
                correlation_id=correlation_id,
            )

    async def _link_new_case(
        self,
        *,
        new_query_id: str,
        prior_query_id: str,
        correlation_id: str,
    ) -> None:
        """Record the new query as linked to the prior (closed) one.

        Used when a vendor replies after the reopen window. The new
        query_id goes through the standard pipeline; this just drops
        a pointer back to the prior case for traceability.
        """
        try:
            await self._postgres.execute(
                """
                UPDATE workflow.case_execution
                SET linked_query_id = $1, updated_at = $2
                WHERE query_id = $3
                """,
                prior_query_id,
                TimeHelper.ist_now(),
                new_query_id,
            )
        except Exception:
            logger.warning(
                "Failed to set linked_query_id (non-critical)",
                new_query_id=new_query_id,
                prior_query_id=prior_query_id,
                correlation_id=correlation_id,
            )
            return

        logger.info(
            "New case linked to prior closed case",
            new_query_id=new_query_id,
            prior_query_id=prior_query_id,
            correlation_id=correlation_id,
        )

    # ------------------------------------------------------------------
    # Follow-up info helpers (used by handle_followup_info)
    # ------------------------------------------------------------------

    async def _fetch_case_status(self, query_id: str) -> str | None:
        """Return the current case_execution.status for a query_id, or None."""
        try:
            row = await self._postgres.fetchrow(
                """
                SELECT status
                FROM workflow.case_execution
                WHERE query_id = $1
                """,
                query_id,
            )
        except Exception:
            logger.warning(
                "case_execution status lookup failed",
                query_id=query_id,
            )
            return None
        if row is None:
            return None
        return row.get("status")

    async def _append_additional_context(
        self,
        *,
        prior_query_id: str,
        new_query_id: str,
        body_text: str,
        attachments_summary: list[dict],
        correlation_id: str,
    ) -> bool:
        """Append a follow-up entry to case_execution.additional_context.

        Uses jsonb_set + COALESCE so the column is initialised to an
        empty array on first follow-up and grows from there. Each entry
        carries the source query_id and a timestamp so reviewers can
        trace what was added when.

        Returns True on success, False on DB failure (non-critical:
        caller logs and continues).
        """
        entry = {
            "source_query_id": new_query_id,
            "received_at": TimeHelper.ist_now().isoformat(),
            "body_text": (body_text or "")[:5000],
            "attachments": attachments_summary,
        }
        try:
            await self._postgres.execute(
                """
                UPDATE workflow.case_execution
                SET additional_context = COALESCE(additional_context, '[]'::jsonb)
                                         || $1::jsonb,
                    updated_at = $2
                WHERE query_id = $3
                """,
                orjson.dumps([entry]).decode("utf-8"),
                TimeHelper.ist_now(),
                prior_query_id,
            )
        except Exception:
            logger.warning(
                "Failed to append additional_context (non-critical)",
                prior_query_id=prior_query_id,
                new_query_id=new_query_id,
                correlation_id=correlation_id,
            )
            return False
        return True

    async def _mark_child_merged(
        self,
        *,
        new_query_id: str,
        prior_query_id: str,
        correlation_id: str,
    ) -> None:
        """Flip the new (child) case to MERGED_INTO_PARENT and link it.

        Once a child is in this terminal state the SQS-driven pipeline
        run for it should detect the status and exit early — the merged
        info now lives on the parent.
        """
        try:
            await self._postgres.execute(
                """
                UPDATE workflow.case_execution
                SET status = 'MERGED_INTO_PARENT',
                    parent_query_id = $1,
                    updated_at = $2
                WHERE query_id = $3
                """,
                prior_query_id,
                TimeHelper.ist_now(),
                new_query_id,
            )
        except Exception:
            logger.warning(
                "Failed to mark child MERGED_INTO_PARENT (non-critical)",
                new_query_id=new_query_id,
                prior_query_id=prior_query_id,
                correlation_id=correlation_id,
            )

    async def _record_followup_audit(
        self,
        *,
        prior_query_id: str,
        new_query_id: str,
        prior_status: str,
        attachments_count: int,
        correlation_id: str,
    ) -> None:
        """Write an audit.action_log entry for the merge.

        Non-critical — a missing audit row never blocks the merge.
        """
        details = {
            "prior_query_id": prior_query_id,
            "new_query_id": new_query_id,
            "prior_status": prior_status,
            "attachments_count": attachments_count,
        }
        try:
            await self._postgres.execute(
                """
                INSERT INTO audit.action_log
                    (correlation_id, query_id, step_name, actor, action,
                     status, details, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
                """,
                correlation_id or "",
                prior_query_id,
                "closure.followup",
                "system",
                "FOLLOWUP_INFO_RECEIVED",
                "merged",
                orjson.dumps(details).decode("utf-8"),
                TimeHelper.ist_now(),
            )
        except Exception:
            logger.warning(
                "Failed to write FOLLOWUP_INFO_RECEIVED audit row",
                prior_query_id=prior_query_id,
                new_query_id=new_query_id,
                correlation_id=correlation_id,
            )

    async def _add_servicenow_followup_note(
        self,
        *,
        prior_query_id: str,
        new_query_id: str,
        body_text: str,
        attachments_summary: list[dict],
        correlation_id: str,
    ) -> None:
        """Add a work note to the prior case's ServiceNow ticket.

        Path B (AWAITING_RESOLUTION) means a human team is already
        looking at this ticket. Surfacing the new info as a work note
        is the difference between the team finding the missing PDF on
        their own ticket vs. a second ticket showing up in their queue.
        """
        if self._servicenow is None:
            return
        try:
            row = await self._postgres.fetchrow(
                """
                SELECT ticket_id
                FROM workflow.ticket_link
                WHERE query_id = $1
                ORDER BY created_at DESC
                LIMIT 1
                """,
                prior_query_id,
            )
        except Exception:
            logger.warning(
                "ticket_link lookup failed — work note not added",
                prior_query_id=prior_query_id,
                correlation_id=correlation_id,
            )
            return

        ticket_id = row.get("ticket_id") if row else None
        if not ticket_id:
            return

        attachment_lines = "\n".join(
            f"- {a.get('filename', '<unknown>')} "
            f"({a.get('content_type', '')}, "
            f"{a.get('size_bytes', 0)} bytes)"
            for a in attachments_summary
        )
        note = (
            f"VQMS follow-up reply from vendor on the same thread "
            f"(child query {new_query_id}).\n\n"
            f"Body:\n{(body_text or '')[:2000]}\n\n"
            f"Attachments:\n{attachment_lines or '(none)'}"
        )

        try:
            await self._servicenow.add_work_note(
                ticket_id,
                note,
                correlation_id=correlation_id,
            )
        except Exception:
            logger.warning(
                "ServiceNow work note add failed (non-critical)",
                prior_query_id=prior_query_id,
                ticket_id=ticket_id,
                correlation_id=correlation_id,
            )
