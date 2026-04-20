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


class MailItemResponse(BaseModel):
    """A single email in a thread.

    Represents one row from intake.email_messages joined with
    its attachments from intake.email_attachments.
    """

    model_config = ConfigDict(frozen=True)

    query_id: str = Field(description="VQMS query ID (e.g., VQ-2026-0001)")
    sender: UserResponse = Field(description="Email sender")
    subject: str = Field(description="Email subject line")
    body: str = Field(description="Plain text email body")
    body_html: str | None = Field(default=None, description="Sanitized HTML email body, if available")
    timestamp: str = Field(description="Received time in ISO 8601 IST format")
    attachments: list[AttachmentSummary] = Field(
        default_factory=list, description="Attachments on this email"
    )
    thread_status: str = Field(description="Thread status: NEW, EXISTING_OPEN, REPLY_TO_CLOSED")


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
        description="Count by priority: {High: N, Medium: N, Low: N}"
    )
    today_count: int = Field(description="Queries created today (IST)")
    this_week_count: int = Field(description="Queries created in the last 7 days")


class AttachmentDownloadResponse(BaseModel):
    """Presigned S3 download URL for an attachment."""

    model_config = ConfigDict(frozen=True)

    attachment_id: str = Field(description="Attachment identifier")
    filename: str = Field(description="Original filename for Content-Disposition")
    download_url: str = Field(description="Presigned S3 URL (valid for 1 hour)")
    expires_in_seconds: int = Field(default=3600, description="URL validity in seconds")
