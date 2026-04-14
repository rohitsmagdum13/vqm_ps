"""Module: models/vendor.py

Pydantic models for vendor profiles and vendor matching.

Vendors are the external companies that submit queries.
Each vendor has a tier (Platinum/Gold/Silver/Bronze) that
determines SLA targets and priority multipliers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VendorTier(BaseModel):
    """Vendor service tier with SLA and priority settings.

    Tiers determine how quickly we must respond and how
    the routing engine prioritizes the query.
    """

    model_config = ConfigDict(frozen=True)

    tier_name: Literal["PLATINUM", "GOLD", "SILVER", "BRONZE"] = Field(
        description="Vendor tier classification",
    )
    sla_hours: int = Field(description="Maximum response time in hours for this tier")
    priority_multiplier: float = Field(description="Priority weight multiplier (higher = faster handling)")


class VendorProfile(BaseModel):
    """Full vendor profile loaded from Salesforce.

    Cached in PostgreSQL with a 1-hour TTL to reduce
    Salesforce API calls.
    """

    model_config = ConfigDict(frozen=True)

    vendor_id: str = Field(description="Salesforce vendor/account ID")
    vendor_name: str = Field(description="Company name")
    tier: VendorTier = Field(description="Service tier with SLA settings")
    primary_contact_email: str = Field(description="Main contact email address")
    is_active: bool = Field(description="Whether the vendor account is active")
    account_manager: str | None = Field(default=None, description="Assigned account manager name")
    cached_at: datetime | None = Field(default=None, description="When this profile was cached (IST)")
    expires_at: datetime | None = Field(default=None, description="Cache expiry time (IST)")


class VendorMatch(BaseModel):
    """Result of vendor identification from a sender email.

    The email path tries 3 methods to identify the vendor:
    1. Exact email match in Salesforce contacts
    2. Email domain extraction from email body
    3. Fuzzy name match on company name
    """

    model_config = ConfigDict(frozen=True)

    vendor_id: str = Field(description="Matched vendor ID")
    vendor_name: str = Field(description="Matched vendor name")
    match_method: Literal["exact_email", "body_extraction", "fuzzy_name", "unresolved"] = Field(
        description="Which method succeeded",
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Match confidence score")
    matched_contact_email: str | None = Field(default=None, description="The contact email that matched")


# --- Vendor CRUD Models (merged from local_vqm) ---
# These models are used by the vendor management portal endpoints
# (GET /vendors, PUT /vendors/{vendor_id}). They map to the
# Salesforce STANDARD Account object — NOT the custom
# Vendor_Account__c object used by the AI pipeline above.


class VendorAccountData(BaseModel):
    """Full vendor record from the Salesforce standard Account object.

    Returned by GET /vendors. Contains all fields that the portal
    displays in the vendor management table.
    """

    id: str = Field(description="Salesforce Account record ID")
    name: str = Field(description="Account name (company name)")
    vendor_id: str | None = Field(default=None, description="Custom Vendor_ID__c field on Account")
    website: str | None = Field(default=None, description="Company website URL")
    vendor_tier: str | None = Field(default=None, description="Vendor tier (Vendor_Tier__c)")
    category: str | None = Field(default=None, description="Vendor category (Category__c)")
    payment_terms: str | None = Field(default=None, description="Payment terms (Payment_Terms__c)")
    annual_revenue: float | None = Field(default=None, description="Annual revenue")
    sla_response_hours: float | None = Field(default=None, description="SLA response time in hours")
    sla_resolution_days: float | None = Field(default=None, description="SLA resolution time in days")
    vendor_status: str | None = Field(default=None, description="Vendor status: Active, Inactive")
    onboarded_date: str | None = Field(default=None, description="Date vendor was onboarded")
    billing_city: str | None = Field(default=None, description="BillingCity")
    billing_state: str | None = Field(default=None, description="BillingState")
    billing_country: str | None = Field(default=None, description="BillingCountry")


VENDOR_UPDATABLE_FIELDS: set[str] = {
    "Website",
    "Vendor_Tier__c",
    "Category__c",
    "Payment_Terms__c",
    "AnnualRevenue",
    "SLA_Response_Hours__c",
    "SLA_Resolution_Days__c",
    "Vendor_Status__c",
    "Onboarded_Date__c",
    "BillingCity",
    "BillingState",
    "BillingCountry",
}


class VendorUpdateRequest(BaseModel):
    """Request body for PUT /vendors/{vendor_id}.

    At least one field must be provided.
    """

    website: str | None = Field(default=None, description="Company website URL")
    vendor_tier: str | None = Field(default=None, description="Vendor tier")
    category: str | None = Field(default=None, description="Vendor category")
    payment_terms: str | None = Field(default=None, description="Payment terms")
    annual_revenue: float | None = Field(default=None, description="Annual revenue")
    sla_response_hours: float | None = Field(default=None, description="SLA response hours")
    sla_resolution_days: float | None = Field(default=None, description="SLA resolution days")
    vendor_status: str | None = Field(default=None, description="Vendor status")
    onboarded_date: str | None = Field(default=None, description="Onboarded date")
    billing_city: str | None = Field(default=None, description="Billing city")
    billing_state: str | None = Field(default=None, description="Billing state")
    billing_country: str | None = Field(default=None, description="Billing country")

    @model_validator(mode="after")
    def at_least_one_field(self) -> VendorUpdateRequest:
        """Ensure at least one field is provided for update."""
        values = self.model_dump(exclude_none=True)
        if not values:
            msg = "At least one field must be provided for update"
            raise ValueError(msg)
        return self

    def to_salesforce_fields(self) -> dict:
        """Convert snake_case Python fields to Salesforce API field names."""
        field_mapping = {
            "website": "Website",
            "vendor_tier": "Vendor_Tier__c",
            "category": "Category__c",
            "payment_terms": "Payment_Terms__c",
            "annual_revenue": "AnnualRevenue",
            "sla_response_hours": "SLA_Response_Hours__c",
            "sla_resolution_days": "SLA_Resolution_Days__c",
            "vendor_status": "Vendor_Status__c",
            "onboarded_date": "Onboarded_Date__c",
            "billing_city": "BillingCity",
            "billing_state": "BillingState",
            "billing_country": "BillingCountry",
        }
        result = {}
        for python_name, sf_name in field_mapping.items():
            value = getattr(self, python_name)
            if value is not None:
                result[sf_name] = value
        return result


class VendorUpdateResult(BaseModel):
    """Response body for PUT /vendors/{vendor_id}."""

    success: bool = Field(description="Whether the update succeeded")
    vendor_id: str = Field(description="The Vendor_ID__c that was updated")
    updated_fields: list[str] = Field(description="List of Salesforce field names that were updated")
    message: str = Field(description="Human-readable result message")
