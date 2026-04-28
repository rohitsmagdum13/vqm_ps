"""Module: api/routes/queries.py

Vendor-facing query endpoints.

These routes are scoped to the logged-in vendor's data. The vendor_id
used for filtering and ownership checks comes EXCLUSIVELY from the JWT
claim (via auth middleware → request.state.vendor_id). No client-supplied
header or body field is trusted.

Routes:
  POST /queries                    — submit a new query (multipart)
  GET  /queries                    — list the vendor's own queries
  GET  /queries/{id}               — query detail (404 if not owned)
  GET  /queries/{id}/trail         — pipeline trail (404 if not owned)

Admin-side equivalents live in api/routes/admin_queries.py — they're
deliberately separate so each handler has a single security stance and
neither has to branch on `if is_admin:`.

POST /queries accepts multipart/form-data:
    submission  (form field, JSON-encoded QuerySubmission)
    files       (0..N file uploads — PDF, DOCX, XLSX, CSV, TXT, images)
"""

from __future__ import annotations

import json

import structlog
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import ValidationError

from models.query import QuerySubmission
from utils.decorators import log_api_call
from utils.exceptions import DuplicateQueryError

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["queries"])


def _require_vendor(request: Request) -> str:
    """Return the JWT-bound vendor_id, or reject if the caller can't act
    as a vendor.

    The middleware sets `request.state.role` and `request.state.vendor_id`
    from the JWT. Vendor handlers MUST NOT trust any header — that's the
    whole point of this split. ADMIN tokens are rejected (admins use the
    /admin/queries routes).
    """
    role = getattr(request.state, "role", None)
    if role != "VENDOR":
        # 403 (not 404) — the route exists, the caller just can't use it.
        raise HTTPException(
            status_code=403,
            detail="This endpoint is for vendor accounts. Admins should use /admin/queries.",
        )
    vendor_id = getattr(request.state, "vendor_id", None)
    if not vendor_id:
        # VENDOR token without a vendor_id claim — should be impossible
        # because the login gate enforces it, but fail closed if it ever
        # happens rather than returning everyone's data.
        raise HTTPException(
            status_code=403,
            detail="Vendor identity missing from token",
        )
    return vendor_id


@router.get("/queries")
@log_api_call
async def list_my_queries(request: Request) -> dict:
    """List the logged-in vendor's queries.

    The vendor_id comes from the JWT — no header is read or trusted.
    Ordered by creation date (newest first).
    """
    vendor_id = _require_vendor(request)

    postgres = request.app.state.postgres
    if postgres is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    rows = await postgres.fetch(
        "SELECT ce.query_id, ce.status, ce.source, ce.processing_path, "
        "       ce.vendor_id, ce.created_at, ce.updated_at, "
        "       pq.subject, pq.query_type, pq.priority, "
        "       pq.reference_number, pq.sla_deadline "
        "FROM workflow.case_execution ce "
        "LEFT JOIN intake.portal_queries pq ON ce.query_id = pq.query_id "
        "WHERE ce.vendor_id = $1 "
        "ORDER BY ce.created_at DESC",
        vendor_id,
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
) -> dict:
    """Submit a vendor query from the portal, with optional attachments.

    vendor_id is taken from the JWT — there is no X-Vendor-ID header in
    the contract. A vendor cannot submit a query on someone else's behalf.

    Returns:
    - **201**: `{"query_id": "...", "status": "RECEIVED",
                 "attachments": [...], "extracted_entities": {...}}`
    - **403**: Caller is not a vendor (admin trying to submit)
    - **409**: Duplicate submission
    - **422**: Validation error
    """
    vendor_id = _require_vendor(request)

    portal_intake = request.app.state.portal_intake
    if portal_intake is None:
        raise HTTPException(
            status_code=503,
            detail="Portal Intake Service unavailable — check PostgreSQL/SQS connection",
        )

    correlation_id = request.headers.get("X-Correlation-ID")

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
            vendor_id,
            files=real_files,
            correlation_id=correlation_id,
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
async def get_my_query(
    request: Request,
    query_id: str,
) -> dict:
    """Get the status of a query owned by the logged-in vendor.

    Returns 404 if the query doesn't exist OR belongs to a different
    vendor — never reveal that someone else's query exists.
    """
    vendor_id = _require_vendor(request)

    postgres = request.app.state.postgres
    if postgres is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    row = await postgres.fetchrow(
        "SELECT ce.query_id, ce.status, ce.source, ce.processing_path, "
        "       ce.vendor_id, ce.created_at, ce.updated_at, "
        "       pq.subject, pq.query_type, pq.description, "
        "       pq.priority, pq.reference_number, pq.sla_deadline "
        "FROM workflow.case_execution ce "
        "LEFT JOIN intake.portal_queries pq ON ce.query_id = pq.query_id "
        "WHERE ce.query_id = $1 AND ce.vendor_id = $2",
        query_id,
        vendor_id,
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
async def get_my_query_trail(
    request: Request,
    query_id: str,
) -> dict:
    """Return the pipeline trail for a query owned by the logged-in vendor.

    Verifies ownership before exposing the audit log. Returns 404 if the
    query doesn't exist OR belongs to a different vendor.
    """
    vendor_id = _require_vendor(request)

    postgres = request.app.state.postgres
    trail_service = getattr(request.app.state, "trail_service", None)
    if postgres is None or trail_service is None:
        raise HTTPException(status_code=503, detail="Trail service unavailable")

    owner_row = await postgres.fetchrow(
        "SELECT vendor_id FROM workflow.case_execution WHERE query_id = $1",
        query_id,
    )
    if owner_row is None or owner_row["vendor_id"] != vendor_id:
        # Same 404 for both "doesn't exist" and "belongs to someone else"
        # — never confirm or deny existence of foreign-vendor queries.
        raise HTTPException(status_code=404, detail="Query not found")

    events = await trail_service.get_trail(query_id)
    return {"events": events}
