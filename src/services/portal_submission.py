"""Module: services/portal_submission.py

Compatibility shim — the implementation has moved to
``services.portal_intake``. This module re-exports the same
``PortalIntakeService`` symbol so existing imports keep working.

New code should import directly from the folder module:

    from services.portal_intake import PortalIntakeService
"""

from __future__ import annotations

from services.portal_intake import PortalIntakeService

__all__ = ["PortalIntakeService"]
