"""Module: api/routes/portal_dashboard.py

FastAPI routes for the Vendor Portal Dashboard KPIs.

Provides aggregate query statistics for a vendor's portal
dashboard — total queries, open count, resolved count, and
average resolution time.

Usage:
    from api.routes.portal_dashboard import router as portal_dashboard_router
    app.include_router(portal_dashboard_router)
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Header, HTTPException, Request

from utils.decorators import log_api_call

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["portal-dashboard"])

# Statuses considered "open" (not yet resolved or closed)
_OPEN_STATUSES = (
    "RECEIVED",
    "ANALYZING",
    "ROUTING",
    "DRAFTING",
    "VALIDATING",
    "SENDING",
    "AWAITING_HUMAN_REVIEW",
    "AWAITING_TEAM_RESOLUTION",
)

_RESOLVED_STATUSES = ("RESOLVED", "CLOSED")


@router.get("/dashboard/kpis")
@log_api_call
async def get_kpis(
    request: Request,
    x_vendor_id: str = Header(
        ...,
        description="Vendor ID to filter KPIs. Example: hexaware",
        alias="X-Vendor-ID",
    ),
) -> dict:
    """Get dashboard KPIs for a vendor.

    Returns aggregate counts grouped by query status, plus
    a simple average resolution time estimate.
    """
    postgres = request.app.state.postgres
    if postgres is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # Get counts grouped by status
    rows = await postgres.fetch(
        "SELECT status, COUNT(*) as count "
        "FROM workflow.case_execution "
        "WHERE vendor_id = $1 "
        "GROUP BY status",
        x_vendor_id,
    )

    total_queries = 0
    open_queries = 0
    resolved_queries = 0

    for row in rows:
        count = row["count"]
        status = row["status"]
        total_queries += count

        if status in _OPEN_STATUSES:
            open_queries += count
        elif status in _RESOLVED_STATUSES:
            resolved_queries += count

    # Average resolution time — hours between created_at and updated_at
    # for resolved/closed queries. Simple estimate for the dashboard.
    avg_row = await postgres.fetchrow(
        "SELECT AVG(EXTRACT(EPOCH FROM (updated_at - created_at)) / 3600) "
        "    as avg_hours "
        "FROM workflow.case_execution "
        "WHERE vendor_id = $1 AND status IN ('RESOLVED', 'CLOSED')",
        x_vendor_id,
    )

    avg_resolution_hours = 0.0
    if avg_row and avg_row["avg_hours"] is not None:
        avg_resolution_hours = round(float(avg_row["avg_hours"]), 1)

    return {
        "open_queries": open_queries,
        "resolved_queries": resolved_queries,
        "avg_resolution_hours": avg_resolution_hours,
        "total_queries": total_queries,
    }
