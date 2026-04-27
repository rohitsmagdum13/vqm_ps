"""Module: app/routes.py

Router registration and health check for the VQMS FastAPI application.

Registers all API routers and provides the health check endpoint.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from api.routes.admin_drafts import router as admin_drafts_router
from api.routes.auth import router as auth_router
from api.routes.copilot_triage import router as copilot_triage_router
from api.routes.dashboard import router as dashboard_router
from api.routes.portal_dashboard import router as portal_dashboard_router
from api.routes.queries import router as queries_router
from api.routes.triage import router as triage_router
from api.routes.vendors import router as vendors_router
from api.routes.webhooks import router as webhooks_router


def register_routes(application: FastAPI) -> None:
    """Register all routers and the health check endpoint."""
    application.include_router(auth_router)
    application.include_router(queries_router)
    application.include_router(vendors_router)
    application.include_router(webhooks_router)
    application.include_router(dashboard_router)
    application.include_router(portal_dashboard_router)
    application.include_router(triage_router)
    application.include_router(copilot_triage_router)
    application.include_router(admin_drafts_router)

    @application.get("/health", tags=["system"])
    async def health_check():
        """Health check endpoint.

        Returns basic app status. Used by load balancers and
        monitoring systems to verify the app is running.
        No authentication required.
        """
        db_healthy = False
        if hasattr(application.state, "postgres") and application.state.postgres is not None:
            try:
                db_healthy = await application.state.postgres.health_check()
            except Exception:
                db_healthy = False

        return {
            "status": "healthy",
            "app": "vqms",
            "version": "0.1.0",
            "database": "connected" if db_healthy else "disconnected",
        }


def configure_openapi(application: FastAPI) -> None:
    """Configure custom OpenAPI schema with Bearer auth security scheme.

    Adds the "Authorize" button to Swagger UI so you can
    paste your JWT token and test protected endpoints easily.
    """

    def custom_openapi():
        if application.openapi_schema:
            return application.openapi_schema

        openapi_schema = get_openapi(
            title=application.title,
            version=application.version,
            description=application.description,
            routes=application.routes,
        )

        # Add Bearer token security scheme
        openapi_schema["components"]["securitySchemes"] = {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": (
                    "Paste the token from POST /auth/login response. "
                    "Example: eyJhbGciOiJIUzI1NiIs..."
                ),
            }
        }

        # Apply globally — every endpoint shows the lock icon
        openapi_schema["security"] = [{"BearerAuth": []}]

        application.openapi_schema = openapi_schema
        return openapi_schema

    application.openapi = custom_openapi
