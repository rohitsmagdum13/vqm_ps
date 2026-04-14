"""Vendor management endpoints for VQMS.

GET  /vendors              — List all active vendors from Salesforce
PUT  /vendors/{vendor_id}  — Update a vendor's fields in Salesforce
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from adapters.salesforce import SalesforceConnectorError
from models.vendor import VendorAccountData, VendorUpdateRequest, VendorUpdateResult
from utils.decorators import log_api_call
from utils.helpers import IdGenerator

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/vendors", tags=["vendors"])


@router.get("")
@log_api_call
async def get_all_vendors(request: Request) -> list[VendorAccountData]:
    """Get all active vendors from Salesforce."""
    if not getattr(request.state, "is_authenticated", False):
        return JSONResponse(
            status_code=401,
            content={"detail": "Not authenticated"},
        )

    correlation_id = IdGenerator.generate_correlation_id()

    try:
        salesforce = request.app.state.salesforce
        raw_vendors = await salesforce.get_all_active_vendors(
            correlation_id=correlation_id,
        )
    except SalesforceConnectorError as exc:
        logger.error(
            "Failed to fetch vendors from Salesforce",
            error=str(exc),
            correlation_id=correlation_id,
        )
        return JSONResponse(
            status_code=502,
            content={"detail": "Salesforce query failed"},
        )

    return [VendorAccountData(**vendor) for vendor in raw_vendors]


@router.put("/{vendor_id}")
@log_api_call
async def update_vendor(
    vendor_id: str,
    update_request: VendorUpdateRequest,
    request: Request,
) -> VendorUpdateResult:
    """Update a vendor's fields in Salesforce."""
    if not getattr(request.state, "is_authenticated", False):
        return JSONResponse(
            status_code=401,
            content={"detail": "Not authenticated"},
        )

    correlation_id = IdGenerator.generate_correlation_id()

    sf_fields = update_request.to_salesforce_fields()

    try:
        salesforce = request.app.state.salesforce
        result = await salesforce.update_vendor_account(
            vendor_id_field=vendor_id,
            update_data=sf_fields,
            correlation_id=correlation_id,
        )
    except SalesforceConnectorError as exc:
        logger.error(
            "Failed to update vendor in Salesforce",
            vendor_id=vendor_id,
            error=str(exc),
            correlation_id=correlation_id,
        )
        return JSONResponse(
            status_code=502,
            content={"detail": f"Salesforce update failed: {exc}"},
        )

    return VendorUpdateResult(
        success=result["success"],
        vendor_id=result["vendor_id"],
        updated_fields=result["updated_fields"],
        message=f"Updated {len(result['updated_fields'])} field(s) for vendor {vendor_id}",
    )
