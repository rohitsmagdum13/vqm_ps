"""Tests for the AdminEmailService and admin email routes.

Covers:
- AttachmentValidator: count, per-file size, total size, blocked extensions.
- AdminEmailService.send: happy path, query_id missing, Graph failure,
  idempotent replay (same payload), 409-style mismatch (different payload).
- AdminEmailService.reply_to_query: trail resolution, override message,
  no-trail 422, override-from-different-conversation 422.

All external systems (Graph, Postgres, S3) are mocked. No network or DB.
"""

from __future__ import annotations

from io import BytesIO
from unittest.mock import AsyncMock

import pytest
from fastapi import UploadFile

from adapters.graph_api.email_send import OutboundAttachment
from services.admin_email.attachments import (
    AttachmentLimits,
    AttachmentValidator,
)
from services.admin_email.service import (
    AdminEmailService,
    _payload_hash,
)
from utils.exceptions import (
    AdminEmailError,
    AdminEmailQueryNotFoundError,
    AttachmentRejectedError,
    GraphAPIError,
)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _upload(filename: str, payload: bytes, content_type: str = "application/pdf") -> UploadFile:
    """Build an UploadFile around the given bytes."""
    file = BytesIO(payload)
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    upload = UploadFile(
        file=file,
        filename=filename,
        size=size,
        headers={"content-type": content_type},
    )
    return upload


class _FakeStager:
    """Minimal stager — skips real S3 and just builds OutboundAttachments
    in-memory. Used so the service tests don't need moto for every case.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[UploadFile]]] = []

    async def stage(self, outbound_id: str, files: list[UploadFile], *, correlation_id: str = ""):
        self.calls.append((outbound_id, list(files)))
        from services.admin_email.attachments import StagedAttachment

        staged = []
        for upload in files:
            content = await upload.read()
            staged.append(
                StagedAttachment(
                    attachment_id=f"ATT-{upload.filename}",
                    s3_key=f"outbound-emails/{outbound_id}/{upload.filename}",
                    outbound_attachment=OutboundAttachment(
                        filename=upload.filename or "f",
                        content_type=upload.content_type or "application/octet-stream",
                        content_bytes=content,
                        size_bytes=len(content),
                    ),
                )
            )
        return staged


def _service(postgres: AsyncMock, graph_api: AsyncMock) -> AdminEmailService:
    return AdminEmailService(
        postgres=postgres,
        graph_api=graph_api,
        attachment_stager=_FakeStager(),
        attachment_validator=AttachmentValidator(),
    )


# ---------------------------------------------------------------------
# AttachmentValidator
# ---------------------------------------------------------------------


class TestAttachmentValidator:
    def test_accepts_within_limits(self) -> None:
        v = AttachmentValidator()
        v.validate([_upload("invoice.pdf", b"x" * 100)])

    def test_rejects_too_many(self) -> None:
        v = AttachmentValidator(AttachmentLimits(max_count=2))
        files = [
            _upload("a.pdf", b"x"),
            _upload("b.pdf", b"x"),
            _upload("c.pdf", b"x"),
        ]
        with pytest.raises(AttachmentRejectedError, match="Too many attachments"):
            v.validate(files)

    def test_rejects_per_file_too_large(self) -> None:
        v = AttachmentValidator(AttachmentLimits(max_per_file_bytes=10))
        with pytest.raises(AttachmentRejectedError, match="File too large"):
            v.validate([_upload("big.pdf", b"x" * 100)])

    def test_rejects_total_too_large(self) -> None:
        v = AttachmentValidator(
            AttachmentLimits(max_per_file_bytes=100, max_total_bytes=50)
        )
        with pytest.raises(AttachmentRejectedError, match="Total attachments"):
            v.validate(
                [
                    _upload("a.pdf", b"x" * 30),
                    _upload("b.pdf", b"x" * 30),
                ]
            )

    def test_rejects_blocked_extension(self) -> None:
        v = AttachmentValidator()
        with pytest.raises(AttachmentRejectedError, match="extension"):
            v.validate([_upload("malware.exe", b"x")])


# ---------------------------------------------------------------------
# AdminEmailService.send — fresh
# ---------------------------------------------------------------------


class TestAdminEmailServiceSend:
    async def test_happy_path_no_attachments(
        self, mock_postgres: AsyncMock
    ) -> None:
        graph_api = AsyncMock()
        graph_api.send_email.return_value = None
        # No prior idempotency row; query_id check returns nothing because
        # we don't pass query_id below.
        mock_postgres.fetchrow.return_value = None

        service = _service(mock_postgres, graph_api)

        result = await service.send(
            to=["vendor@example.com"],
            cc=None,
            bcc=None,
            subject="Hello",
            body_html="<p>Hi</p>",
            files=[],
            vendor_id=None,
            query_id=None,
            actor="admin@vqms.com",
            client_request_id=None,
            correlation_id="cid-001",
        )

        assert result.thread_mode == "fresh"
        assert result.to == ["vendor@example.com"]
        assert result.attachments == []
        assert result.idempotent_replay is False
        graph_api.send_email.assert_awaited_once()
        # Postgres must have written the QUEUED row + flipped to SENT + audit.
        assert mock_postgres.execute.await_count >= 3

    async def test_rejects_when_query_id_missing(
        self, mock_postgres: AsyncMock
    ) -> None:
        graph_api = AsyncMock()
        # query existence check returns None
        mock_postgres.fetchrow.return_value = None
        service = _service(mock_postgres, graph_api)

        with pytest.raises(AdminEmailQueryNotFoundError):
            await service.send(
                to=["vendor@example.com"],
                cc=None,
                bcc=None,
                subject="Hello",
                body_html="<p>Hi</p>",
                files=[],
                vendor_id=None,
                query_id="VQ-2026-9999",
                actor="admin@vqms.com",
                client_request_id=None,
                correlation_id="cid-002",
            )
        graph_api.send_email.assert_not_called()

    async def test_marks_failed_on_graph_error(
        self, mock_postgres: AsyncMock
    ) -> None:
        graph_api = AsyncMock()
        graph_api.send_email.side_effect = GraphAPIError(
            endpoint="/sendMail", status_code=500
        )
        mock_postgres.fetchrow.return_value = None
        service = _service(mock_postgres, graph_api)

        with pytest.raises(AdminEmailError) as exc_info:
            await service.send(
                to=["vendor@example.com"],
                cc=None,
                bcc=None,
                subject="Hello",
                body_html="<p>Hi</p>",
                files=[],
                vendor_id=None,
                query_id=None,
                actor="admin@vqms.com",
                client_request_id=None,
                correlation_id="cid-003",
            )
        # outbound_id was generated and bubbled out for caller telemetry.
        assert exc_info.value.outbound_id is not None

    async def test_idempotent_replay_returns_existing_row(
        self, mock_postgres: AsyncMock
    ) -> None:
        graph_api = AsyncMock()
        # Pre-compute the payload hash so the replay row matches.
        payload_hash = _payload_hash(
            to=["vendor@example.com"],
            cc=[],
            bcc=[],
            subject="Hello",
            body_html="<p>Hi</p>",
            files=[],
            thread_mode="fresh",
            reply_to_message_id=None,
        )

        mock_postgres.fetchrow.return_value = {
            "outbound_id": "AOE-2026-0001",
            "payload_hash": payload_hash,
            "status": "SENT",
            "to_recipients": ["vendor@example.com"],
            "cc_recipients": [],
            "bcc_recipients": [],
            "subject": "Hello",
            "thread_mode": "fresh",
            "reply_to_message_id": None,
            "query_id": None,
            "sent_at": None,
        }
        mock_postgres.fetch.return_value = []

        service = _service(mock_postgres, graph_api)
        result = await service.send(
            to=["vendor@example.com"],
            cc=None,
            bcc=None,
            subject="Hello",
            body_html="<p>Hi</p>",
            files=[],
            vendor_id=None,
            query_id=None,
            actor="admin@vqms.com",
            client_request_id="req-123",
            correlation_id="cid-004",
        )

        assert result.idempotent_replay is True
        assert result.outbound_id == "AOE-2026-0001"
        # No Graph send when replay hits.
        graph_api.send_email.assert_not_called()

    async def test_idempotent_mismatch_raises(
        self, mock_postgres: AsyncMock
    ) -> None:
        graph_api = AsyncMock()
        mock_postgres.fetchrow.return_value = {
            "outbound_id": "AOE-2026-0001",
            "payload_hash": "deadbeef" * 8,  # different hash
            "status": "SENT",
            "to_recipients": ["vendor@example.com"],
            "cc_recipients": [],
            "bcc_recipients": [],
            "subject": "Hello",
            "thread_mode": "fresh",
            "reply_to_message_id": None,
            "query_id": None,
            "sent_at": None,
        }

        service = _service(mock_postgres, graph_api)
        with pytest.raises(AdminEmailError, match="different content"):
            await service.send(
                to=["vendor@example.com"],
                cc=None,
                bcc=None,
                subject="Hello",
                body_html="<p>DIFFERENT</p>",
                files=[],
                vendor_id=None,
                query_id=None,
                actor="admin@vqms.com",
                client_request_id="req-123",
                correlation_id="cid-005",
            )


# ---------------------------------------------------------------------
# AdminEmailService.reply_to_query
# ---------------------------------------------------------------------


class TestAdminEmailServiceReply:
    async def test_replies_to_latest_inbound(
        self, mock_postgres: AsyncMock
    ) -> None:
        graph_api = AsyncMock()
        graph_api.send_email.return_value = None
        # First fetchrow = trail lookup, returning the latest inbound row.
        mock_postgres.fetchrow.return_value = {
            "message_id": "AAMkAD-original",
            "sender_email": "vendor@example.com",
            "subject": "Question about PO",
            "conversation_id": "AAQkAD-conv",
            "query_id": "VQ-2026-0001",
            "received_at": None,
        }

        service = _service(mock_postgres, graph_api)
        result = await service.reply_to_query(
            "VQ-2026-0001",
            body_html="<p>Got it</p>",
            cc=None,
            bcc=None,
            to_override=None,
            files=[],
            reply_to_message_id_override=None,
            actor="admin@vqms.com",
            client_request_id=None,
            correlation_id="cid-010",
        )

        assert result.thread_mode == "reply"
        assert result.reply_to_message_id == "AAMkAD-original"
        assert result.conversation_id == "AAQkAD-conv"
        assert result.to == ["vendor@example.com"]
        # send_email called with reply_to_message_id and threading args.
        send_kwargs = graph_api.send_email.await_args.kwargs
        assert send_kwargs["reply_to_message_id"] == "AAMkAD-original"

    async def test_no_trail_returns_no_trail_reason(
        self, mock_postgres: AsyncMock
    ) -> None:
        graph_api = AsyncMock()

        # First fetchrow (trail lookup) -> None,
        # second fetchrow (case_execution check) -> a row, so we report no_trail.
        mock_postgres.fetchrow.side_effect = [None, {"_": 1}]

        service = _service(mock_postgres, graph_api)
        with pytest.raises(AdminEmailQueryNotFoundError) as exc_info:
            await service.reply_to_query(
                "VQ-2026-0001",
                body_html="<p>Got it</p>",
                cc=None,
                bcc=None,
                to_override=None,
                files=[],
                reply_to_message_id_override=None,
                actor="admin@vqms.com",
                client_request_id=None,
                correlation_id="cid-011",
            )
        assert exc_info.value.reason == "no_trail"
        graph_api.send_email.assert_not_called()

    async def test_query_not_found_returns_not_found_reason(
        self, mock_postgres: AsyncMock
    ) -> None:
        graph_api = AsyncMock()
        # Both lookups return None — the case_execution row also doesn't exist.
        mock_postgres.fetchrow.side_effect = [None, None]

        service = _service(mock_postgres, graph_api)
        with pytest.raises(AdminEmailQueryNotFoundError) as exc_info:
            await service.reply_to_query(
                "VQ-2026-0099",
                body_html="<p>Got it</p>",
                cc=None,
                bcc=None,
                to_override=None,
                files=[],
                reply_to_message_id_override=None,
                actor="admin@vqms.com",
                client_request_id=None,
                correlation_id="cid-012",
            )
        assert exc_info.value.reason == "not_found"

    async def test_override_in_different_conversation_rejected(
        self, mock_postgres: AsyncMock
    ) -> None:
        graph_api = AsyncMock()
        # 1st fetchrow = trail anchor, 2nd = override row in a different conv.
        mock_postgres.fetchrow.side_effect = [
            {
                "message_id": "AAMkAD-latest",
                "sender_email": "vendor@example.com",
                "subject": "Question",
                "conversation_id": "conv-A",
                "query_id": "VQ-2026-0001",
                "received_at": None,
            },
            {
                "message_id": "AAMkAD-other",
                "sender_email": "vendor@example.com",
                "subject": "Different thread",
                "conversation_id": "conv-B",
                "query_id": "VQ-2026-0002",
            },
        ]

        service = _service(mock_postgres, graph_api)
        with pytest.raises(AdminEmailQueryNotFoundError) as exc_info:
            await service.reply_to_query(
                "VQ-2026-0001",
                body_html="<p>Got it</p>",
                cc=None,
                bcc=None,
                to_override=None,
                files=[],
                reply_to_message_id_override="AAMkAD-other",
                actor="admin@vqms.com",
                client_request_id=None,
                correlation_id="cid-013",
            )
        assert exc_info.value.reason == "override_message_in_different_conversation"
        graph_api.send_email.assert_not_called()
