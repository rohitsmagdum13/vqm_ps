"""Module: api/routes/admin_email.py

Admin email send/reply endpoints.

Two endpoints, both ADMIN-only, both accept multipart/form-data so
attachments work natively:

- POST /admin/email/send                          (fresh email)
- POST /admin/email/queries/{query_id}/reply      (threaded reply on
                                                   the existing trail)

Threading guarantee:
    The reply endpoint resolves the latest inbound email on the trail
    (or a specific message id passed as ``reply_to_message_id``) and
    sends through Graph's /messages/{id}/reply, so vendors receive the
    response inside the same Outlook/Gmail conversation as the original.

Idempotency:
    Optional ``X-Request-Id`` header dedupes reissued requests. A reused
    id with the same payload returns the original response with header
    ``X-Idempotent-Replay: true``. A reused id with different content is
    rejected with 409.

Quality gate:
    Skipped intentionally — admin is a trusted actor. Audit log records
    the skip so compliance review can see it.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from services.admin_email import AdminEmailService, AdminSendResult
from utils.decorators import log_api_call
from utils.exceptions import (
    AdminEmailError,
    AdminEmailQueryNotFoundError,
    AttachmentRejectedError,
)
from utils.helpers import IdGenerator

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin/email", tags=["admin-email"])

CORRELATION_ID_HEADER = "X-Correlation-Id"
REQUEST_ID_HEADER = "X-Request-Id"
IDEMPOTENT_REPLAY_HEADER = "X-Idempotent-Replay"


def _require_admin(request: Request) -> None:
    """403 unless the JWT decoded by AuthMiddleware says ADMIN."""
    role = getattr(request.state, "role", None)
    if role != "ADMIN":
        raise HTTPException(
            status_code=403,
            detail="Admin role required",
        )


def _service(request: Request) -> AdminEmailService:
    """Pull AdminEmailService off app.state or 503."""
    service = getattr(request.app.state, "admin_email_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Admin Email Service unavailable — check PostgreSQL, "
                "Graph API, and S3 connections"
            ),
        )
    return service


def _actor(request: Request) -> str:
    """Best-effort identifier for the admin sending the email."""
    return (
        getattr(request.state, "user_email", None)
        or getattr(request.state, "username", None)
        or getattr(request.state, "user_id", None)
        or "admin"
    )


def _correlation_id(request: Request) -> str:
    """Read X-Correlation-Id header, generate one if absent."""
    incoming = request.headers.get(CORRELATION_ID_HEADER)
    return incoming or IdGenerator.generate_correlation_id()


def _split_csv(value: str | None) -> list[str]:
    """Split a comma-separated form field into a clean list of emails.

    Empty strings are dropped — admin sending only ``cc=`` (no value)
    should be treated the same as not sending the field.

    Swagger UI ships the literal placeholder text ``"string"`` when an
    optional field is left untouched and "Send empty value" is not
    clicked. We drop that exact value so the placeholder doesn't end
    up as a recipient address.
    """
    if not value:
        return []
    return [
        item.strip()
        for item in value.split(",")
        if item.strip() and item.strip() != "string"
    ]


def _clean_optional(value: str | None) -> str | None:
    """Clean an optional Form field. Drops Swagger's ``"string"`` placeholder."""
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned or cleaned == "string":
        return None
    return cleaned


def _real_files(files: list[UploadFile]) -> list[UploadFile]:
    """Filter out phantom UploadFile entries.

    FastAPI yields an empty UploadFile when no files are uploaded and
    ``File(default=[])`` is used. Same pattern as queries.py:submit_query.
    """
    return [f for f in files if f and f.filename]


def _result_to_response(
    result: AdminSendResult,
    correlation_id: str,
    *,
    status_code: int = 200,
) -> JSONResponse:
    """Format an AdminSendResult into the JSON response payload."""
    body = {
        "outbound_id": result.outbound_id,
        "to": result.to,
        "cc": result.cc,
        "bcc": result.bcc,
        "subject": result.subject,
        "sent_at": result.sent_at.isoformat() if result.sent_at else None,
        "thread_mode": result.thread_mode,
        "query_id": result.query_id,
        "reply_to_message_id": result.reply_to_message_id,
        "conversation_id": result.conversation_id,
        "attachments": result.attachments,
        "idempotent_replay": result.idempotent_replay,
    }
    headers = {CORRELATION_ID_HEADER: correlation_id}
    if result.idempotent_replay:
        headers[IDEMPOTENT_REPLAY_HEADER] = "true"
    return JSONResponse(content=body, status_code=status_code, headers=headers)


# ---------------------------------------------------------------------
# POST /admin/email/send  — fresh email
# ---------------------------------------------------------------------


@router.post("/send")
@log_api_call
async def send_email(
    request: Request,
    to: str = Form(..., min_length=1, description="Comma-separated recipient emails"),
    subject: str = Form(..., min_length=1, max_length=500),
    body_html: str = Form(..., min_length=1),
    cc: str | None = Form(None, description="Comma-separated CC emails (optional)"),
    bcc: str | None = Form(None, description="Comma-separated BCC emails (optional)"),
    vendor_id: str | None = Form(None, description="Salesforce vendor id (optional, audit-only)"),
    query_id: str | None = Form(None, description="Existing VQ-YYYY-NNNN to link this send to (optional)"),
    files: list[UploadFile] = File(
        default=[],
        description="Optional attachments. Up to 10 files, 25 MB each, 50 MB total.",
    ),
) -> JSONResponse:
    """Send a fresh admin email (no thread).

    Admin is authenticated via the standard Bearer JWT middleware;
    role must be ADMIN. Returns 200 with the outbound_id on success.
    """
    _require_admin(request)
    service = _service(request)

    correlation_id = _correlation_id(request)
    request_id = request.headers.get(REQUEST_ID_HEADER)

    to_list = _split_csv(to)
    if not to_list:
        raise HTTPException(
            status_code=400,
            detail="At least one recipient is required",
        )

    try:
        result = await service.send(
            to=to_list,
            cc=_split_csv(cc),
            bcc=_split_csv(bcc),
            subject=subject,
            body_html=body_html,
            files=_real_files(files),
            vendor_id=_clean_optional(vendor_id),
            query_id=_clean_optional(query_id),
            actor=_actor(request),
            client_request_id=request_id,
            correlation_id=correlation_id,
        )
    except AttachmentRejectedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AdminEmailQueryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AdminEmailError as exc:
        # 409 for the explicit idempotency-mismatch sentinel,
        # 502 for any other underlying Graph failure.
        if "different content" in str(exc):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return _result_to_response(result, correlation_id)


# ---------------------------------------------------------------------
# POST /admin/email/queries/{query_id}/reply  — threaded reply
# ---------------------------------------------------------------------


@router.post("/queries/{query_id}/reply")
@log_api_call
async def reply_to_query(
    request: Request,
    query_id: str,
    body_html: str = Form(..., min_length=1),
    cc: str | None = Form(None, description="Comma-separated CC emails (optional)"),
    bcc: str | None = Form(None, description="Comma-separated BCC emails (optional)"),
    to_override: str | None = Form(
        None,
        description="Comma-separated emails. Defaults to the original sender.",
    ),
    reply_to_message_id: str | None = Form(
        None,
        description=(
            "Pin the reply to a specific message in the trail. "
            "Defaults to the latest inbound message on the conversation."
        ),
    ),
    files: list[UploadFile] = File(
        default=[],
        description="Optional attachments. Up to 10 files, 25 MB each, 50 MB total.",
    ),
) -> JSONResponse:
    """Reply on the existing email trail attached to ``query_id``.

    Vendor receives the email inside the same conversation/trail as
    the original — Graph's /messages/{id}/reply preserves
    conversationId, In-Reply-To, and References headers.
    """
    _require_admin(request)
    service = _service(request)

    correlation_id = _correlation_id(request)
    request_id = request.headers.get(REQUEST_ID_HEADER)

    try:
        result = await service.reply_to_query(
            query_id,
            body_html=body_html,
            cc=_split_csv(cc),
            bcc=_split_csv(bcc),
            to_override=_split_csv(to_override) or None,
            files=_real_files(files),
            reply_to_message_id_override=_clean_optional(reply_to_message_id),
            actor=_actor(request),
            client_request_id=request_id,
            correlation_id=correlation_id,
        )
    except AttachmentRejectedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AdminEmailQueryNotFoundError as exc:
        # not_found -> 404, anything else (no_trail, override mismatch) -> 422.
        status = 404 if exc.reason == "not_found" else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except AdminEmailError as exc:
        if "different content" in str(exc):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return _result_to_response(result, correlation_id)
