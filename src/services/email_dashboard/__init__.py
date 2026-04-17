"""Package: services/email_dashboard

Email Dashboard Service for VQMS — split into focused modules.

Re-exports the main service class so existing imports
like ``from services.email_dashboard import EmailDashboardService`` keep working.
"""

from services.email_dashboard.service import EmailDashboardService

__all__ = ["EmailDashboardService"]
