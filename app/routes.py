"""Module: app/routes.py

Router registration and health check for the VQMS FastAPI application.

Registers all API routers and provides the health check endpoint.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from api.routes.admin_drafts import router as admin_drafts_router
from api.routes.admin_email import router as admin_email_router
from api.routes.admin_overview import router as admin_overview_router
from api.routes.admin_queries import router as admin_queries_router
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
    application.include_router(queries_router)        # vendor-facing /queries
    application.include_router(admin_queries_router)  # admin-facing /admin/queries
    application.include_router(admin_overview_router) # admin-facing /admin/overview
    application.include_router(vendors_router)
    application.include_router(webhooks_router)
    application.include_router(dashboard_router)
    application.include_router(portal_dashboard_router)
    application.include_router(triage_router)
    application.include_router(copilot_triage_router)
    application.include_router(admin_drafts_router)
    application.include_router(admin_email_router)

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


def _normalize_binary_fields_for_swagger_ui(node) -> None:
    """Recursively rewrite OpenAPI 3.1 binary fields into OpenAPI 3.0 form.

    FastAPI/Pydantic 2 emits ``{"type": "string", "contentMediaType":
    "application/octet-stream"}`` for ``UploadFile`` parameters. That is
    valid OpenAPI 3.1 but Swagger UI 4.x doesn't recognize it — the
    field renders as ``array<string>`` with an "Add string item" button
    instead of a real file picker, and submitting yields a 422
    "Expected UploadFile, received: <class 'str'>".

    Converting to ``{"type": "string", "format": "binary"}`` (the
    OpenAPI 3.0 way of expressing the same thing) makes Swagger UI
    render the file picker correctly. Both forms are accepted by FastAPI
    on the request side, so this is purely a UI-level rewrite.
    """
    if isinstance(node, dict):
        if (
            node.get("type") == "string"
            and node.get("contentMediaType") == "application/octet-stream"
        ):
            node.pop("contentMediaType", None)
            node["format"] = "binary"
        for value in node.values():
            _normalize_binary_fields_for_swagger_ui(value)
    elif isinstance(node, list):
        for item in node:
            _normalize_binary_fields_for_swagger_ui(item)


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
            # Pin OpenAPI to 3.0.2 so Swagger UI renders UploadFile fields
            # as actual file pickers. OpenAPI 3.1 uses contentMediaType
            # which Swagger UI 4.x falls back to "array<string>" + "Add
            # string item" — that breaks our admin email and portal
            # multipart upload routes.
            openapi_version="3.0.2",
        )

        # Normalise binary fields so Swagger UI shows a real file picker.
        _normalize_binary_fields_for_swagger_ui(openapi_schema)

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
