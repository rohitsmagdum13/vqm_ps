"""Module: main.py

VQMS FastAPI application entry point.

Creates the FastAPI app, registers all routers, adds middleware,
and sets up startup/shutdown lifecycle hooks for connectors
(PostgreSQL, Salesforce, S3, SQS, EventBridge).

Run with:
    uv run uvicorn main:app --reload --port 8000

Then visit:
    http://localhost:8000/docs   (Swagger UI)
    http://localhost:8000/redoc  (ReDoc)
    http://localhost:8000/health (Health check)
"""

from __future__ import annotations

import secrets
import sys
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

# Ensure both root (for config/) and src/ are importable
sys.path.insert(0, ".")
sys.path.insert(0, "src")

from api.middleware.auth_middleware import AuthMiddleware
from api.routes.auth import router as auth_router
from api.routes.dashboard import router as dashboard_router
from api.routes.portal_dashboard import router as portal_dashboard_router
from api.routes.queries import router as queries_router
from api.routes.vendors import router as vendors_router
from api.routes.webhooks import router as webhooks_router
from config.settings import get_settings
from utils.logger import LoggingSetup

# Configure structured logging before anything else
LoggingSetup.configure()

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Startup and shutdown lifecycle for the VQMS application.

    On startup: connect to PostgreSQL (via SSH tunnel if configured),
    and attach all connectors to app.state so route handlers can
    access them via request.app.state.

    On shutdown: close all connections cleanly.
    """
    settings = get_settings()

    logger.info(
        "VQMS starting up",
        app_name=settings.app_name,
        app_env=settings.app_env,
        port=settings.app_port,
    )

    # --- Connect to PostgreSQL ---
    postgres = None
    try:
        from db.connection import PostgresConnector

        postgres = PostgresConnector(settings)
        await postgres.connect()
        logger.info("PostgreSQL connected", tool="postgresql")
        application.state.postgres = postgres
    except Exception:
        logger.warning(
            "PostgreSQL connection failed — some endpoints will not work",
            tool="postgresql",
        )
        application.state.postgres = None

    # --- Initialize Auth Service ---
    # Auth service needs the PostgresConnector to query tbl_users
    # and manage JWT blacklist in cache.kv_store
    if postgres is not None:
        from services.auth import init_auth_service

        init_auth_service(postgres)
        logger.info("Auth service initialized")

    # --- Create Salesforce connector ---
    salesforce = None
    try:
        from adapters.salesforce import SalesforceConnector

        salesforce = SalesforceConnector(settings)
        logger.info("Salesforce connector ready", tool="salesforce")
        application.state.salesforce = salesforce
    except Exception:
        logger.warning(
            "Salesforce connector init failed — vendor endpoints will not work",
            tool="salesforce",
        )
        application.state.salesforce = None

    # --- Create S3 connector ---
    try:
        from storage.s3_client import S3Connector

        application.state.s3 = S3Connector(settings)
        logger.info("S3 connector ready", tool="s3")
    except Exception:
        logger.warning("S3 connector init failed", tool="s3")
        application.state.s3 = None

    # --- Create SQS connector ---
    try:
        from queues.sqs import SQSConnector

        application.state.sqs = SQSConnector(settings)
        logger.info("SQS connector ready", tool="sqs")
    except Exception:
        logger.warning("SQS connector init failed", tool="sqs")
        application.state.sqs = None

    # --- Create EventBridge connector ---
    try:
        from events.eventbridge import EventBridgeConnector

        application.state.eventbridge = EventBridgeConnector(settings)
        logger.info("EventBridge connector ready", tool="eventbridge")
    except Exception:
        logger.warning("EventBridge connector init failed", tool="eventbridge")
        application.state.eventbridge = None

    # --- Create LLM Gateway ---
    try:
        from adapters.llm_gateway import LLMGateway

        application.state.llm_gateway = LLMGateway(settings)
        logger.info("LLM Gateway ready", tool="llm_gateway")
    except Exception:
        logger.warning("LLM Gateway init failed", tool="llm_gateway")
        application.state.llm_gateway = None

    # --- Create Graph API connector ---
    graph_api = None
    try:
        from adapters.graph_api import GraphAPIConnector

        graph_api = GraphAPIConnector(settings)
        logger.info("Graph API connector ready", tool="graph_api")
        application.state.graph_api = graph_api
    except Exception:
        logger.warning(
            "Graph API connector init failed — email endpoints will not work",
            tool="graph_api",
        )
        application.state.graph_api = None

    # --- Create ServiceNow connector ---
    servicenow = None
    try:
        from adapters.servicenow import ServiceNowConnector

        servicenow = ServiceNowConnector(settings)
        logger.info("ServiceNow connector ready", tool="servicenow")
        application.state.servicenow = servicenow
    except Exception:
        logger.warning(
            "ServiceNow connector init failed — ticket endpoints will not work",
            tool="servicenow",
        )
        application.state.servicenow = None

    # --- Create Portal Intake Service ---
    # Wires together postgres + sqs + eventbridge into the service
    # that handles POST /queries from the vendor portal
    try:
        from services.portal_submission import PortalIntakeService

        application.state.portal_intake = PortalIntakeService(
            postgres=application.state.postgres,
            sqs=application.state.sqs,
            eventbridge=application.state.eventbridge,
            settings=settings,
        )
        logger.info("Portal Intake Service ready")
    except Exception:
        logger.warning("Portal Intake Service init failed")
        application.state.portal_intake = None

    # --- Create Email Dashboard Service ---
    # Read-only service for GET /emails endpoints.
    # Needs postgres (queries) and s3 (attachment download URLs).
    try:
        from services.email_dashboard import EmailDashboardService

        application.state.dashboard_service = EmailDashboardService(
            postgres=application.state.postgres,
            s3=application.state.s3,
            settings=settings,
        )
        logger.info("Email Dashboard Service ready")
    except Exception:
        logger.warning("Email Dashboard Service init failed")
        application.state.dashboard_service = None

    # --- Store settings for route handlers ---
    application.state.settings = settings

    logger.info("VQMS startup complete — all connectors initialized")

    yield  # App runs here

    # --- Shutdown ---
    logger.info("VQMS shutting down")

    if servicenow is not None:
        await servicenow.close()
        logger.info("ServiceNow connector closed", tool="servicenow")

    if graph_api is not None:
        await graph_api.close()
        logger.info("Graph API connector closed", tool="graph_api")

    if postgres is not None:
        await postgres.disconnect()
        logger.info("PostgreSQL disconnected", tool="postgresql")

    logger.info("VQMS shutdown complete")


# --- Create the FastAPI application ---

app = FastAPI(
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

# --- Middleware ---

# Middleware execution order: last registered runs FIRST on requests.
# So register AuthMiddleware first, CORSMiddleware second.
# Request flow: CORSMiddleware (handles OPTIONS preflight) → AuthMiddleware → route handler.

app.add_middleware(AuthMiddleware)

app.add_middleware(
    CORSMiddleware,
    # Dev mode: allow all localhost origins (Angular may pick random ports)
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-New-Token"],
)


# --- Security Headers Middleware ---
# Adds browser-level security headers to every response.
# These protect against XSS, clickjacking, MIME sniffing,
# information leakage, and caching of sensitive data.


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security headers to every HTTP response."""
    response = await call_next(request)

    # Skip CSP for Swagger UI paths — Swagger loads scripts from
    # a CDN (cdn.jsdelivr.net) and uses inline JS to render the
    # interactive docs. Our strict CSP blocks both of these,
    # causing a blank white screen. API endpoints still get
    # full CSP protection.
    docs_paths = ("/docs", "/redoc", "/openapi.json")
    is_docs_page = request.url.path in docs_paths

    if not is_docs_page:
        # CSP: Only allow resources from our own domain.
        # Nonce-based script policy blocks injected scripts.
        nonce = secrets.token_urlsafe(16)
        response.headers["Content-Security-Policy"] = (
            f"default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}'; "
            f"style-src 'self' 'unsafe-inline'; "
            f"img-src 'self' data:; "
            f"connect-src 'self'; "
            f"font-src 'self'; "
            f"child-src 'none'; "
            f"frame-ancestors 'none'"
        )

    # Hide server identity (default is "uvicorn")
    response.headers["Server"] = "hidden"

    # Prevent browser from guessing file types
    response.headers["X-Content-Type-Options"] = "nosniff"

    # Legacy XSS filter for older browsers
    response.headers["X-XSS-Protection"] = "1; mode=block"

    # Prevent our app from being embedded in iframes (clickjacking)
    response.headers["X-Frame-Options"] = "DENY"

    # Force HTTPS for 1 year (only effective in production behind TLS)
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains"
    )

    # Don't leak URLs when navigating away from our site
    response.headers["Referrer-Policy"] = "no-referrer"

    # Restrict browser APIs we don't use
    response.headers["Permissions-Policy"] = (
        "geolocation=(), camera=(), microphone=()"
    )

    # Never cache API responses (sensitive vendor/email data)
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, proxy-revalidate"
    )
    response.headers["Pragma"] = "no-cache"

    return response


# --- Routes ---

app.include_router(auth_router)
app.include_router(queries_router)
app.include_router(vendors_router)
app.include_router(webhooks_router)
app.include_router(dashboard_router)
app.include_router(portal_dashboard_router)


# --- Swagger UI: Authorize Button (Bearer JWT) ---
# This adds the "Authorize 🔒" button to Swagger UI so you can
# paste your JWT token and test protected endpoints easily.


def custom_openapi():
    """Build OpenAPI schema with Bearer auth security scheme."""
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
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

    app.openapi_schema = openapi_schema
    return openapi_schema


app.openapi = custom_openapi


# --- Health Check ---

@app.get("/health", tags=["system"])
async def health_check():
    """Health check endpoint.

    Returns basic app status. Used by load balancers and
    monitoring systems to verify the app is running.
    No authentication required.
    """
    db_healthy = False
    if hasattr(app.state, "postgres") and app.state.postgres is not None:
        try:
            db_healthy = await app.state.postgres.health_check()
        except Exception:
            db_healthy = False

    return {
        "status": "healthy",
        "app": "vqms",
        "version": "0.1.0",
        "database": "connected" if db_healthy else "disconnected",
    }
