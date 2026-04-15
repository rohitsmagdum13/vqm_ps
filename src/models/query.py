"""Module: models/query.py

Pydantic models for portal query submission and the unified query payload.

QuerySubmission is the input from the vendor portal wizard.
UnifiedQueryPayload is the normalized format that both email
and portal paths produce before entering the AI pipeline.

QUERY_TYPES defines the 12 official query categories used across
the entire VQMS system (portal, routing, KB search, analytics).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.email import EmailAttachment


# Official VQMS query types — used by portal frontend, backend validation,
# routing engine, KB search, and analytics. Add new types here only.
QUERY_TYPES: dict[str, str] = {
    "RETURN_REFUND": "Return & Refund",
    "GENERAL_INQUIRY": "General Inquiry",
    "CATALOG_PRICING": "Catalog & Pricing",
    "CONTRACT_QUERY": "Contract Query",
    "PURCHASE_ORDER": "Purchase Order",
    "SLA_BREACH_REPORT": "SLA Breach Report",
    "DELIVERY_SHIPMENT": "Delivery & Shipment",
    "INVOICE_PAYMENT": "Invoice & Payment",
    "COMPLIANCE_AUDIT": "Compliance & Audit",
    "TECHNICAL_SUPPORT": "Technical Support",
    "ONBOARDING": "Onboarding",
    "QUALITY_ISSUE": "Quality Issue",
}

# Which team handles each query type (used by routing node)
QUERY_TYPE_TEAM_MAP: dict[str, str] = {
    "RETURN_REFUND": "finance-ops",
    "GENERAL_INQUIRY": "general-support",
    "CATALOG_PRICING": "procurement",
    "CONTRACT_QUERY": "legal-compliance",
    "PURCHASE_ORDER": "procurement",
    "SLA_BREACH_REPORT": "sla-compliance",
    "DELIVERY_SHIPMENT": "supply-chain",
    "INVOICE_PAYMENT": "finance-ops",
    "COMPLIANCE_AUDIT": "legal-compliance",
    "TECHNICAL_SUPPORT": "tech-support",
    "ONBOARDING": "vendor-management",
    "QUALITY_ISSUE": "quality-assurance",
}

QueryType = Literal[
    "RETURN_REFUND",
    "GENERAL_INQUIRY",
    "CATALOG_PRICING",
    "CONTRACT_QUERY",
    "PURCHASE_ORDER",
    "SLA_BREACH_REPORT",
    "DELIVERY_SHIPMENT",
    "INVOICE_PAYMENT",
    "COMPLIANCE_AUDIT",
    "TECHNICAL_SUPPORT",
    "ONBOARDING",
    "QUALITY_ISSUE",
]


class QuerySubmission(BaseModel):
    """Vendor query submitted via the VQMS portal wizard.

    This is the raw input from the portal's 3-step form
    (type -> details -> review). Validated by Pydantic before
    any processing.
    """

    model_config = ConfigDict(frozen=True)

    query_type: QueryType = Field(description="One of the 12 official VQMS query types")
    subject: str = Field(description="Short summary of the query (5-500 chars)")
    description: str = Field(description="Full query details (10-5000 chars)")
    priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = Field(
        default="MEDIUM",
        description="Vendor-selected priority level",
    )
    reference_number: str | None = Field(
        default=None,
        description="Optional reference (invoice number, PO number, etc.)",
    )

    @field_validator("subject")
    @classmethod
    def validate_subject_length(cls, v: str) -> str:
        """Subject must be between 5 and 500 characters."""
        if len(v) < 5:
            msg = "Subject must be at least 5 characters"
            raise ValueError(msg)
        if len(v) > 500:
            msg = "Subject must be at most 500 characters"
            raise ValueError(msg)
        return v

    @field_validator("description")
    @classmethod
    def validate_description_length(cls, v: str) -> str:
        """Description must be between 10 and 5000 characters."""
        if len(v) < 10:
            msg = "Description must be at least 10 characters"
            raise ValueError(msg)
        if len(v) > 5000:
            msg = "Description must be at most 5000 characters"
            raise ValueError(msg)
        return v


class UnifiedQueryPayload(BaseModel):
    """Normalized query payload consumed by the AI pipeline.

    Both the email path and portal path produce this model
    before enqueueing to SQS. The LangGraph orchestrator
    reads this as the starting input.
    """

    model_config = ConfigDict(frozen=True)

    query_id: str = Field(description="VQMS query ID (VQ-2026-XXXX)")
    correlation_id: str = Field(description="UUID v4 tracing ID")
    execution_id: str = Field(description="UUID v4 for this pipeline run")
    source: Literal["email", "portal"] = Field(description="Which entry point produced this payload")
    vendor_id: str | None = Field(default=None, description="Resolved vendor ID (from JWT or Salesforce)")
    subject: str = Field(description="Query subject line")
    body: str = Field(description="Query body text")
    priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = Field(
        default="MEDIUM",
        description="Priority level",
    )
    received_at: datetime = Field(description="When the query was first received (IST)")
    attachments: list[EmailAttachment] = Field(
        default_factory=list,
        description="Attachments (email path only; empty for portal)",
    )
    thread_status: Literal["NEW", "EXISTING_OPEN", "REPLY_TO_CLOSED"] = Field(
        default="NEW",
        description="Thread correlation result (always NEW for portal)",
    )
    metadata: dict = Field(
        default_factory=dict,
        description="Additional context (email headers, portal form fields, etc.)",
    )
