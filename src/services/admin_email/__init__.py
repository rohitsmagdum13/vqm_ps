"""Package: services/admin_email

Admin Email Service for VQMS — free-form admin send/reply.

Backs the two endpoints in api/routes/admin_email.py:
- POST /admin/email/send                          (fresh email)
- POST /admin/email/queries/{query_id}/reply      (threaded reply)

Re-exports so existing imports like
``from services.admin_email import AdminEmailService`` keep working.
"""

from services.admin_email.attachments import (
    AttachmentLimits,
    AttachmentStager,
    AttachmentValidator,
)
from services.admin_email.service import (
    AdminEmailService,
    AdminSendResult,
)

__all__ = [
    "AdminEmailService",
    "AdminSendResult",
    "AttachmentLimits",
    "AttachmentStager",
    "AttachmentValidator",
]
