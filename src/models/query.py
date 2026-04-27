"""Module: models/query.py

Pydantic models for portal query submission and the unified query payload.

QuerySubmission is the input from the vendor portal wizard.
UnifiedQueryPayload is the normalized format that both email
and portal paths produce before entering the AI pipeline.

QueryAttachment models a portal-uploaded file (mirrors EmailAttachment).
ExtractedEntities is the structured JSON output of the entity-extraction
LLM call performed during portal intake.

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


class QueryAttachment(BaseModel):
    """A single file attachment uploaded with a portal query.

    Mirrors EmailAttachment but carries portal-specific extras:
    extraction_method records which extractor produced the text
    (textract / pdfplumber / openpyxl / docx / decode / none),
    so downstream consumers and the admin UI can tell apart
    OCR-derived text from native parsers.
    """

    model_config = ConfigDict(frozen=True)

    attachment_id: str = Field(description="Stable ID for the attachment within a query (ATT-001 ...)")
    filename: str = Field(description="Original filename from the upload")
    content_type: str = Field(description="MIME type")
    size_bytes: int = Field(description="File size in bytes")
    s3_key: str | None = Field(default=None, description="S3 object key under attachments/{query_id}/")
    extracted_text: str | None = Field(
        default=None,
        description="Text extracted from the file (max 5000 chars)",
    )
    extraction_status: Literal["pending", "success", "failed", "skipped"] = Field(
        default="pending",
        description="Outcome of text extraction",
    )
    extraction_method: Literal[
        "textract", "pdfplumber", "openpyxl", "python_docx", "decode", "none"
    ] = Field(
        default="none",
        description="Which extractor produced the text",
    )


class AmountEntity(BaseModel):
    """A monetary amount with currency, parsed from query text or attachments."""

    model_config = ConfigDict(frozen=True)

    value: float = Field(description="Numeric amount")
    currency: str = Field(description="ISO-4217 currency code (e.g. INR, USD)")


class ExtractedEntities(BaseModel):
    """Structured entities extracted by the entity-extraction LLM call.

    All fields default to empty so a parse failure can return an
    'empty' instance and the pipeline keeps moving. Lists are used
    even for typically-single fields so the model never has to make
    an arbitrary "which one wins" choice.

    The schema is the contract the prompt is pinned to — keep this
    model and the prompt in sync.
    """

    model_config = ConfigDict(frozen=True)

    invoice_numbers: list[str] = Field(default_factory=list)
    po_numbers: list[str] = Field(default_factory=list)
    amounts: list[AmountEntity] = Field(default_factory=list)
    dates: list[str] = Field(
        default_factory=list,
        description="Calendar dates in YYYY-MM-DD format",
    )
    vendor_names: list[str] = Field(default_factory=list)
    product_skus: list[str] = Field(default_factory=list)
    contract_ids: list[str] = Field(default_factory=list)
    ticket_numbers: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    phone_numbers: list[str] = Field(default_factory=list)
    summary: str = Field(default="", description="One-sentence summary of the query")


class UnifiedQueryPayload(BaseModel):
    """Normalized query payload consumed by the AI pipeline.

    Both the email path and portal path produce this model
    before enqueueing to SQS. The LangGraph orchestrator
    reads this as the starting input.

    Email path uses ``EmailAttachment`` items inside ``attachments``;
    portal path uses ``QueryAttachment`` items. The pipeline only
    reads common fields (filename, s3_key, extracted_text), so the
    union is safe.
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
    attachments: list[EmailAttachment | QueryAttachment] = Field(
        default_factory=list,
        description="Attachments — EmailAttachment for email path, QueryAttachment for portal path",
    )
    thread_status: Literal["NEW", "EXISTING_OPEN", "REPLY_TO_CLOSED"] = Field(
        default="NEW",
        description="Thread correlation result (always NEW for portal)",
    )
    metadata: dict = Field(
        default_factory=dict,
        description=(
            "Additional context (email headers, portal form fields, "
            "extracted_entities for portal path, etc.)"
        ),
    )
