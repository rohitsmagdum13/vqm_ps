"""Module: services/admin_email/service.py

Admin Email Service — orchestrates free-form admin send/reply.

Responsibilities:
1. Resolve the message being replied to (latest inbound on a thread,
   or an explicit ``reply_to_message_id`` pinned by the admin).
2. Validate attachments BEFORE creating any state.
3. Compute the SHA-256 payload hash so X-Request-Id idempotency can
   reject reused request ids that carry different content.
4. Pre-INSERT a tracking row with status=QUEUED so a Graph failure
   never leaves an orphan send.
5. Call GraphAPIConnector.send_email with cc/bcc/attachments.
6. UPDATE row + audit log on success or failure.

The service does NOT interact with the LangGraph pipeline, the
draft-approval queue, or the SLA monitor — admin sends are
intentionally a side-channel.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog

from adapters.graph_api import GraphAPIConnector
from db.connection import PostgresConnector
from services.admin_email.attachments import (
    AttachmentStager,
    AttachmentValidator,
    StagedAttachment,
)
from utils.exceptions import (
    AdminEmailError,
    AdminEmailQueryNotFoundError,
    GraphAPIError,
)
from utils.helpers import TimeHelper

logger = structlog.get_logger(__name__)

STATUS_QUEUED = "QUEUED"
STATUS_SENT = "SENT"
STATUS_FAILED = "FAILED"

THREAD_FRESH = "fresh"
THREAD_REPLY = "reply"

ATTACHMENT_STATUS_STAGED = "STAGED"
ATTACHMENT_STATUS_SENT = "SENT"
ATTACHMENT_STATUS_FAILED = "FAILED"


@dataclass(frozen=True)
class AdminSendResult:
    """Return type for ``AdminEmailService.send`` / ``reply_to_query``.

    The route handler turns this into the JSON response. ``idempotent_replay``
    is True when the row was returned from the idempotency cache instead
    of newly sent.
    """

    outbound_id: str
    to: list[str]
    cc: list[str]
    bcc: list[str]
    subject: str
    sent_at: datetime
    thread_mode: str
    query_id: str | None
    reply_to_message_id: str | None
    conversation_id: str | None
    attachments: list[dict]
    idempotent_replay: bool


class AdminEmailService:
    """Backs the admin email send/reply API.

    All state writes go through this service so the route handler stays
    thin (validate, hand off, format the response).
    """

    def __init__(
        self,
        *,
        postgres: PostgresConnector,
        graph_api: GraphAPIConnector,
        attachment_stager: AttachmentStager,
        attachment_validator: AttachmentValidator,
    ) -> None:
        self._postgres = postgres
        self._graph_api = graph_api
        self._stager = attachment_stager
        self._validator = attachment_validator

    # ------------------------------------------------------------------
    # Public API — fresh send
    # ------------------------------------------------------------------

    async def send(
        self,
        *,
        to: list[str],
        cc: list[str] | None,
        bcc: list[str] | None,
        subject: str,
        body_html: str,
        files: list,
        vendor_id: str | None,
        query_id: str | None,
        actor: str,
        client_request_id: str | None,
        correlation_id: str,
    ) -> AdminSendResult:
        """Send a fresh admin email (no thread).

        Raises:
            AdminEmailError: Send failed at any layer.
            AdminEmailQueryNotFoundError: ``query_id`` was supplied but
                does not exist in workflow.case_execution.
            AttachmentRejectedError: Attachment validation failed.
        """
        cc_list = list(cc or [])
        bcc_list = list(bcc or [])

        # Validate attachments BEFORE any state is created.
        self._validator.validate(files)

        # Confirm the query_id exists when one is supplied.
        if query_id is not None:
            await self._assert_query_exists(query_id, correlation_id=correlation_id)

        # Compute payload hash for idempotency mismatch detection.
        payload_hash = _payload_hash(
            to=to,
            cc=cc_list,
            bcc=bcc_list,
            subject=subject,
            body_html=body_html,
            files=files,
            thread_mode=THREAD_FRESH,
            reply_to_message_id=None,
        )

        # Check for an idempotent replay BEFORE doing any work.
        if client_request_id:
            replay = await self._check_idempotent_replay(
                actor=actor,
                request_id=client_request_id,
                payload_hash=payload_hash,
            )
            if replay is not None:
                return replay

        # Stage attachments to S3 (validated, but not yet a DB row).
        outbound_id = _generate_outbound_id()
        staged = await self._stager.stage(
            outbound_id, files, correlation_id=correlation_id
        )

        # Pre-INSERT tracking row.
        await self._insert_outbound_row(
            outbound_id=outbound_id,
            request_id=client_request_id,
            correlation_id=correlation_id,
            query_id=query_id,
            actor=actor,
            to=to,
            cc=cc_list,
            bcc=bcc_list,
            subject=subject,
            body_html=body_html,
            thread_mode=THREAD_FRESH,
            reply_to_message_id=None,
            payload_hash=payload_hash,
            attachments=staged,
        )

        # Send via Graph.
        try:
            await self._graph_api.send_email(
                to=to,
                subject=subject,
                body_html=body_html,
                cc=cc_list,
                bcc=bcc_list,
                attachments=[s.outbound_attachment for s in staged],
                reply_to_message_id=None,
                correlation_id=correlation_id,
            )
        except GraphAPIError as exc:
            await self._mark_failed(outbound_id, exc, correlation_id=correlation_id)
            raise AdminEmailError(
                f"Graph API send failed: {exc}",
                outbound_id=outbound_id,
                correlation_id=correlation_id,
            ) from exc

        # Mark SENT + audit.
        sent_at = TimeHelper.ist_now()
        await self._mark_sent(outbound_id, sent_at)
        await self._record_audit(
            outbound_id=outbound_id,
            query_id=query_id,
            correlation_id=correlation_id,
            actor=actor,
            action="admin_email_send",
            status="SENT",
            details={
                "thread_mode": THREAD_FRESH,
                "to_count": len(to),
                "cc_count": len(cc_list),
                "bcc_count": len(bcc_list),
                "attachment_count": len(staged),
                "vendor_id": vendor_id,
                "quality_gate": "skipped_admin_actor",
            },
        )

        logger.info(
            "Admin email sent (fresh)",
            outbound_id=outbound_id,
            actor=actor,
            to_count=len(to),
            attachment_count=len(staged),
            correlation_id=correlation_id,
        )

        return AdminSendResult(
            outbound_id=outbound_id,
            to=list(to),
            cc=cc_list,
            bcc=bcc_list,
            subject=subject,
            sent_at=sent_at,
            thread_mode=THREAD_FRESH,
            query_id=query_id,
            reply_to_message_id=None,
            conversation_id=None,
            attachments=_summarise_attachments(staged),
            idempotent_replay=False,
        )

    # ------------------------------------------------------------------
    # Public API — threaded reply
    # ------------------------------------------------------------------

    async def reply_to_query(
        self,
        query_id: str,
        *,
        body_html: str,
        cc: list[str] | None,
        bcc: list[str] | None,
        to_override: list[str] | None,
        files: list,
        reply_to_message_id_override: str | None,
        actor: str,
        client_request_id: str | None,
        correlation_id: str,
    ) -> AdminSendResult:
        """Reply to the existing email trail attached to ``query_id``.

        By default the reply is anchored to the latest inbound message.
        When ``reply_to_message_id_override`` is provided, the service
        validates it belongs to the same conversation_id and uses it.

        Raises:
            AdminEmailQueryNotFoundError: query_id has no inbound email
                or doesn't exist (route maps to 422 / 404).
            AdminEmailError: Send failed.
            AttachmentRejectedError: Attachment validation failed.
        """
        # Validate attachments BEFORE any state is created.
        self._validator.validate(files)

        # Resolve the message we'll reply to.
        anchor = await self._resolve_reply_anchor(
            query_id=query_id,
            override_message_id=reply_to_message_id_override,
            correlation_id=correlation_id,
        )

        to_list = list(to_override) if to_override else [anchor["sender_email"]]
        cc_list = list(cc or [])
        bcc_list = list(bcc or [])
        subject = anchor.get("subject") or ""

        # Compute payload hash. Anchor message id is part of the hash so
        # replays anchored to a different message are treated as distinct.
        payload_hash = _payload_hash(
            to=to_list,
            cc=cc_list,
            bcc=bcc_list,
            subject=subject,
            body_html=body_html,
            files=files,
            thread_mode=THREAD_REPLY,
            reply_to_message_id=anchor["message_id"],
        )

        if client_request_id:
            replay = await self._check_idempotent_replay(
                actor=actor,
                request_id=client_request_id,
                payload_hash=payload_hash,
            )
            if replay is not None:
                return replay

        outbound_id = _generate_outbound_id()
        staged = await self._stager.stage(
            outbound_id, files, correlation_id=correlation_id
        )

        await self._insert_outbound_row(
            outbound_id=outbound_id,
            request_id=client_request_id,
            correlation_id=correlation_id,
            query_id=query_id,
            actor=actor,
            to=to_list,
            cc=cc_list,
            bcc=bcc_list,
            subject=subject,
            body_html=body_html,
            thread_mode=THREAD_REPLY,
            reply_to_message_id=anchor["message_id"],
            payload_hash=payload_hash,
            attachments=staged,
        )

        try:
            await self._graph_api.send_email(
                to=to_list,
                subject=subject,
                body_html=body_html,
                cc=cc_list,
                bcc=bcc_list,
                attachments=[s.outbound_attachment for s in staged],
                reply_to_message_id=anchor["message_id"],
                correlation_id=correlation_id,
            )
        except GraphAPIError as exc:
            await self._mark_failed(outbound_id, exc, correlation_id=correlation_id)
            raise AdminEmailError(
                f"Graph API reply failed: {exc}",
                outbound_id=outbound_id,
                correlation_id=correlation_id,
            ) from exc

        sent_at = TimeHelper.ist_now()
        await self._mark_sent(outbound_id, sent_at)
        await self._record_audit(
            outbound_id=outbound_id,
            query_id=query_id,
            correlation_id=correlation_id,
            actor=actor,
            action="admin_email_reply",
            status="SENT",
            details={
                "thread_mode": THREAD_REPLY,
                "reply_to_message_id": anchor["message_id"],
                "conversation_id": anchor.get("conversation_id"),
                "to_count": len(to_list),
                "cc_count": len(cc_list),
                "bcc_count": len(bcc_list),
                "attachment_count": len(staged),
                "quality_gate": "skipped_admin_actor",
            },
        )

        logger.info(
            "Admin email sent (reply)",
            outbound_id=outbound_id,
            query_id=query_id,
            actor=actor,
            reply_to_message_id=anchor["message_id"],
            attachment_count=len(staged),
            correlation_id=correlation_id,
        )

        return AdminSendResult(
            outbound_id=outbound_id,
            to=to_list,
            cc=cc_list,
            bcc=bcc_list,
            subject=subject,
            sent_at=sent_at,
            thread_mode=THREAD_REPLY,
            query_id=query_id,
            reply_to_message_id=anchor["message_id"],
            conversation_id=anchor.get("conversation_id"),
            attachments=_summarise_attachments(staged),
            idempotent_replay=False,
        )

    # ------------------------------------------------------------------
    # Internal helpers — DB writes + reply lookup
    # ------------------------------------------------------------------

    async def _assert_query_exists(
        self, query_id: str, *, correlation_id: str
    ) -> None:
        """Raise AdminEmailQueryNotFoundError if query_id is not in
        workflow.case_execution. Used by ``send`` when a query_id is
        provided for tagging.
        """
        row = await self._postgres.fetchrow(
            "SELECT 1 FROM workflow.case_execution WHERE query_id = $1",
            query_id,
        )
        if row is None:
            raise AdminEmailQueryNotFoundError(
                query_id,
                reason="not_found",
                correlation_id=correlation_id,
            )

    async def _resolve_reply_anchor(
        self,
        *,
        query_id: str,
        override_message_id: str | None,
        correlation_id: str,
    ) -> dict:
        """Return the inbound message dict the reply should anchor to.

        Without an override -> latest inbound on the trail.
        With an override -> the matching row, but only if it shares the
        same conversation_id as the query's other messages.
        """
        # Latest inbound on the trail (covers conversation_id grouping).
        latest = await self._postgres.fetchrow(
            """
            SELECT message_id,
                   sender_email,
                   subject,
                   conversation_id,
                   query_id,
                   received_at
            FROM intake.email_messages
            WHERE query_id = $1
               OR conversation_id = (
                   SELECT conversation_id
                   FROM intake.email_messages
                   WHERE query_id = $1 AND conversation_id IS NOT NULL
                   LIMIT 1
               )
            ORDER BY received_at DESC
            LIMIT 1
            """,
            query_id,
        )
        if latest is None:
            # No inbound at all -> not_found vs no_trail depends on
            # whether the case_execution row exists.
            case_row = await self._postgres.fetchrow(
                "SELECT 1 FROM workflow.case_execution WHERE query_id = $1",
                query_id,
            )
            reason = "no_trail" if case_row is not None else "not_found"
            raise AdminEmailQueryNotFoundError(
                query_id, reason=reason, correlation_id=correlation_id
            )

        if override_message_id is None:
            return dict(latest)

        # Validate the override belongs to the same conversation.
        override_row = await self._postgres.fetchrow(
            """
            SELECT message_id, sender_email, subject, conversation_id, query_id
            FROM intake.email_messages
            WHERE message_id = $1
            """,
            override_message_id,
        )
        if override_row is None:
            raise AdminEmailQueryNotFoundError(
                query_id,
                reason="override_message_not_found",
                correlation_id=correlation_id,
            )

        latest_conv = latest.get("conversation_id")
        override_conv = override_row.get("conversation_id")
        # If both have a conversation_id they must match. If either is
        # NULL we accept it as long as both share the same query_id.
        if latest_conv and override_conv:
            if latest_conv != override_conv:
                raise AdminEmailQueryNotFoundError(
                    query_id,
                    reason="override_message_in_different_conversation",
                    correlation_id=correlation_id,
                )
        else:
            if override_row.get("query_id") != latest.get("query_id"):
                raise AdminEmailQueryNotFoundError(
                    query_id,
                    reason="override_message_in_different_conversation",
                    correlation_id=correlation_id,
                )

        return dict(override_row)

    async def _check_idempotent_replay(
        self,
        *,
        actor: str,
        request_id: str,
        payload_hash: str,
    ) -> AdminSendResult | None:
        """Look up an existing row for (actor, request_id).

        Returns:
            * None — no prior row (caller proceeds to send).
            * AdminSendResult with idempotent_replay=True — prior row was
              SENT and the payload hash matches.

        Raises:
            AdminEmailError(409 sentinel) — prior row exists but the
              payload hash differs. The route handler maps this to 409.

        Failed prior rows are treated as "retry from scratch" — caller
        proceeds and creates a new tracking row.
        """
        row = await self._postgres.fetchrow(
            """
            SELECT outbound_id,
                   payload_hash,
                   status,
                   to_recipients,
                   cc_recipients,
                   bcc_recipients,
                   subject,
                   thread_mode,
                   reply_to_message_id,
                   query_id,
                   sent_at
            FROM intake.admin_outbound_emails
            WHERE actor = $1 AND request_id = $2
            """,
            actor,
            request_id,
        )
        if row is None:
            return None

        if row["status"] != STATUS_SENT:
            # Failed earlier — let the caller retry.
            return None

        if row["payload_hash"] and row["payload_hash"] != payload_hash:
            raise AdminEmailError(
                "X-Request-Id reused with different content",
                correlation_id=None,
            )

        # Reconstruct the AdminSendResult from the row.
        attachments = await self._postgres.fetch(
            """
            SELECT attachment_id, filename, size_bytes
            FROM intake.admin_outbound_attachments
            WHERE outbound_id = $1
            ORDER BY created_at ASC
            """,
            row["outbound_id"],
        )
        return AdminSendResult(
            outbound_id=row["outbound_id"],
            to=_loads_jsonb_list(row["to_recipients"]),
            cc=_loads_jsonb_list(row["cc_recipients"]),
            bcc=_loads_jsonb_list(row["bcc_recipients"]),
            subject=row["subject"],
            sent_at=row["sent_at"],
            thread_mode=row["thread_mode"],
            query_id=row["query_id"],
            reply_to_message_id=row["reply_to_message_id"],
            conversation_id=None,
            attachments=[
                {
                    "attachment_id": a["attachment_id"],
                    "filename": a["filename"],
                    "size_bytes": a["size_bytes"],
                }
                for a in attachments
            ],
            idempotent_replay=True,
        )

    async def _insert_outbound_row(
        self,
        *,
        outbound_id: str,
        request_id: str | None,
        correlation_id: str,
        query_id: str | None,
        actor: str,
        to: list[str],
        cc: list[str],
        bcc: list[str],
        subject: str,
        body_html: str,
        thread_mode: str,
        reply_to_message_id: str | None,
        payload_hash: str,
        attachments: list[StagedAttachment],
    ) -> None:
        """Atomically insert the outbound row + attachment rows.

        Done in a single transaction so a partial failure doesn't leave
        orphan attachment rows.
        """
        async with self._postgres.transaction() as conn:
            await conn.execute(
                """
                INSERT INTO intake.admin_outbound_emails (
                    outbound_id, request_id, correlation_id, query_id, actor,
                    to_recipients, cc_recipients, bcc_recipients,
                    subject, body_html,
                    thread_mode, reply_to_message_id,
                    payload_hash, status, created_at
                )
                VALUES ($1,$2,$3,$4,$5,
                        $6::jsonb,$7::jsonb,$8::jsonb,
                        $9,$10,
                        $11,$12,
                        $13,$14,$15)
                """,
                outbound_id,
                request_id,
                correlation_id,
                query_id,
                actor,
                json.dumps(to),
                json.dumps(cc),
                json.dumps(bcc),
                subject,
                body_html,
                thread_mode,
                reply_to_message_id,
                payload_hash,
                STATUS_QUEUED,
                TimeHelper.ist_now(),
            )

            for staged in attachments:
                await conn.execute(
                    """
                    INSERT INTO intake.admin_outbound_attachments (
                        attachment_id, outbound_id,
                        filename, content_type, size_bytes,
                        s3_key, upload_status, created_at
                    )
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                    """,
                    staged.attachment_id,
                    outbound_id,
                    staged.outbound_attachment.filename,
                    staged.outbound_attachment.content_type,
                    staged.outbound_attachment.size_bytes,
                    staged.s3_key,
                    ATTACHMENT_STATUS_STAGED,
                    TimeHelper.ist_now(),
                )

    async def _mark_sent(self, outbound_id: str, sent_at: datetime) -> None:
        """Flip status to SENT and set sent_at."""
        await self._postgres.execute(
            """
            UPDATE intake.admin_outbound_emails
            SET status = $1, sent_at = $2
            WHERE outbound_id = $3
            """,
            STATUS_SENT,
            sent_at,
            outbound_id,
        )
        await self._postgres.execute(
            """
            UPDATE intake.admin_outbound_attachments
            SET upload_status = $1
            WHERE outbound_id = $2
            """,
            ATTACHMENT_STATUS_SENT,
            outbound_id,
        )

    async def _mark_failed(
        self,
        outbound_id: str,
        exc: Exception,
        *,
        correlation_id: str,
    ) -> None:
        """Flip status to FAILED, capture the error message."""
        try:
            await self._postgres.execute(
                """
                UPDATE intake.admin_outbound_emails
                SET status = $1, last_error = $2, failed_at = $3
                WHERE outbound_id = $4
                """,
                STATUS_FAILED,
                str(exc)[:2000],
                TimeHelper.ist_now(),
                outbound_id,
            )
            await self._postgres.execute(
                """
                UPDATE intake.admin_outbound_attachments
                SET upload_status = $1
                WHERE outbound_id = $2
                """,
                ATTACHMENT_STATUS_FAILED,
                outbound_id,
            )
        except Exception:
            logger.warning(
                "Failed to mark admin outbound email FAILED",
                outbound_id=outbound_id,
                correlation_id=correlation_id,
            )

    async def _record_audit(
        self,
        *,
        outbound_id: str,
        query_id: str | None,
        correlation_id: str,
        actor: str,
        action: str,
        status: str,
        details: dict,
    ) -> None:
        """Append an audit.action_log row. Non-critical."""
        try:
            details_with_outbound = dict(details)
            details_with_outbound["outbound_id"] = outbound_id
            await self._postgres.execute(
                """
                INSERT INTO audit.action_log
                    (correlation_id, query_id, step_name, actor, action,
                     status, details)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
                """,
                correlation_id,
                query_id,
                "admin_email",
                actor,
                action,
                status,
                json.dumps(details_with_outbound),
            )
        except Exception:
            logger.warning(
                "Failed to write audit.action_log entry",
                outbound_id=outbound_id,
                action=action,
                correlation_id=correlation_id,
            )


# ----------------------------------------------------------------------
# Module-level helpers
# ----------------------------------------------------------------------


def _generate_outbound_id() -> str:
    """Build an AOE-YYYY-NNNN id. Uses the same dev-mode UUID-tail
    sequence trick as IdGenerator.generate_query_id so we don't need
    a database sequence yet.
    """
    year = TimeHelper.ist_now().year
    sequence = int(uuid.uuid4().hex[-4:], 16) % 10000
    return f"AOE-{year}-{sequence:04d}"


def _payload_hash(
    *,
    to: list[str],
    cc: list[str],
    bcc: list[str],
    subject: str,
    body_html: str,
    files: list,
    thread_mode: str,
    reply_to_message_id: str | None,
) -> str:
    """SHA-256 of a canonical request payload.

    Used by the idempotency check to detect when a reused X-Request-Id
    is sent with different content. Files are hashed by (filename,
    size) — we don't read the bytes here because that would force an
    extra round-trip on every request.
    """
    canonical = {
        "to": sorted(to),
        "cc": sorted(cc),
        "bcc": sorted(bcc),
        "subject": subject,
        "body_html": body_html,
        "thread_mode": thread_mode,
        "reply_to_message_id": reply_to_message_id,
        "files": sorted(
            [
                {"name": (f.filename or ""), "size": getattr(f, "size", None) or 0}
                for f in files
            ],
            key=lambda d: d["name"],
        ),
    }
    serialised = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()


def _summarise_attachments(staged: list[StagedAttachment]) -> list[dict]:
    """Public-facing summary used in API responses."""
    return [
        {
            "attachment_id": s.attachment_id,
            "filename": s.outbound_attachment.filename,
            "size_bytes": s.outbound_attachment.size_bytes,
        }
        for s in staged
    ]


def _loads_jsonb_list(value: Any) -> list[str]:
    """asyncpg returns JSONB as either a parsed list or a JSON string.

    Normalise to list[str] (or empty list) so AdminSendResult typing holds.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return [str(x) for x in parsed] if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []
