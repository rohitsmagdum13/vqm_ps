"""Package: services/email_intake

Email Ingestion Service for VQMS — split into focused modules.

Re-exports the main service class and error so existing imports
like ``from services.email_intake import EmailIntakeService`` keep working.
"""

from services.email_intake.service import EmailIntakeError, EmailIntakeService

__all__ = ["EmailIntakeService", "EmailIntakeError"]
