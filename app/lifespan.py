"""Module: app/lifespan.py

Startup and shutdown lifecycle for the VQMS application.

On startup: connect to PostgreSQL (via SSH tunnel if configured),
initialize all connectors and services, attach to app.state.
On shutdown: close all connections cleanly.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from config.settings import get_settings

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
