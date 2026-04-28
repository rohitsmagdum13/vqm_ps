"""Module: adapters/graph_api/email_send.py

Email sending operations via Microsoft Graph API.

Handles sending outbound emails to vendors via the
/sendMail endpoint. Used by the Delivery node (Step 12)
for both Path A resolution emails and Path B acknowledgments,
and by AdminEmailService for free-form admin send/reply.

The send_email signature accepts both a single ``to`` string (for
backward-compatibility with the Delivery node and DraftApprovalService)
and a list of recipients with cc/bcc/attachments support for the admin
email API. The branching between Graph's "inline attachment" path
(<= 3 MB total) and the "createUploadSession" path (> 3 MB) lives
inside this adapter so callers don't have to think about it.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

import structlog

from adapters.graph_api.client import GRAPH_BASE_URL
from utils.decorators import log_service_call

logger = structlog.get_logger(__name__)

# Graph API guidance: total message size <= 4 MB stays inline. We use
# 3 MB as the practical threshold to leave headroom for the JSON envelope
# and base64 expansion.
INLINE_ATTACHMENT_THRESHOLD_BYTES = 3 * 1024 * 1024  # 3 MB

# Graph upload session chunk size — 5 MB is the documented sweet spot.
SESSION_UPLOAD_CHUNK_BYTES = 5 * 1024 * 1024  # 5 MB


@dataclass(frozen=True)
class OutboundAttachment:
    """A single attachment ready to send via Graph API.

    The bytes are loaded into memory by the staging layer (S3 download
    or direct upload). The adapter decides between inline encoding and
    upload session based on the cumulative size.
    """

    filename: str
    content_type: str
    content_bytes: bytes
    size_bytes: int


class EmailSendMixin:
    """Email send methods for the Graph API connector.

    Mixed into GraphAPIConnector. Expects self._request()
    and self._mailbox from GraphAPIClient.
    """

    @log_service_call
    async def send_email(
        self,
        to: str | list[str],
        subject: str,
        body_html: str,
        *,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        attachments: list[OutboundAttachment] | None = None,
        reply_to_message_id: str | None = None,
        correlation_id: str = "",
    ) -> None:
        """Send an email via Graph API.

        Threading:
            When ``reply_to_message_id`` is provided, the message is sent
            via ``/messages/{id}/reply`` (no attachments) or
            ``/messages/{id}/createReply`` -> upload sessions -> /send
            (with attachments). Graph copies the original conversationId
            and sets In-Reply-To / References headers so Outlook/Gmail
            group the response under the same trail.

            When ``reply_to_message_id`` is None, a standalone /sendMail
            (or draft + send for large attachments) is used.

        Recipients:
            ``to`` accepts either a single email string (legacy callers)
            or a list of strings. Internal logic always works on a list.

        Attachments:
            * Total size <= 3 MB AND no single file > 3 MB -> inline base64
              ``fileAttachment`` array on the message.
            * Otherwise -> Graph upload-session path: create a draft, push
              each large file via createUploadSession + chunked PUT, then
              POST /send.

        Args:
            to: Recipient email address(es).
            subject: Email subject (used only for fresh sends, ignored
                by Graph on the simple ``/reply`` path).
            body_html: HTML body content.
            cc: Optional list of CC recipients.
            bcc: Optional list of BCC recipients.
            attachments: Optional list of OutboundAttachment.
            reply_to_message_id: Graph internal message ID of the email
                being replied to. When set, the response is threaded.
            correlation_id: Tracing ID.

        Raises:
            GraphAPIError: On API errors.
        """
        to_list: list[str] = [to] if isinstance(to, str) else list(to)
        cc_list: list[str] = list(cc or [])
        bcc_list: list[str] = list(bcc or [])
        attachments = attachments or []

        total_attachment_bytes = sum(att.size_bytes for att in attachments)
        any_oversize = any(
            att.size_bytes > INLINE_ATTACHMENT_THRESHOLD_BYTES
            for att in attachments
        )
        needs_upload_session = bool(attachments) and (
            total_attachment_bytes > INLINE_ATTACHMENT_THRESHOLD_BYTES
            or any_oversize
        )

        if needs_upload_session:
            await self._send_via_upload_session(
                to_list=to_list,
                cc_list=cc_list,
                bcc_list=bcc_list,
                subject=subject,
                body_html=body_html,
                attachments=attachments,
                reply_to_message_id=reply_to_message_id,
                correlation_id=correlation_id,
            )
            return

        # Inline path — covers (a) no attachments, (b) all attachments
        # small enough to encode in the request body.
        if reply_to_message_id:
            await self._send_inline_reply(
                to_list=to_list,
                cc_list=cc_list,
                bcc_list=bcc_list,
                body_html=body_html,
                attachments=attachments,
                reply_to_message_id=reply_to_message_id,
                correlation_id=correlation_id,
            )
            return

        await self._send_inline_fresh(
            to_list=to_list,
            cc_list=cc_list,
            bcc_list=bcc_list,
            subject=subject,
            body_html=body_html,
            attachments=attachments,
            correlation_id=correlation_id,
        )

    # ------------------------------------------------------------------
    # Inline path — attachments fit in the request body
    # ------------------------------------------------------------------

    async def _send_inline_fresh(
        self,
        *,
        to_list: list[str],
        cc_list: list[str],
        bcc_list: list[str],
        subject: str,
        body_html: str,
        attachments: list[OutboundAttachment],
        correlation_id: str,
    ) -> None:
        """Fresh send via /sendMail with optional inline attachments."""
        message: dict = {
            "subject": subject,
            "body": {"contentType": "HTML", "content": body_html},
            "toRecipients": _to_recipient_list(to_list),
        }
        if cc_list:
            message["ccRecipients"] = _to_recipient_list(cc_list)
        if bcc_list:
            message["bccRecipients"] = _to_recipient_list(bcc_list)
        if attachments:
            message["attachments"] = [_inline_attachment(a) for a in attachments]

        url = f"{GRAPH_BASE_URL}/users/{self._mailbox}/sendMail"
        await self._request(
            "POST",
            url,
            json_body={"message": message, "saveToSentItems": True},
            correlation_id=correlation_id,
        )
        logger.info(
            "Email sent via Graph API",
            tool="graph_api",
            to_count=len(to_list),
            cc_count=len(cc_list),
            bcc_count=len(bcc_list),
            attachment_count=len(attachments),
            subject=subject,
            correlation_id=correlation_id,
        )

    async def _send_inline_reply(
        self,
        *,
        to_list: list[str],
        cc_list: list[str],
        bcc_list: list[str],
        body_html: str,
        attachments: list[OutboundAttachment],
        reply_to_message_id: str,
        correlation_id: str,
    ) -> None:
        """Threaded reply via /messages/{id}/reply with optional inline attachments.

        Graph's /reply endpoint accepts a ``message`` envelope with override
        fields. Recipients/attachments here override the defaults Graph would
        otherwise inherit from the original message.
        """
        url = (
            f"{GRAPH_BASE_URL}/users/{self._mailbox}"
            f"/messages/{reply_to_message_id}/reply"
        )
        override_message: dict = {
            "body": {"contentType": "HTML", "content": body_html},
            "toRecipients": _to_recipient_list(to_list),
        }
        if cc_list:
            override_message["ccRecipients"] = _to_recipient_list(cc_list)
        if bcc_list:
            override_message["bccRecipients"] = _to_recipient_list(bcc_list)
        if attachments:
            override_message["attachments"] = [_inline_attachment(a) for a in attachments]

        await self._request(
            "POST",
            url,
            json_body={"message": override_message, "comment": ""},
            correlation_id=correlation_id,
        )
        logger.info(
            "Email sent via Graph API (threaded reply)",
            tool="graph_api",
            to_count=len(to_list),
            cc_count=len(cc_list),
            bcc_count=len(bcc_list),
            attachment_count=len(attachments),
            reply_to_message_id=reply_to_message_id,
            correlation_id=correlation_id,
        )

    # ------------------------------------------------------------------
    # Upload-session path — attachments too large for inline encoding
    # ------------------------------------------------------------------

    async def _send_via_upload_session(
        self,
        *,
        to_list: list[str],
        cc_list: list[str],
        bcc_list: list[str],
        subject: str,
        body_html: str,
        attachments: list[OutboundAttachment],
        reply_to_message_id: str | None,
        correlation_id: str,
    ) -> None:
        """Send a message with > 3 MB total attachments via upload sessions.

        Flow:
            1. Create a draft message (POST /messages or POST /messages/{id}/createReply).
            2. For each attachment > 3 MB: createUploadSession + chunked PUT.
               For each attachment <= 3 MB: POST as inline fileAttachment.
            3. POST /messages/{draftId}/send.

        We do NOT roll back the draft on partial failure — Graph will GC
        unsent drafts after a few days, and a half-built draft is far less
        damaging than a half-sent email.
        """
        # Step 1 — create the draft.
        if reply_to_message_id:
            create_url = (
                f"{GRAPH_BASE_URL}/users/{self._mailbox}"
                f"/messages/{reply_to_message_id}/createReply"
            )
            create_body = {"comment": ""}
        else:
            create_url = f"{GRAPH_BASE_URL}/users/{self._mailbox}/messages"
            create_body = {
                "subject": subject,
                "body": {"contentType": "HTML", "content": body_html},
                "toRecipients": _to_recipient_list(to_list),
            }
            if cc_list:
                create_body["ccRecipients"] = _to_recipient_list(cc_list)
            if bcc_list:
                create_body["bccRecipients"] = _to_recipient_list(bcc_list)

        draft_response = await self._request(
            "POST",
            create_url,
            json_body=create_body,
            correlation_id=correlation_id,
        )
        draft = draft_response.json()
        draft_id = draft.get("id")
        if not draft_id:
            # Should never happen — Graph always returns the draft id.
            # But raising here is safer than silently sending nothing.
            from utils.exceptions import GraphAPIError

            raise GraphAPIError(
                endpoint=create_url,
                status_code=500,
                correlation_id=correlation_id,
            )

        # For createReply we still need to update body + recipients on the draft.
        if reply_to_message_id:
            patch_body: dict = {
                "body": {"contentType": "HTML", "content": body_html},
                "toRecipients": _to_recipient_list(to_list),
            }
            if cc_list:
                patch_body["ccRecipients"] = _to_recipient_list(cc_list)
            if bcc_list:
                patch_body["bccRecipients"] = _to_recipient_list(bcc_list)
            await self._request(
                "PATCH",
                f"{GRAPH_BASE_URL}/users/{self._mailbox}/messages/{draft_id}",
                json_body=patch_body,
                correlation_id=correlation_id,
            )

        # Step 2 — push each attachment.
        for att in attachments:
            if att.size_bytes <= INLINE_ATTACHMENT_THRESHOLD_BYTES:
                await self._post_inline_attachment(draft_id, att, correlation_id)
            else:
                await self._upload_large_attachment(draft_id, att, correlation_id)

        # Step 3 — send the draft.
        await self._request(
            "POST",
            f"{GRAPH_BASE_URL}/users/{self._mailbox}/messages/{draft_id}/send",
            correlation_id=correlation_id,
        )

        logger.info(
            "Email sent via Graph API (upload-session path)",
            tool="graph_api",
            to_count=len(to_list),
            cc_count=len(cc_list),
            bcc_count=len(bcc_list),
            attachment_count=len(attachments),
            total_attachment_bytes=sum(a.size_bytes for a in attachments),
            threaded=reply_to_message_id is not None,
            correlation_id=correlation_id,
        )

    async def _post_inline_attachment(
        self,
        draft_id: str,
        att: OutboundAttachment,
        correlation_id: str,
    ) -> None:
        """Attach a small file (<= 3 MB) inline to a draft message."""
        url = (
            f"{GRAPH_BASE_URL}/users/{self._mailbox}"
            f"/messages/{draft_id}/attachments"
        )
        await self._request(
            "POST",
            url,
            json_body=_inline_attachment(att),
            correlation_id=correlation_id,
        )

    async def _upload_large_attachment(
        self,
        draft_id: str,
        att: OutboundAttachment,
        correlation_id: str,
    ) -> None:
        """Upload a large attachment (> 3 MB) via Graph upload session.

        createUploadSession returns a uploadUrl that does NOT need the
        Bearer token — Graph signs it. We chunk the bytes and PUT each
        chunk with a Content-Range header.
        """
        # Create the upload session.
        session_url = (
            f"{GRAPH_BASE_URL}/users/{self._mailbox}"
            f"/messages/{draft_id}/attachments/createUploadSession"
        )
        session_response = await self._request(
            "POST",
            session_url,
            json_body={
                "AttachmentItem": {
                    "attachmentType": "file",
                    "name": att.filename,
                    "size": att.size_bytes,
                    "contentType": att.content_type,
                }
            },
            correlation_id=correlation_id,
        )
        upload_url = session_response.json().get("uploadUrl")
        if not upload_url:
            from utils.exceptions import GraphAPIError

            raise GraphAPIError(
                endpoint=session_url,
                status_code=500,
                correlation_id=correlation_id,
            )

        # Chunked PUTs against the pre-signed uploadUrl.
        client = await self._get_http_client()
        total = att.size_bytes
        offset = 0
        while offset < total:
            end = min(offset + SESSION_UPLOAD_CHUNK_BYTES, total) - 1
            chunk = att.content_bytes[offset : end + 1]
            response = await client.put(
                upload_url,
                content=chunk,
                headers={
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {offset}-{end}/{total}",
                },
            )
            if response.status_code >= 400:
                from utils.exceptions import GraphAPIError

                logger.error(
                    "Graph upload-session chunk failed",
                    tool="graph_api",
                    filename=att.filename,
                    status_code=response.status_code,
                    offset=offset,
                    correlation_id=correlation_id,
                )
                raise GraphAPIError(
                    endpoint=upload_url,
                    status_code=response.status_code,
                    correlation_id=correlation_id,
                )
            offset = end + 1


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _to_recipient_list(emails: list[str]) -> list[dict]:
    """Convert a list of email strings into Graph recipient dicts."""
    return [{"emailAddress": {"address": email}} for email in emails]


def _inline_attachment(att: OutboundAttachment) -> dict:
    """Build the Graph fileAttachment payload for an inline attachment."""
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": att.filename,
        "contentType": att.content_type,
        "contentBytes": base64.b64encode(att.content_bytes).decode("ascii"),
    }
