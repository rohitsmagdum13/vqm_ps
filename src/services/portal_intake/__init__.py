"""Portal intake folder module — entry point for vendor-portal queries.

The exported PortalIntakeService takes a validated QuerySubmission plus
zero or more uploaded files and:
  1. checks idempotency, generates IDs, and persists the submission
  2. uploads each attachment to S3 and extracts text
     (Textract first, library-based fallback for PDFs)
  3. runs an LLM call to produce a structured ExtractedEntities JSON
  4. publishes events and enqueues the unified payload to SQS

Usage:
    from services.portal_intake import PortalIntakeService
    payload = await service.submit_query(submission, vendor_id, files=[...])
"""

from services.portal_intake.service import PortalIntakeService

__all__ = ["PortalIntakeService"]
