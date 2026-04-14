"""Vendor management endpoints for VQMS.

Full CRUD operations on Salesforce Vendor_Account__c records.
All endpoints require ADMIN role — enforced by _require_admin().

GET    /vendors              — List all active vendors
POST   /vendors              — Create a new vendor (auto-generates V-XXX)
PUT    /vendors/{vendor_id}  — Update vendor fields
DELETE /vendors/{vendor_id}  — Delete a vendor
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from adapters.salesforce import SalesforceConnectorError
from models.vendor import (
    VendorAccountData,
    VendorCreateRequest,
    VendorCreateResult,
    VendorDeleteResult,
    VendorUpdateRequest,
    VendorUpdateResult,
)
from utils.decorators import log_api_call
from utils.helpers import IdGenerator

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/vendors", tags=["vendors"])


def _require_admin(request: Request) -> None:
    """Check that the authenticated user has the ADMIN role.

    The AuthMiddleware already decoded the JWT and set
    request.state.role. This function just checks the value.

    Raises:
        HTTPException 403 if the user is not an ADMIN.
    """
    role = getattr(request.state, "role", None)
    if role != "ADMIN":
        raise HTTPException(
            status_code=403,
            detail="Admin access required. Your role: "
            + (role or "unauthenticated"),
        )


# ---------------------------------------------------------------
# GET /vendors — List all active vendors
# ---------------------------------------------------------------

@router.get("")
@log_api_call
async def get_all_vendors(request: Request) -> list[VendorAccountData]:
    """Get all active vendors from Salesforce.

    Requires ADMIN role. Queries the Salesforce Vendor_Account__c
    custom object filtered by Vendor_Status__c = 'Active'.
    """
    _require_admin(request)
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


# ---------------------------------------------------------------
# POST /vendors — Create a new vendor
# ---------------------------------------------------------------

@router.post("", status_code=201)
@log_api_call
async def create_vendor(
    request: Request,
    create_request: VendorCreateRequest,
) -> VendorCreateResult:
    """Create a new Vendor_Account__c record in Salesforce.

    Requires ADMIN role. Auto-generates the next Vendor_ID__c
    by finding the current highest V-XXX number and adding 1.

    Example: If the highest existing vendor is V-025, the new
    vendor gets V-026.
    """
    _require_admin(request)
    correlation_id = IdGenerator.generate_correlation_id()

    # Convert Python field names to Salesforce API field names
    sf_fields = create_request.to_salesforce_fields()

    try:
        salesforce = request.app.state.salesforce
        result = await salesforce.create_vendor_account(
            create_data=sf_fields,
            correlation_id=correlation_id,
        )
    except SalesforceConnectorError as exc:
        logger.error(
            "Failed to create vendor in Salesforce",
            name=create_request.name,
            error=str(exc),
            correlation_id=correlation_id,
        )
        return JSONResponse(
            status_code=502,
            content={"detail": f"Salesforce create failed: {exc}"},
        )

    # Build VendorAccountData from the full record fetched back
    vendor_data = None
    vendor_record = result.get("vendor_record")
    if vendor_record and vendor_record.get("id"):
        vendor_data = VendorAccountData(**vendor_record)

    return VendorCreateResult(
        success=result["success"],
        salesforce_id=result["salesforce_id"],
        vendor_id=result["vendor_id"],
        name=result["name"],
        message=f"Vendor '{result['name']}' created with ID {result['vendor_id']}",
        vendor=vendor_data,
    )


# ---------------------------------------------------------------
# PUT /vendors/{vendor_id} — Update vendor fields
# ---------------------------------------------------------------

@router.put("/{vendor_id}")
@log_api_call
async def update_vendor(
    vendor_id: str,
    update_request: VendorUpdateRequest,
    request: Request,
) -> VendorUpdateResult:
    """Update a vendor's fields in Salesforce.

    Requires ADMIN role. Accepts either a Salesforce record ID
    or a Vendor_ID__c code (V-001).
    At least one field must be provided.
    """
    _require_admin(request)
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

    # Build VendorAccountData from the full record fetched back
    vendor_data = None
    vendor_record = result.get("vendor_record")
    if vendor_record and vendor_record.get("id"):
        vendor_data = VendorAccountData(**vendor_record)

    return VendorUpdateResult(
        success=result["success"],
        vendor_id=result["vendor_id"],
        updated_fields=result["updated_fields"],
        message=f"Updated {len(result['updated_fields'])} field(s) for vendor {vendor_id}",
        vendor=vendor_data,
    )


# ---------------------------------------------------------------
# DELETE /vendors/{vendor_id} — Delete a vendor
# ---------------------------------------------------------------

@router.delete("/{vendor_id}")
@log_api_call
async def delete_vendor(
    vendor_id: str,
    request: Request,
) -> VendorDeleteResult:
    """Delete a Vendor_Account__c record from Salesforce.

    Requires ADMIN role. Accepts either a Salesforce record ID
    or a Vendor_ID__c code (V-001).

    WARNING: This permanently deletes the Vendor_Account__c record
    from Salesforce. Use with caution.
    """
    _require_admin(request)
    correlation_id = IdGenerator.generate_correlation_id()

    try:
        salesforce = request.app.state.salesforce
        result = await salesforce.delete_vendor_account(
            vendor_id_field=vendor_id,
            correlation_id=correlation_id,
        )
    except SalesforceConnectorError as exc:
        logger.error(
            "Failed to delete vendor from Salesforce",
            vendor_id=vendor_id,
            error=str(exc),
            correlation_id=correlation_id,
        )
        return JSONResponse(
            status_code=502,
            content={"detail": f"Salesforce delete failed: {exc}"},
        )

    return VendorDeleteResult(
        success=result["success"],
        vendor_id=result["vendor_id"],
        message=f"Vendor {vendor_id} deleted successfully",
    )
