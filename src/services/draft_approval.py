"""Module: services/draft_approval.py

Admin draft-approval service for Path A queries.

The pipeline halts every Path A case at status ``PENDING_APPROVAL``
after the Delivery node has created the ServiceNow ticket and stamped
the real INC number into the draft. This service backs the admin
draft-approval UI and is responsible for:

1. Listing every case waiting for approval.
2. Returning the full draft package for a single case (original query,
   AI analysis, the drafted email subject + HTML body, KB citations).
3. Sending the approved (and optionally edited) email to the vendor via
   Microsoft Graph and flipping the case status to ``RESOLVED``.
4. Recording rejections so the queue does not keep showing the case.

This service does NOT re-enter the LangGraph pipeline. The post-approval
work is small and synchronous — one email send + one status update —
so a graph re-entry would just add complexity for no gain.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from adapters.graph_api import GraphAPIConnector
from db.connection import PostgresConnector
from utils.exceptions import GraphAPIError
from utils.helpers import TimeHelper

logger = structlog.get_logger(__name__)

# Status values handled by this service. They live on
# workflow.case_execution.status which is VARCHAR(20), so all values
# below must fit in 20 characters.
STATUS_PENDING_APPROVAL = "PENDING_APPROVAL"  # 16 chars
STATUS_RESOLVED = "RESOLVED"
STATUS_REJECTED = "DRAFT_REJECTED"            # 14 chars


class DraftApprovalError(Exception):
    """Raised when a draft approval operation cannot complete."""


class DraftNotFoundError(DraftApprovalError):
    """Raised when no PENDING_APPROVAL case exists for the given query_id."""


class DraftApprovalService:
    """Backs the admin draft-approval queue and approve/edit/reject actions.

    The DeliveryNode persists the finalised draft + ticket_info on the
    ``workflow.case_execution`` row when Path A halts; this service is
    the only reader/writer for those rows once status is ``PENDING_APPROVAL``.
    """

    def __init__(
        self,
        postgres: PostgresConnector,
        graph_api: GraphAPIConnector,
        closure_service: Any | None = None,
    ) -> None:
        """Initialize with required connectors.

        Args:
            postgres: PostgreSQL connector — required for reads/writes
                against ``workflow.case_execution`` and ``audit.action_log``.
            graph_api: Graph API connector — used by ``approve`` to send
                the finalised email to the vendor.
            closure_service: Optional Phase 6 ClosureService. When present,
                ``register_resolution_sent`` is called after a successful
                send so the auto-close timer starts.
        """
        self._postgres = postgres
        self._graph_api = graph_api
        self._closure_service = closure_service

    # ------------------------------------------------------------------
    # READ — surface pending drafts to the admin UI
    # ------------------------------------------------------------------

    async def list_pending(self) -> list[dict]:
        """Return every case currently parked at ``PENDING_APPROVAL``.

        The list is ordered by ``updated_at`` descending so the freshest
        drafts appear first. Joined with the intake tables so the
        response carries the original subject regardless of source.
        """
        rows = await self._postgres.fetch(
            """
            SELECT ce.query_id,
                   ce.vendor_id,
                   ce.source,
                   ce.processing_path,
                   ce.analysis_result,
                   ce.draft_response,
                   ce.updated_at,
                   ce.created_at,
                   COALESCE(em.subject, pq.subject)        AS subject,
                   tl.ticket_id
            FROM workflow.case_execution ce
            LEFT JOIN intake.email_messages em ON ce.query_id = em.query_id
            LEFT JOIN intake.portal_queries pq ON ce.query_id = pq.query_id
            LEFT JOIN workflow.ticket_link  tl ON ce.query_id = tl.query_id
            WHERE ce.status = $1
            ORDER BY ce.updated_at DESC
            LIMIT 200
            """,
            STATUS_PENDING_APPROVAL,
        )

        items: list[dict] = []
        for row in rows:
            analysis = _coerce_jsonb(row.get("analysis_result"))
            draft = _coerce_jsonb(row.get("draft_response"))
            items.append(
                {
                    "query_id": row["query_id"],
                    "vendor_id": row.get("vendor_id"),
                    "subject": row.get("subject"),
                    "source": row.get("source"),
                    "processing_path": row.get("processing_path"),
                    "ticket_id": row.get("ticket_id"),
                    "intent": (analysis or {}).get("intent_classification"),
                    "confidence": (draft or {}).get("confidence")
                    or (analysis or {}).get("confidence_score"),
                    "drafted_at": str(row["updated_at"]),
                    "created_at": str(row["created_at"]),
                }
            )
        return items

    async def get_detail(self, query_id: str) -> dict:
        """Return the full draft package for a single case.

        Raises:
            DraftNotFoundError: No PENDING_APPROVAL case for this id.
        """
        row = await self._postgres.fetchrow(
            """
            SELECT ce.query_id,
                   ce.vendor_id,
                   ce.source,
                   ce.processing_path,
                   ce.status,
                   ce.analysis_result,
                   ce.routing_decision,
                   ce.draft_response,
                   ce.created_at,
                   ce.updated_at,
                   COALESCE(em.subject, pq.subject)     AS subject,
                   COALESCE(em.body_text, pq.description) AS original_body,
                   tl.ticket_id
            FROM workflow.case_execution ce
            LEFT JOIN intake.email_messages em ON ce.query_id = em.query_id
            LEFT JOIN intake.portal_queries pq ON ce.query_id = pq.query_id
            LEFT JOIN workflow.ticket_link  tl ON ce.query_id = tl.query_id
            WHERE ce.query_id = $1
            """,
            query_id,
        )
        if row is None:
            raise DraftNotFoundError(f"No case found for {query_id}")
        if row["status"] != STATUS_PENDING_APPROVAL:
            raise DraftNotFoundError(
                f"Case {query_id} is in status {row['status']}, "
                f"not {STATUS_PENDING_APPROVAL}",
            )

        analysis = _coerce_jsonb(row.get("analysis_result"))
        routing = _coerce_jsonb(row.get("routing_decision"))
        draft = _coerce_jsonb(row.get("draft_response")) or {}

        # Strip internal stash fields before sending to the UI — the admin
        # does not need to see the recipient/reply-to we cached for send.
        public_draft = {
            k: v for k, v in draft.items() if not k.startswith("_")
        }

        return {
            "query_id": row["query_id"],
            "vendor_id": row.get("vendor_id"),
            "source": row.get("source"),
            "processing_path": row.get("processing_path"),
            "status": row["status"],
            "subject": row.get("subject"),
            "original_body": row.get("original_body"),
            "ticket_id": row.get("ticket_id"),
            "analysis": analysis,
            "routing": routing,
            "draft": public_draft,
            "created_at": str(row["created_at"]),
            "drafted_at": str(row["updated_at"]),
        }

    # ------------------------------------------------------------------
    # WRITE — approve, approve-with-edits, reject
    # ------------------------------------------------------------------

    async def approve(
        self,
        query_id: str,
        *,
        actor: str,
        correlation_id: str,
    ) -> dict:
        """Send the persisted draft to the vendor and flip status to RESOLVED.

        Returns:
            Dict with query_id, ticket_id, recipient, status.

        Raises:
            DraftNotFoundError: No PENDING_APPROVAL case for this id.
            DraftApprovalError: Email send failed.
        """
        return await self._send_and_resolve(
            query_id=query_id,
            edited_subject=None,
            edited_body=None,
            actor=actor,
            correlation_id=correlation_id,
        )

    async def approve_with_edits(
        self,
        query_id: str,
        *,
        subject: str,
        body_html: str,
        actor: str,
        correlation_id: str,
    ) -> dict:
        """Overwrite the draft with admin edits and send.

        The edited subject/body are persisted onto draft_response BEFORE
        the send, so a delivery failure leaves the latest text in place
        for a retry.
        """
        return await self._send_and_resolve(
            query_id=query_id,
            edited_subject=subject,
            edited_body=body_html,
            actor=actor,
            correlation_id=correlation_id,
        )

    async def reject(
        self,
        query_id: str,
        *,
        feedback: str,
        actor: str,
        correlation_id: str,
    ) -> dict:
        """Reject the draft without sending.

        Sets the case to ``DRAFT_REJECTED`` and writes the feedback to
        ``audit.action_log``. The case stays terminal — re-drafting on
        rejection is out of scope for this iteration.
        """
        row = await self._postgres.fetchrow(
            "SELECT status FROM workflow.case_execution WHERE query_id = $1",
            query_id,
        )
        if row is None:
            raise DraftNotFoundError(f"No case found for {query_id}")
        if row["status"] != STATUS_PENDING_APPROVAL:
            raise DraftNotFoundError(
                f"Case {query_id} is in status {row['status']}, "
                f"not {STATUS_PENDING_APPROVAL}",
            )

        await self._postgres.execute(
            """
            UPDATE workflow.case_execution
            SET status = $1, updated_at = $2
            WHERE query_id = $3
            """,
            STATUS_REJECTED,
            TimeHelper.ist_now(),
            query_id,
        )
        await self._record_audit(
            query_id=query_id,
            correlation_id=correlation_id,
            actor=actor,
            action="draft_rejected",
            status="REJECTED",
            details={"feedback": feedback},
        )
        logger.info(
            "Draft rejected by admin",
            step="draft_approval",
            query_id=query_id,
            actor=actor,
            correlation_id=correlation_id,
        )
        return {"query_id": query_id, "status": STATUS_REJECTED}

    # ------------------------------------------------------------------
    # Internal — shared send + status flip path
    # ------------------------------------------------------------------

    async def _send_and_resolve(
        self,
        *,
        query_id: str,
        edited_subject: str | None,
        edited_body: str | None,
        actor: str,
        correlation_id: str,
    ) -> dict:
        """Send the (optionally edited) draft and flip status to RESOLVED."""
        row = await self._postgres.fetchrow(
            """
            SELECT ce.draft_response, ce.status, tl.ticket_id
            FROM workflow.case_execution ce
            LEFT JOIN workflow.ticket_link tl ON ce.query_id = tl.query_id
            WHERE ce.query_id = $1
            """,
            query_id,
        )
        if row is None:
            raise DraftNotFoundError(f"No case found for {query_id}")
        if row["status"] != STATUS_PENDING_APPROVAL:
            raise DraftNotFoundError(
                f"Case {query_id} is in status {row['status']}, "
                f"not {STATUS_PENDING_APPROVAL}",
            )

        draft = _coerce_jsonb(row.get("draft_response")) or {}
        if edited_subject is not None:
            draft["subject"] = edited_subject
        if edited_body is not None:
            draft["body"] = edited_body

        recipient = draft.get("_recipient_email")
        if not recipient:
            # Defensive: DeliveryNode stashes recipient on Path A, so a
            # missing value means the snapshot is malformed. Refuse to
            # send rather than silently drop the email.
            raise DraftApprovalError(
                f"Cannot send {query_id}: recipient email not on draft snapshot",
            )

        if edited_subject is not None or edited_body is not None:
            await self._postgres.execute(
                """
                UPDATE workflow.case_execution
                SET draft_response = $1::jsonb, updated_at = $2
                WHERE query_id = $3
                """,
                json.dumps(draft),
                TimeHelper.ist_now(),
                query_id,
            )

        try:
            await self._graph_api.send_email(
                to=recipient,
                subject=draft.get("subject", ""),
                body_html=draft.get("body", ""),
                reply_to_message_id=draft.get("_reply_to_message_id"),
                correlation_id=correlation_id,
            )
        except GraphAPIError as exc:
            logger.error(
                "Approved draft email send failed",
                step="draft_approval",
                query_id=query_id,
                error=str(exc),
                correlation_id=correlation_id,
            )
            raise DraftApprovalError(f"Graph API send failed: {exc}") from exc

        await self._postgres.execute(
            """
            UPDATE workflow.case_execution
            SET status = $1, updated_at = $2
            WHERE query_id = $3
            """,
            STATUS_RESOLVED,
            TimeHelper.ist_now(),
            query_id,
        )
        await self._record_audit(
            query_id=query_id,
            correlation_id=correlation_id,
            actor=actor,
            action=(
                "draft_approved_with_edits"
                if (edited_subject is not None or edited_body is not None)
                else "draft_approved"
            ),
            status="SENT",
            details={
                "ticket_id": row.get("ticket_id"),
                "recipient": recipient,
            },
        )

        # Phase 6 closure timer — non-critical: a failure here cannot roll
        # back a successful send.
        if self._closure_service is not None:
            try:
                await self._closure_service.register_resolution_sent(
                    query_id=query_id, correlation_id=correlation_id,
                )
            except Exception:
                logger.warning(
                    "Failed to register resolution_sent with ClosureService",
                    step="draft_approval",
                    query_id=query_id,
                    correlation_id=correlation_id,
                )

        logger.info(
            "Draft approved and sent",
            step="draft_approval",
            query_id=query_id,
            ticket_id=row.get("ticket_id"),
            actor=actor,
            edited=(edited_subject is not None or edited_body is not None),
            correlation_id=correlation_id,
        )
        return {
            "query_id": query_id,
            "ticket_id": row.get("ticket_id"),
            "recipient": recipient,
            "status": STATUS_RESOLVED,
        }

    async def _record_audit(
        self,
        *,
        query_id: str,
        correlation_id: str,
        actor: str,
        action: str,
        status: str,
        details: dict,
    ) -> None:
        """Append an entry to audit.action_log. Non-critical."""
        try:
            await self._postgres.execute(
                """
                INSERT INTO audit.action_log
                    (correlation_id, query_id, step_name, actor, action,
                     status, details)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
                """,
                correlation_id,
                query_id,
                "draft_approval",
                actor,
                action,
                status,
                json.dumps(details),
            )
        except Exception:
            logger.warning(
                "Failed to write audit.action_log entry",
                step="draft_approval",
                query_id=query_id,
                action=action,
                correlation_id=correlation_id,
            )


def _coerce_jsonb(value: Any) -> dict | None:
    """asyncpg returns JSONB as either a parsed dict or a JSON string.

    Normalise to a dict (or None) so callers don't have to branch.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None
