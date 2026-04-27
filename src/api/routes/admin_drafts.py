"""Admin draft-approval endpoints for VQMS.

Path A queries park at status ``PENDING_APPROVAL`` after the Delivery
node has created the ServiceNow ticket and stamped the real INC number
into the draft. These endpoints back the admin queue UI and the
approve / edit / reject actions:

GET    /admin/drafts                       — list every pending draft
GET    /admin/drafts/{query_id}            — one draft + analysis package
POST   /admin/drafts/{query_id}/approve    — send the persisted draft as-is
POST   /admin/drafts/{query_id}/edit-approve — overwrite then send
POST   /admin/drafts/{query_id}/reject     — record feedback, do not send

All endpoints require ADMIN role (matches the pattern in
:mod:`api.routes.vendors`).
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from services.draft_approval import (
    DraftApprovalError,
    DraftNotFoundError,
)
from utils.decorators import log_api_call
from utils.helpers import IdGenerator

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin/drafts", tags=["admin-drafts"])


def _require_admin(request: Request) -> None:
    """403 unless the JWT decoded by AuthMiddleware says ADMIN."""
    role = getattr(request.state, "role", None)
    if role != "ADMIN":
        raise HTTPException(
            status_code=403,
            detail="Admin access required. Your role: "
            + (role or "unauthenticated"),
        )


def _service(request: Request):
    """Pull DraftApprovalService off app.state or 503."""
    service = getattr(request.app.state, "draft_approval_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Draft Approval Service unavailable — check PostgreSQL "
                "and Graph API connections"
            ),
        )
    return service


def _actor(request: Request) -> str:
    """Best-effort identifier for the admin acting on the draft."""
    return (
        getattr(request.state, "user_email", None)
        or getattr(request.state, "user_id", None)
        or "admin"
    )


class EditApproveRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=500)
    body_html: str = Field(min_length=1)


class RejectRequest(BaseModel):
    feedback: str = Field(min_length=1, max_length=2000)


# ---------------------------------------------------------------
# GET /admin/drafts — pending list
# ---------------------------------------------------------------

@router.get("")
@log_api_call
async def list_pending_drafts(request: Request) -> dict:
    """Return every case currently waiting for admin approval."""
    _require_admin(request)
    items = await _service(request).list_pending()
    return {"drafts": items}


# ---------------------------------------------------------------
# GET /admin/drafts/{query_id} — one draft package
# ---------------------------------------------------------------

@router.get("/{query_id}")
@log_api_call
async def get_draft_detail(query_id: str, request: Request) -> dict:
    """Return the full draft + analysis + original-query package."""
    _require_admin(request)
    try:
        return await _service(request).get_detail(query_id)
    except DraftNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------
# POST /admin/drafts/{query_id}/approve — send as drafted
# ---------------------------------------------------------------

@router.post("/{query_id}/approve")
@log_api_call
async def approve_draft(query_id: str, request: Request) -> dict:
    """Send the persisted draft to the vendor and mark RESOLVED."""
    _require_admin(request)
    correlation_id = IdGenerator.generate_correlation_id()
    try:
        return await _service(request).approve(
            query_id,
            actor=_actor(request),
            correlation_id=correlation_id,
        )
    except DraftNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DraftApprovalError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ---------------------------------------------------------------
# POST /admin/drafts/{query_id}/edit-approve — overwrite then send
# ---------------------------------------------------------------

@router.post("/{query_id}/edit-approve")
@log_api_call
async def approve_draft_with_edits(
    query_id: str,
    payload: EditApproveRequest,
    request: Request,
) -> dict:
    """Overwrite the draft with admin edits and send."""
    _require_admin(request)
    correlation_id = IdGenerator.generate_correlation_id()
    try:
        return await _service(request).approve_with_edits(
            query_id,
            subject=payload.subject,
            body_html=payload.body_html,
            actor=_actor(request),
            correlation_id=correlation_id,
        )
    except DraftNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DraftApprovalError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ---------------------------------------------------------------
# POST /admin/drafts/{query_id}/reject — record feedback, no send
# ---------------------------------------------------------------

@router.post("/{query_id}/reject")
@log_api_call
async def reject_draft(
    query_id: str,
    payload: RejectRequest,
    request: Request,
) -> dict:
    """Reject the draft. Status flips to DRAFT_REJECTED, no email goes out."""
    _require_admin(request)
    correlation_id = IdGenerator.generate_correlation_id()
    try:
        return await _service(request).reject(
            query_id,
            feedback=payload.feedback,
            actor=_actor(request),
            correlation_id=correlation_id,
        )
    except DraftNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
