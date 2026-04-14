"""Module: api/routes/dashboard.py

FastAPI routes for the Email Dashboard API.

Read-only endpoints that serve email data for the frontend
dashboard. All data comes from PostgreSQL via the
EmailDashboardService — no writes, no mutations.

Endpoints:
    GET /emails           — Paginated list of email chains
    GET /emails/stats     — Aggregate dashboard statistics
    GET /emails/{query_id} — Single email chain detail
    GET /emails/{query_id}/attachments/{attachment_id}/download
                          — Presigned S3 download URL

Usage:
    from api.routes.dashboard import router as dashboard_router
    app.include_router(dashboard_router)
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Query, Request

from services.email_dashboard import EmailDashboardService
from utils.decorators import log_api_call
from utils.helpers import IdGenerator

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/emails", tags=["email-dashboard"])

# Valid filter/sort values for input validation
_VALID_STATUSES = {"New", "Reopened", "Resolved"}
_VALID_PRIORITIES = {"High", "Medium", "Low"}
_VALID_SORT_FIELDS = {"timestamp", "status", "priority"}
_VALID_SORT_ORDERS = {"asc", "desc"}


def _get_correlation_id(request: Request) -> str:
    """Extract correlation_id from header or generate a new one."""
    return (
        request.headers.get("X-Correlation-ID")
        or IdGenerator.generate_correlation_id()
    )


def _get_service(request: Request) -> EmailDashboardService:
    """Get the dashboard service from app state."""
    service = getattr(request.app.state, "dashboard_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Email dashboard service is not available",
        )
    return service


@router.get("")
@log_api_call
async def list_email_chains(
    request: Request,
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    status: str | None = Query(default=None, description="Filter: New, Reopened, Resolved"),
    priority: str | None = Query(default=None, description="Filter: High, Medium, Low"),
    search: str | None = Query(default=None, description="Search in subject and sender email"),
    sort_by: str = Query(default="timestamp", description="Sort: timestamp, status, priority"),
    sort_order: str = Query(default="desc", description="Direction: asc or desc"),
) -> dict:
    """List email chains with pagination, filtering, and sorting.

    Groups emails by conversation thread. Each chain includes
    all emails in the thread, workflow status, and priority.

    Returns:
        Paginated list of email chains.
    """
    # Validate enum parameters
    if status and status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status filter: '{status}'. Must be one of: {', '.join(sorted(_VALID_STATUSES))}",
        )
    if priority and priority not in _VALID_PRIORITIES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid priority filter: '{priority}'. Must be one of: {', '.join(sorted(_VALID_PRIORITIES))}",
        )
    if sort_by not in _VALID_SORT_FIELDS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid sort_by: '{sort_by}'. Must be one of: {', '.join(sorted(_VALID_SORT_FIELDS))}",
        )
    if sort_order not in _VALID_SORT_ORDERS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid sort_order: '{sort_order}'. Must be 'asc' or 'desc'",
        )

    correlation_id = _get_correlation_id(request)
    service = _get_service(request)

    result = await service.list_email_chains(
        page=page,
        page_size=page_size,
        status=status,
        priority=priority,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        correlation_id=correlation_id,
    )

    return result.model_dump(mode="json")


@router.get("/stats")
@log_api_call
async def get_email_stats(request: Request) -> dict:
    """Get aggregate dashboard statistics for email-sourced queries.

    Returns total counts, status breakdown, priority breakdown,
    and time-based counts (today, this week).
    """
    correlation_id = _get_correlation_id(request)
    service = _get_service(request)

    result = await service.get_stats(correlation_id=correlation_id)
    return result.model_dump(mode="json")


@router.get("/{query_id}")
@log_api_call
async def get_email_chain(request: Request, query_id: str) -> dict:
    """Get a single email chain by query_id.

    If the email belongs to a conversation thread, returns all
    emails in that thread. Otherwise returns just the single email.

    Returns:
        Email chain with all messages, status, and priority.
        404 if query_id not found.
    """
    correlation_id = _get_correlation_id(request)
    service = _get_service(request)

    result = await service.get_email_chain(
        query_id, correlation_id=correlation_id
    )

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Email chain not found for query_id: {query_id}",
        )

    return result.model_dump(mode="json")


@router.get("/{query_id}/attachments/{attachment_id}/download")
@log_api_call
async def download_attachment(
    request: Request,
    query_id: str,
    attachment_id: str,
) -> dict:
    """Generate a presigned S3 download URL for an attachment.

    The query_id in the path is for URL consistency but the
    lookup is done by attachment_id (which is globally unique).

    Returns:
        Presigned URL valid for 1 hour.
        404 if attachment not found or has no S3 key.
    """
    correlation_id = _get_correlation_id(request)
    service = _get_service(request)

    result = await service.get_attachment_download(
        attachment_id, correlation_id=correlation_id
    )

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Attachment not found: {attachment_id}",
        )

    return result.model_dump(mode="json")
