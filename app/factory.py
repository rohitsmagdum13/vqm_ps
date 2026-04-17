"""Module: app/factory.py

FastAPI application factory for VQMS.

Assembles the full application by combining lifespan hooks,
middleware, routes, and OpenAPI configuration.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.lifespan import lifespan
from app.middleware import register_middleware
from app.routes import configure_openapi, register_routes


def create_app() -> FastAPI:
    """Create and configure the VQMS FastAPI application.

    Returns:
        Fully configured FastAPI application ready to serve requests.
    """
    application = FastAPI(
        title="VQMS — Vendor Query Management System",
        description=(
            "Agentic AI platform that automates vendor query resolution. "
            "Ingests queries via email (Graph API) and portal (REST API), "
            "analyzes with Claude AI, and routes to Path A (AI-resolved), "
            "Path B (human-investigated), or Path C (human-reviewed)."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    register_middleware(application)
    register_routes(application)
    configure_openapi(application)

    return application
