"""Module: api/routes/admin_queries.py

Admin-only query endpoints.

Mirrors the vendor-facing routes in api/routes/queries.py but without
ownership filtering — admins can read any query in the system, and
optionally scope the listing by vendor via a query string filter.

Routes:
  GET  /admin/queries                    — list all queries (or ?vendor_id=… filter)
  GET  /admin/queries/{id}               — query detail (no ownership check)
  GET  /admin/queries/{id}/trail         — full pipeline trail

The split (admin vs vendor) is intentional:
  * Each route has a single security stance — vendor routes always
    enforce JWT ownership, admin routes always skip it. No more
    "if is_admin:" branching inside a polymorphic handler.
  * Matches the existing /admin/* convention used by the rest of the
    admin features (dashboard, triage, drafts, vendors, ops, …).
  * Lets us require the ADMIN role at the route level via a dependency
    instead of inside every handler.

Usage:
    from api.routes.admin_queries import router as admin_queries_router
    app.include_router(admin_queries_router)
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Query, Request

from utils.decorators import log_api_call

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin-queries"])


def _require_admin(request: Request) -> None:
    """Reject the request unless the JWT carries the ADMIN role.

    Raised inside the handler rather than as a dependency to keep the
    route signatures minimal — this module ships no other roles.
    """
    role = getattr(request.state, "role", None)
    if role != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin role required")


@router.get("/queries")
@log_api_call
async def list_all_queries(
    request: Request,
    vendor_id: str | None = Query(
        None,
        description=(
            "Optional filter to scope the listing to a single vendor. "
            "Omit to return queries for all vendors."
        ),
    ),
) -> dict:
    """List queries across all vendors (admin view).

    Returns workflow.case_execution rows joined with intake.portal_queries
    so the response carries both workflow state and submission details.
    Ordered by creation date (newest first).
    """
    _require_admin(request)

    postgres = request.app.state.postgres
    if postgres is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    base_select = (
        "SELECT ce.query_id, ce.status, ce.source, ce.processing_path, "
        "       ce.vendor_id, ce.created_at, ce.updated_at, "
        "       pq.subject, pq.query_type, pq.priority, "
        "       pq.reference_number, pq.sla_deadline "
        "FROM workflow.case_execution ce "
        "LEFT JOIN intake.portal_queries pq ON ce.query_id = pq.query_id "
    )

    if vendor_id:
        rows = await postgres.fetch(
            base_select
            + "WHERE ce.vendor_id = $1 "
            + "ORDER BY ce.created_at DESC",
            vendor_id,
        )
    else:
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


@router.get("/queries/{query_id}")
@log_api_call
async def get_query_detail_admin(
    request: Request,
    query_id: str,
) -> dict:
    """Get the detail for any query (no ownership check)."""
    _require_admin(request)

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
        "WHERE ce.query_id = $1",
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
async def get_query_trail_admin(
    request: Request,
    query_id: str,
) -> dict:
    """Return the full pipeline trail for any query (admin view).

    Reads from `audit.action_log` via ExecutionTrailService — same
    underlying source as the vendor route, just without the ownership
    filter. Returns a 404 if the query doesn't exist at all.
    """
    _require_admin(request)

    postgres = request.app.state.postgres
    trail_service = getattr(request.app.state, "trail_service", None)
    if postgres is None or trail_service is None:
        raise HTTPException(status_code=503, detail="Trail service unavailable")

    # Confirm the query exists before exposing audit rows for an unknown id.
    exists_row = await postgres.fetchrow(
        "SELECT 1 FROM workflow.case_execution WHERE query_id = $1",
        query_id,
    )
    if exists_row is None:
        raise HTTPException(status_code=404, detail="Query not found")

    events = await trail_service.get_trail(query_id)
    return {"events": events}
