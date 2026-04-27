"""Module: api/routes/queries.py

FastAPI routes for VQMS query submission and status lookup.

Handles portal query submission (POST /queries) and query status
lookup (GET /queries/{id}).

POST /queries accepts multipart/form-data:
    submission  (form field, JSON-encoded QuerySubmission)
    files       (0..N file uploads — PDF, DOCX, XLSX, CSV, TXT, images)

All routes access connectors via request.app.state — simple
and explicit dependency injection for development mode.

Usage:
    from api.routes.queries import router
    app.include_router(router)
"""

from __future__ import annotations

import json

import structlog
from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from pydantic import ValidationError

from models.query import QuerySubmission
from utils.decorators import log_api_call
from utils.exceptions import DuplicateQueryError

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["queries"])


@router.get("/queries")
@log_api_call
async def list_queries(
    request: Request,
    x_vendor_id: str | None = Header(
        None,
        description=(
            "Vendor ID to filter queries. Required for VENDOR role. "
            "Optional for ADMIN role — when omitted, returns all queries."
        ),
        alias="X-Vendor-ID",
    ),
) -> dict:
    """List queries from workflow.case_execution.

    Behavior depends on the authenticated role:
    - ADMIN: Returns all queries when X-Vendor-ID is omitted; filters by
      vendor when provided.
    - VENDOR: Always filters by X-Vendor-ID (required).

    Used by the portal dashboard (vendor view) and the admin queries
    page (admin view). Ordered by creation date (newest first).
    """
    postgres = request.app.state.postgres
    if postgres is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    role = getattr(request.state, "role", None)
    is_admin = role == "ADMIN"

    # Vendors must filter by their own vendor_id; admins may view all.
    if not is_admin and not x_vendor_id:
        raise HTTPException(
            status_code=400,
            detail="X-Vendor-ID header is required for vendor accounts",
        )

    base_select = (
        "SELECT ce.query_id, ce.status, ce.source, ce.processing_path, "
        "       ce.vendor_id, ce.created_at, ce.updated_at, "
        "       pq.subject, pq.query_type, pq.priority, "
        "       pq.reference_number, pq.sla_deadline "
        "FROM workflow.case_execution ce "
        "LEFT JOIN intake.portal_queries pq ON ce.query_id = pq.query_id "
    )

    if x_vendor_id:
        # JOIN case_execution (workflow state) with portal_queries (intake data)
        # so the frontend gets both status and submission details in one call.
        # LEFT JOIN because email-path queries won't have portal_queries rows.
        rows = await postgres.fetch(
            base_select
            + "WHERE ce.vendor_id = $1 "
            + "ORDER BY ce.created_at DESC",
            x_vendor_id,
        )
    else:
        # Admin global view — no vendor filter.
        rows = await postgres.fetch(
            base_select + "ORDER BY ce.created_at DESC",
        )

    queries = [
        {
            "query_id": row["query_id"],
            "subject": row.get("subject"),
            "query_type": row.get("query_type"),
            "status": row["status"],
            "priority": row.get("priority"),
            "source": row["source"],
            "processing_path": row.get("processing_path"),
            "reference_number": row.get("reference_number"),
            "vendor_id": row.get("vendor_id"),
            "sla_deadline": str(row["sla_deadline"]) if row.get("sla_deadline") else None,
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }
        for row in rows
    ]

    return {"queries": queries}


@router.post("/queries", status_code=201)
@log_api_call
async def submit_query(
    request: Request,
    submission: str = Form(
        ...,
        description=(
            "JSON-encoded QuerySubmission: "
            '{"query_type":"INVOICE_PAYMENT","subject":"...","description":"...",'
            '"priority":"MEDIUM","reference_number":null}'
        ),
    ),
    files: list[UploadFile] = File(
        default=[],
        description="Optional attachments (PDF, DOCX, XLSX, CSV, TXT, PNG, JPG). Up to 10 files, 50 MB total.",
    ),
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
    """Submit a vendor query from the portal, with optional attachments.

    Accepts multipart/form-data:
        submission  (form field, JSON-encoded QuerySubmission)
        files       (0..N file uploads)

    Returns:
    - **201**: `{"query_id": "...", "status": "RECEIVED",
                 "attachments": [...], "extracted_entities": {...}}`
    - **409**: Duplicate submission
    - **422**: Validation error
    """
    portal_intake = request.app.state.portal_intake
    if portal_intake is None:
        raise HTTPException(
            status_code=503,
            detail="Portal Intake Service unavailable — check PostgreSQL/SQS connection",
        )

    # The wizard sends the structured fields as a single JSON form field
    # so we keep one Pydantic model for validation and don't need a
    # second flat-form schema.
    try:
        submission_data = json.loads(submission)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"submission field is not valid JSON: {exc.msg}",
        ) from exc

    try:
        submission_model = QuerySubmission(**submission_data)
    except ValidationError as exc:
        # Pydantic's errors() includes the original ValueError under
        # ctx, which is not JSON serializable. Strip ctx and keep just
        # what the client needs to fix their submission.
        safe_errors = [
            {k: v for k, v in err.items() if k != "ctx"} for err in exc.errors()
        ]
        raise HTTPException(status_code=422, detail=safe_errors) from exc

    # FastAPI passes an empty UploadFile when no files are sent and
    # default=[] is used; filter out anything without a filename so the
    # processor doesn't see phantom uploads.
    real_files = [f for f in files if f and f.filename]

    try:
        payload = await portal_intake.submit_query(
            submission_model,
            x_vendor_id,
            files=real_files,
            correlation_id=x_correlation_id,
        )
    except DuplicateQueryError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Duplicate query: {exc.message_id}",
        ) from exc

    return {
        "query_id": payload.query_id,
        "status": "RECEIVED",
        "created_at": str(payload.received_at),
        "attachments": [
            {
                "attachment_id": a.attachment_id,
                "filename": a.filename,
                "size_bytes": a.size_bytes,
                "extraction_status": a.extraction_status,
                "extraction_method": a.extraction_method,
            }
            for a in payload.attachments
        ],
        "extracted_entities": payload.metadata.get("extracted_entities", {}),
    }


@router.get("/queries/{query_id}")
@log_api_call
async def get_query_status(
    request: Request,
    query_id: str,
    x_vendor_id: str | None = Header(
        None,
        description=(
            "Vendor ID to verify ownership. Required for VENDOR role. "
            "Optional for ADMIN role — admins can view any query."
        ),
        alias="X-Vendor-ID",
    ),
) -> dict:
    """Get the status of a submitted query.

    Vendors can only see their own queries — vendor_id from the header
    must match the query's vendor_id. Admins can fetch any query
    without supplying a vendor_id.

    **How to test in Swagger UI:**

    1. Fill in the `query_id` path parameter (e.g., `VQ-2026-0042`)
    2. Fill in `X-Vendor-ID` header (vendors only)
    3. Click Execute
    """
    postgres = request.app.state.postgres
    if postgres is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    role = getattr(request.state, "role", None)
    is_admin = role == "ADMIN"

    if not is_admin and not x_vendor_id:
        raise HTTPException(
            status_code=400,
            detail="X-Vendor-ID header is required for vendor accounts",
        )

    base_select = (
        "SELECT ce.query_id, ce.status, ce.source, ce.processing_path, "
        "       ce.vendor_id, ce.created_at, ce.updated_at, "
        "       pq.subject, pq.query_type, pq.description, "
        "       pq.priority, pq.reference_number, pq.sla_deadline "
        "FROM workflow.case_execution ce "
        "LEFT JOIN intake.portal_queries pq ON ce.query_id = pq.query_id "
    )

    if x_vendor_id:
        # JOIN to get both workflow state and portal submission details
        row = await postgres.fetchrow(
            base_select + "WHERE ce.query_id = $1 AND ce.vendor_id = $2",
            query_id,
            x_vendor_id,
        )
    else:
        # Admin lookup — no ownership check.
        row = await postgres.fetchrow(
            base_select + "WHERE ce.query_id = $1",
            query_id,
        )

    if row is None:
        raise HTTPException(status_code=404, detail="Query not found")

    return {
        "query_id": row["query_id"],
        "subject": row.get("subject"),
        "query_type": row.get("query_type"),
        "description": row.get("description"),
        "status": row["status"],
        "priority": row.get("priority"),
        "source": row["source"],
        "processing_path": row.get("processing_path"),
        "reference_number": row.get("reference_number"),
        "vendor_id": row.get("vendor_id"),
        "sla_deadline": str(row["sla_deadline"]) if row.get("sla_deadline") else None,
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


@router.get("/queries/{query_id}/trail")
@log_api_call
async def get_query_trail(
    request: Request,
    query_id: str,
    x_vendor_id: str | None = Header(
        None,
        description=(
            "Vendor ID to verify ownership. Required for VENDOR role. "
            "Optional for ADMIN role — admins can view any query's trail."
        ),
        alias="X-Vendor-ID",
    ),
) -> dict:
    """Return the per-step pipeline trail for a query.

    One entry per `audit.action_log` row — intake, every LangGraph node,
    every LLM sub-call, admin actions, and closure milestones — ordered
    chronologically. The Angular query-detail page consumes this to
    render the live `<app-pipeline-timeline>`.
    """
    postgres = request.app.state.postgres
    trail_service = getattr(request.app.state, "trail_service", None)
    if postgres is None or trail_service is None:
        raise HTTPException(status_code=503, detail="Trail service unavailable")

    role = getattr(request.state, "role", None)
    is_admin = role == "ADMIN"

    if not is_admin and not x_vendor_id:
        raise HTTPException(
            status_code=400,
            detail="X-Vendor-ID header is required for vendor accounts",
        )

    # Vendors can only see trails for queries they own — verify ownership
    # before exposing the audit log. Admins skip the check.
    if not is_admin:
        owner_row = await postgres.fetchrow(
            "SELECT vendor_id FROM workflow.case_execution WHERE query_id = $1",
            query_id,
        )
        if owner_row is None:
            raise HTTPException(status_code=404, detail="Query not found")
        if owner_row["vendor_id"] != x_vendor_id:
            raise HTTPException(status_code=404, detail="Query not found")

    events = await trail_service.get_trail(query_id)
    return {"events": events}
