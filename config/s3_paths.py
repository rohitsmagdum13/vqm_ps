"""Module: config/s3_paths.py

Centralized S3 storage paths for VQMS single-bucket architecture.

All S3 object keys are built from these constants — no hardcoded
bucket names, prefixes, or filenames anywhere else in the codebase.

Bucket structure:
    vqms-data-store/
    ├── inbound-emails/VQ-YYYY-NNNN/raw_email.json
    ├── attachments/VQ-YYYY-NNNN/{att_id}_{filename}
    ├── attachments/VQ-YYYY-NNNN/_manifest.json
    ├── processed/VQ-YYYY-NNNN/email_analysis.json
    ├── processed/VQ-YYYY-NNNN/response_draft.json
    ├── processed/VQ-YYYY-NNNN/ticket_payload.json
    ├── processed/VQ-YYYY-NNNN/resolution_summary.json
    ├── templates/response_templates/{category}.json
    └── archive/VQ-YYYY-NNNN/_archive_bundle.json

Usage:
    from config.s3_paths import build_s3_key, S3_PREFIX_INBOUND_EMAILS, FILENAME_RAW_EMAIL

    key = build_s3_key(S3_PREFIX_INBOUND_EMAILS, "VQ-2026-0001", FILENAME_RAW_EMAIL)
    # -> "inbound-emails/VQ-2026-0001/raw_email.json"
"""

from __future__ import annotations

# ===========================
# Prefix constants (top-level folders in the bucket)
# ===========================
S3_PREFIX_INBOUND_EMAILS = "inbound-emails"
S3_PREFIX_ATTACHMENTS = "attachments"
S3_PREFIX_PROCESSED = "processed"
S3_PREFIX_TEMPLATES = "templates"
S3_PREFIX_ARCHIVE = "archive"

# ===========================
# Standard filename constants
# ===========================
FILENAME_RAW_EMAIL = "raw_email.json"
FILENAME_ATTACHMENT_MANIFEST = "_manifest.json"
FILENAME_EMAIL_ANALYSIS = "email_analysis.json"
FILENAME_RESPONSE_DRAFT = "response_draft.json"
FILENAME_TICKET_PAYLOAD = "ticket_payload.json"
FILENAME_RESOLUTION_SUMMARY = "resolution_summary.json"
FILENAME_ARCHIVE_BUNDLE = "_archive_bundle.json"


def build_s3_key(prefix: str, query_id: str, filename: str) -> str:
    """Build an S3 object key from prefix, query ID, and filename.

    All VQMS files follow the pattern: prefix/VQ-YYYY-NNNN/filename.
    This function enforces that convention so no code constructs
    S3 keys manually with f-strings.

    Args:
        prefix: Top-level folder (use S3_PREFIX_* constants).
        query_id: Vendor Query ID (e.g., "VQ-2026-0001").
        filename: File name (use FILENAME_* constants where applicable).

    Returns:
        Full S3 object key, e.g., "inbound-emails/VQ-2026-0001/raw_email.json".
    """
    return f"{prefix}/{query_id}/{filename}"
