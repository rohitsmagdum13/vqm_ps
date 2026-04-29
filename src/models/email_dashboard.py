"""Module: models/email_dashboard.py

Pydantic response models for the Email Dashboard API.

These models define the exact JSON shape returned by each endpoint.
All models use frozen=True for immutability, matching the pattern
used throughout the VQMS codebase.

Note on recipients: The to/cc fields are intentionally omitted because
the intake.email_messages table does not store recipient columns.
Only sender information is available in the DB. Recipients can be
added in a future migration if needed.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class UserResponse(BaseModel):
    """A user (sender) in the email dashboard.

    Used to represent the email sender. Recipients are not
    available in the current DB schema.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(description="Display name (sender_name from DB, falls back to email)")
    email: str = Field(description="Email address")


class AttachmentSummary(BaseModel):
    """An email attachment summary for list and detail views."""

    model_config = ConfigDict(frozen=True)

    attachment_id: str = Field(description="Unique attachment identifier")
    filename: str = Field(description="Original filename")
    content_type: str = Field(description="MIME type (e.g., application/pdf)")
    size_bytes: int = Field(description="File size in bytes")
    file_format: str = Field(description="Uppercase file extension (e.g., PDF, XLSX, UNKNOWN)")
    # Admin portal renders attachments with a direct download link,
    # so we embed the presigned URL here instead of making the
    # frontend hit a second endpoint per attachment.
    download_url: str | None = Field(
        default=None,
        description="Presigned S3 URL to download the attachment (None if s3_key missing)",
    )
    expires_in_seconds: int = Field(
        default=3600,
        description="Presigned URL validity window in seconds",
    )


class MailItemResponse(BaseModel):
    """A single email in a thread.

    Represents one row from intake.email_messages joined with
    its attachments from intake.email_attachments. Every non-PII
    column on intake.email_messages is exposed here so the dashboard
    can render the full audit trail for a vendor email.
    """

    model_config = ConfigDict(frozen=True)

    # Identifiers
    query_id: str = Field(description="VQMS query ID (e.g., VQ-2026-0001)")
    message_id: str = Field(description="Exchange Online message ID (unique per email)")
    correlation_id: str = Field(description="UUID v4 tracing ID propagated through the pipeline")
    internet_message_id: str | None = Field(
        default=None,
        description="RFC 5322 Message-ID header (distinct from Graph's message_id)",
    )

    # Sender + full recipient lists
    sender: UserResponse = Field(description="Email sender (from field)")
    to_recipients: list[UserResponse] = Field(
        default_factory=list, description="Primary recipients (To field)"
    )
    cc_recipients: list[UserResponse] = Field(
        default_factory=list, description="CC recipients"
    )
    bcc_recipients: list[UserResponse] = Field(
        default_factory=list,
        description="BCC recipients (only populated when the mailbox is itself a BCC)",
    )
    reply_to: list[UserResponse] = Field(
        default_factory=list, description="Reply-To addresses if different from sender"
    )

    # Subject + body
    subject: str = Field(description="Email subject line")
    body: str = Field(description="Plain text email body")
    body_html: str | None = Field(default=None, description="Sanitized HTML email body, if available")
    importance: str | None = Field(
        default=None, description="Exchange importance: low, normal, or high"
    )
    has_attachments: bool = Field(
        default=False, description="True if the email has one or more attachments"
    )
    web_link: str | None = Field(
        default=None, description="Outlook Web Access URL for this email"
    )

    # Timestamps (ISO 8601 IST strings)
    timestamp: str = Field(description="Received time in ISO 8601 IST format (received_at)")
    parsed_at: str = Field(description="When the email was parsed (ISO 8601 IST)")
    created_at: str = Field(description="When the email_messages row was inserted (ISO 8601 IST)")

    # Thread correlation
    in_reply_to: str | None = Field(
        default=None, description="Message-ID this email is a reply to"
    )
    conversation_id: str | None = Field(
        default=None, description="Exchange conversationId for thread grouping"
    )
    thread_status: str = Field(description="Thread status: NEW, EXISTING_OPEN, REPLY_TO_CLOSED")

    # Vendor resolution
    vendor_id: str | None = Field(
        default=None, description="Resolved vendor ID from Salesforce (NULL if unresolved)"
    )
    vendor_match_method: str | None = Field(
        default=None,
        description="How the vendor was identified: exact_email, body_extraction, fuzzy_name, unresolved",
    )

    # Storage + source
    s3_raw_email_key: str | None = Field(
        default=None, description="S3 key for the raw .eml file"
    )
    source: str = Field(default="email", description="Entry point — always 'email' for this model")

    # Attachments
    attachments: list[AttachmentSummary] = Field(
        default_factory=list, description="Attachments on this email"
    )


class MailChainResponse(BaseModel):
    """A thread of related emails with workflow status.

    Groups emails by conversation_id (Graph API thread ID).
    If conversation_id is NULL, the email is its own chain.
    """

    model_config = ConfigDict(frozen=True)

    conversation_id: str | None = Field(
        description="Graph API conversation thread ID (NULL if standalone)"
    )
    mail_items: list[MailItemResponse] = Field(description="Emails in this thread, newest first")
    status: str = Field(description="Dashboard status: New, Reopened, or Resolved")
    priority: str = Field(description="Dashboard priority: High, Medium, or Low")


class MailChainListResponse(BaseModel):
    """Paginated list of email chains for the dashboard."""

    model_config = ConfigDict(frozen=True)

    total: int = Field(description="Total number of chains matching filters")
    page: int = Field(description="Current page number (1-based)")
    page_size: int = Field(description="Items per page")
    mail_chains: list[MailChainResponse] = Field(description="Chains on this page")


class EmailStatsResponse(BaseModel):
    """Aggregate dashboard statistics for email-sourced queries."""

    model_config = ConfigDict(frozen=True)

    total_emails: int = Field(description="Total email-sourced queries")
    new_count: int = Field(description="Queries in active processing states")
    reopened_count: int = Field(description="Reopened queries")
    resolved_count: int = Field(description="Resolved or closed queries")
    priority_breakdown: dict[str, int] = Field(
        description="Count by priority: {Critical: N, High: N, Medium: N, Low: N}"
    )
    today_count: int = Field(description="Queries created today (IST)")
    this_week_count: int = Field(description="Queries created in the last 7 days")
    past_10_days_new: list[int] = Field(
        description=(
            "New-email counts per day for the last 10 days, oldest → newest. "
            "Length is always exactly 10 (zero-filled for days with no activity)."
        )
    )
    past_10_days_resolved: list[int] = Field(
        description=(
            "Resolved-email counts per day for the last 10 days, oldest → newest. "
            "Length is always exactly 10 (zero-filled for days with no activity)."
        )
    )


class AttachmentDownloadResponse(BaseModel):
    """Presigned S3 download URL for an attachment."""

    model_config = ConfigDict(frozen=True)

    attachment_id: str = Field(description="Attachment identifier")
    filename: str = Field(description="Original filename for Content-Disposition")
    download_url: str = Field(description="Presigned S3 URL (valid for 1 hour)")
    expires_in_seconds: int = Field(default=3600, description="URL validity in seconds")
