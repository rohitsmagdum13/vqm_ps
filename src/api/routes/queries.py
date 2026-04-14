"""Module: api/routes/queries.py

FastAPI routes for VQMS query submission and status lookup.

Handles portal query submission (POST /queries) and query status
lookup (GET /queries/{id}).

All routes access connectors via request.app.state — simple
and explicit dependency injection for development mode.

Usage:
    from api.routes.queries import router
    app.include_router(router)
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request

from models.query import QuerySubmission
from utils.decorators import log_api_call
from utils.exceptions import DuplicateQueryError

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["queries"])


@router.post("/queries", status_code=201)
@log_api_call
async def submit_query(request: Request, submission: QuerySubmission) -> dict:
    """Submit a vendor query from the portal.

    The vendor_id is extracted from the X-Vendor-ID header.
    In production, this will come from the Cognito JWT claims.
    The correlation_id is extracted from X-Correlation-ID header
    or generated automatically.

    Returns:
        201 with {"query_id": "VQ-2026-XXXX", "status": "RECEIVED"}
        409 on duplicate submission
        422 on validation error (Pydantic handles this)
    """
    # Extract vendor_id from header (placeholder for JWT extraction)
    # SECURITY: vendor_id comes from auth header, NEVER from request body
    vendor_id = request.headers.get("X-Vendor-ID")
    if not vendor_id:
        raise HTTPException(status_code=400, detail="X-Vendor-ID header required")

    correlation_id = request.headers.get("X-Correlation-ID")

    portal_intake = request.app.state.portal_intake

    try:
        payload = await portal_intake.submit_query(
            submission, vendor_id, correlation_id=correlation_id
        )
    except DuplicateQueryError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Duplicate query: {exc.message_id}",
        ) from exc

    return {"query_id": payload.query_id, "status": "RECEIVED"}


@router.get("/queries/{query_id}")
@log_api_call
async def get_query_status(request: Request, query_id: str) -> dict:
    """Get the status of a submitted query.

    The vendor_id is extracted from the X-Vendor-ID header
    to ensure vendors can only see their own queries.

    Returns:
        200 with query status details
        404 if query not found or vendor mismatch
    """
    vendor_id = request.headers.get("X-Vendor-ID")
    if not vendor_id:
        raise HTTPException(status_code=400, detail="X-Vendor-ID header required")

    postgres = request.app.state.postgres

    row = await postgres.fetchrow(
        "SELECT query_id, status, source, created_at, updated_at "
        "FROM workflow.case_execution "
        "WHERE query_id = $1 AND vendor_id = $2",
        query_id,
        vendor_id,
    )

    if row is None:
        raise HTTPException(status_code=404, detail="Query not found")

    return {
        "query_id": row["query_id"],
        "status": row["status"],
        "source": row["source"],
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }
