"""Module: models/email.py

Pydantic models for email ingestion data.

These models represent the parsed output of the Email Ingestion
Service (intake/email_intake.py). A raw email from Exchange Online
is parsed into an EmailAttachment list and a ParsedEmailPayload.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EmailAttachment(BaseModel):
    """A single file attachment extracted from a vendor email.

    Attachments are stored in S3 and their text content is
    extracted for inclusion in the AI analysis.
    """

    model_config = ConfigDict(frozen=True)

    attachment_id: str = Field(description="Unique ID for this attachment")
    filename: str = Field(description="Original filename from the email")
    content_type: str = Field(description="MIME type (e.g., application/pdf)")
    size_bytes: int = Field(description="File size in bytes")
    s3_key: str | None = Field(default=None, description="S3 object key where the file is stored")
    extracted_text: str | None = Field(default=None, description="Text extracted from the attachment (max 5000 chars)")
    extraction_status: Literal["pending", "success", "failed", "skipped"] = Field(
        default="pending",
        description="Status of text extraction",
    )


class ParsedEmailPayload(BaseModel):
    """The fully parsed output of an incoming vendor email.

    This is the primary output of the Email Ingestion Service.
    It contains all metadata, parsed content, vendor identification,
    and thread correlation needed for the AI pipeline.
    """

    model_config = ConfigDict(frozen=True)

    message_id: str = Field(description="Exchange Online message ID (unique per email)")
    correlation_id: str = Field(description="UUID v4 tracing ID for the entire pipeline")
    query_id: str = Field(description="VQMS query ID (VQ-2026-XXXX format)")
    sender_email: str = Field(description="Email address of the sender")
    sender_name: str | None = Field(default=None, description="Display name of the sender")
    recipients: list[str] = Field(description="List of recipient email addresses")
    subject: str = Field(description="Email subject line")
    body_text: str = Field(description="Plain text body of the email")
    body_html: str | None = Field(default=None, description="HTML body (if present)")
    received_at: datetime = Field(description="When the email was received (IST)")
    parsed_at: datetime = Field(description="When the email was parsed (IST)")
    in_reply_to: str | None = Field(default=None, description="Message-ID this is a reply to")
    references: list[str] = Field(default_factory=list, description="Message-ID chain from email headers")
    conversation_id: str | None = Field(default=None, description="Exchange conversationId for thread grouping")
    thread_status: Literal["NEW", "EXISTING_OPEN", "REPLY_TO_CLOSED"] = Field(
        description="Result of thread correlation check",
    )
    vendor_id: str | None = Field(default=None, description="Resolved vendor ID from Salesforce")
    vendor_match_method: Literal["exact_email", "body_extraction", "fuzzy_name", "unresolved"] | None = Field(
        default=None,
        description="How the vendor was identified (3-step fallback)",
    )
    attachments: list[EmailAttachment] = Field(default_factory=list, description="Parsed email attachments")
    s3_raw_email_key: str | None = Field(default=None, description="S3 key for the raw .eml file")
    source: Literal["email"] = Field(default="email", description="Entry point — always 'email' for this model")
