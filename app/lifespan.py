"""Module: app/lifespan.py

Startup and shutdown lifecycle for the VQMS application.

On startup: connect to PostgreSQL (via SSH tunnel if configured),
initialize all connectors and services, attach to app.state.
On shutdown: close all connections cleanly.
"""

from __future__ import annotations

import asyncio
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

    # --- Create Triage Service (Path C) ---
    # Backs the triage API routes that reviewers use to correct
    # low-confidence analyses and resume the paused workflow.
    # SQS and EventBridge are optional — without SQS the resume
    # falls back to DB-only so a background worker can pick up.
    if application.state.postgres is not None:
        try:
            from services.triage import TriageService

            application.state.triage_service = TriageService(
                postgres=application.state.postgres,
                sqs=application.state.sqs,
                eventbridge=application.state.eventbridge,
                settings=settings,
            )
            logger.info("Triage Service ready")
        except Exception:
            logger.warning("Triage Service init failed")
            application.state.triage_service = None
    else:
        application.state.triage_service = None

    # --- Phase 6 Episodic Memory Writer ---
    # Writes a summary row into memory.episodic_memory on case closure so
    # context_loading can surface it on future queries for the same vendor.
    episodic_memory_writer = None
    if application.state.postgres is not None:
        try:
            from services.episodic_memory import EpisodicMemoryWriter

            episodic_memory_writer = EpisodicMemoryWriter(
                postgres=application.state.postgres,
                settings=settings,
            )
            application.state.episodic_memory_writer = episodic_memory_writer
            logger.info("Episodic Memory Writer ready")
        except Exception:
            logger.warning("Episodic Memory Writer init failed")
            application.state.episodic_memory_writer = None
    else:
        application.state.episodic_memory_writer = None

    # --- Phase 6 Closure Service ---
    # Handles confirmation-reply detection, reopen inside window, and the
    # actual close_case call (update case_execution, ServiceNow status,
    # publish TicketClosed, write episodic memory).
    closure_service = None
    if (
        application.state.postgres is not None
        and application.state.sqs is not None
        and servicenow is not None
    ):
        try:
            from services.closure import ClosureService

            closure_service = ClosureService(
                postgres=application.state.postgres,
                servicenow=servicenow,
                eventbridge=application.state.eventbridge,
                sqs=application.state.sqs,
                episodic_memory_writer=episodic_memory_writer,
                settings=settings,
            )
            application.state.closure_service = closure_service
            logger.info("Closure Service ready")
        except Exception:
            logger.warning("Closure Service init failed")
            application.state.closure_service = None
    else:
        application.state.closure_service = None

    # --- Phase 6 SLA Monitor background task ---
    # Scans workflow.sla_checkpoints every sla_monitor_interval_seconds
    # and fires SLAWarning70 / SLAEscalation85 / SLAEscalation95 events.
    sla_monitor = None
    sla_monitor_task: asyncio.Task | None = None
    if application.state.postgres is not None and application.state.eventbridge is not None:
        try:
            from services.sla_monitor import SlaMonitor

            sla_monitor = SlaMonitor(
                postgres=application.state.postgres,
                eventbridge=application.state.eventbridge,
                settings=settings,
            )
            application.state.sla_monitor = sla_monitor
            sla_monitor_task = asyncio.create_task(sla_monitor.start_monitor_loop())
            logger.info(
                "SLA monitor started",
                interval_seconds=settings.sla_monitor_interval_seconds,
            )
        except Exception:
            logger.warning("SLA monitor start failed")
            application.state.sla_monitor = None
    else:
        application.state.sla_monitor = None

    # --- Phase 6 Auto-Close Scheduler background task ---
    # Scans workflow.closure_tracking hourly and closes any case whose
    # auto_close_deadline has passed without a vendor confirmation.
    auto_close_scheduler = None
    auto_close_task: asyncio.Task | None = None
    if closure_service is not None:
        try:
            from services.auto_close_scheduler import AutoCloseScheduler

            auto_close_scheduler = AutoCloseScheduler(
                postgres=application.state.postgres,
                closure_service=closure_service,
                settings=settings,
            )
            application.state.auto_close_scheduler = auto_close_scheduler
            auto_close_task = asyncio.create_task(auto_close_scheduler.start_loop())
            logger.info(
                "Auto-close scheduler started",
                interval_seconds=settings.auto_close_interval_seconds,
            )
        except Exception:
            logger.warning("Auto-close scheduler start failed")
            application.state.auto_close_scheduler = None
    else:
        application.state.auto_close_scheduler = None

    # --- Store settings for route handlers ---
    application.state.settings = settings

    logger.info("VQMS startup complete — all connectors initialized")

    yield  # App runs here

    # --- Shutdown ---
    logger.info("VQMS shutting down")

    if sla_monitor is not None:
        sla_monitor.stop()
    if sla_monitor_task is not None:
        sla_monitor_task.cancel()
        try:
            await sla_monitor_task
        except (asyncio.CancelledError, Exception):
            pass
        logger.info("SLA monitor stopped")

    if auto_close_scheduler is not None:
        auto_close_scheduler.stop()
    if auto_close_task is not None:
        auto_close_task.cancel()
        try:
            await auto_close_task
        except (asyncio.CancelledError, Exception):
            pass
        logger.info("Auto-close scheduler stopped")

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
