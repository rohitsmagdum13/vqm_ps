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
from fastapi import APIRouter, Header, HTTPException, Request

from models.query import QuerySubmission
from utils.decorators import log_api_call
from utils.exceptions import DuplicateQueryError

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["queries"])


@router.post("/queries", status_code=201)
@log_api_call
async def submit_query(
    request: Request,
    submission: QuerySubmission,
    x_vendor_id: str = Header(
        ...,
        description="Vendor ID (from JWT in production). Example: 001al00002Ie1zsAAB",
        alias="X-Vendor-ID",
    ),
    x_correlation_id: str | None = Header(
        None,
        description="Optional correlation ID for tracing. Auto-generated if not provided.",
        alias="X-Correlation-ID",
    ),
) -> dict:
    """Submit a vendor query from the portal.

    **How to test in Swagger UI:**

    1. Fill in `X-Vendor-ID` header (e.g., `001al00002Ie1zsAAB`)
    2. Fill in the request body with query details
    3. Click Execute

    Returns:
    - **201**: `{"query_id": "VQ-2026-XXXX", "status": "RECEIVED"}`
    - **409**: Duplicate submission (same vendor + subject + description)
    - **422**: Validation error (subject too short, description too short, etc.)
    """
    portal_intake = request.app.state.portal_intake
    if portal_intake is None:
        raise HTTPException(
            status_code=503,
            detail="Portal Intake Service unavailable — check PostgreSQL/SQS connection",
        )

    try:
        payload = await portal_intake.submit_query(
            submission, x_vendor_id, correlation_id=x_correlation_id
        )
    except DuplicateQueryError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Duplicate query: {exc.message_id}",
        ) from exc

    return {"query_id": payload.query_id, "status": "RECEIVED"}


@router.get("/queries/{query_id}")
@log_api_call
async def get_query_status(
    request: Request,
    query_id: str,
    x_vendor_id: str = Header(
        ...,
        description="Vendor ID to verify ownership. Example: 001al00002Ie1zsAAB",
        alias="X-Vendor-ID",
    ),
) -> dict:
    """Get the status of a submitted query.

    The vendor can only see their own queries — vendor_id from the
    header must match the query's vendor_id in the database.

    **How to test in Swagger UI:**

    1. Fill in the `query_id` path parameter (e.g., `VQ-2026-0042`)
    2. Fill in `X-Vendor-ID` header with the same vendor used to submit
    3. Click Execute
    """
    postgres = request.app.state.postgres
    if postgres is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    row = await postgres.fetchrow(
        "SELECT query_id, status, source, processing_path, "
        "       created_at, updated_at "
        "FROM workflow.case_execution "
        "WHERE query_id = $1 AND vendor_id = $2",
        query_id,
        x_vendor_id,
    )

    if row is None:
        raise HTTPException(status_code=404, detail="Query not found")

    return {
        "query_id": row["query_id"],
        "status": row["status"],
        "source": row["source"],
        "processing_path": row.get("processing_path"),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }
