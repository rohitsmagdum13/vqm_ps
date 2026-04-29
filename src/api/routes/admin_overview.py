"""Module: api/routes/admin_overview.py

Admin Operations Overview API.

A single read-only route that bundles every chart on the Operations
Overview screen into one response so the frontend renders in one
network round-trip instead of eight.

Routes:
  GET /admin/overview — full overview payload (admin only)

Usage:
    from api.routes.admin_overview import router as admin_overview_router
    app.include_router(admin_overview_router)
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request

from services.admin_overview import AdminOverviewService
from utils.decorators import log_api_call
from utils.helpers import IdGenerator

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin-overview"])


def _require_admin(request: Request) -> None:
    """Reject the request unless the JWT carries the ADMIN role."""
    role = getattr(request.state, "role", None)
    if role != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin role required")


def _correlation_id(request: Request) -> str:
    return (
        request.headers.get("X-Correlation-ID")
        or IdGenerator.generate_correlation_id()
    )


def _get_service(request: Request) -> AdminOverviewService:
    service = getattr(request.app.state, "admin_overview_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Admin overview service is not available",
        )
    return service


@router.get("/overview")
@log_api_call
async def get_overview(request: Request) -> dict:
    """Return the bundled Operations Overview payload.

    See models/admin_overview.py:AdminOverviewResponse for the full shape.
    Each section is independent — a slow query in one section will not
    blank out the others (the service swallows + returns zero defaults).
    """
    _require_admin(request)
    correlation_id = _correlation_id(request)
    service = _get_service(request)
    result = await service.get_overview(correlation_id=correlation_id)
    return result.model_dump(mode="json")
