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

from utils.log_types import LOG_TYPE_APPLICATION
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
    # and manage JWT blacklist in cache.kv_store. The Salesforce
    # connector is wired in below so init_auth_service can be called
    # *after* the SF connector is constructed (the gate checks vendor
    # registration before issuing the JWT).

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

    # Initialize the auth service now that both connectors are known.
    # When salesforce is None (init failed), the login gate falls back
    # to cache.vendor_cache for vendor verification.
    if postgres is not None:
        from services.auth import init_auth_service

        init_auth_service(postgres, salesforce=salesforce)
        logger.info(
            "Auth service initialized",
            salesforce_wired=salesforce is not None,
        )

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

    # --- Create Textract connector ---
    # Optional — used by the portal attachment pipeline to OCR PDFs and
    # images before falling back to pdfplumber. If office IAM lacks
    # textract:DetectDocumentText the adapter still constructs cleanly;
    # actual calls will fail with AccessDenied and the extractor falls
    # through to pdfplumber.
    try:
        from adapters.textract import TextractConnector

        application.state.textract = TextractConnector(settings)
        logger.info("Textract connector ready", tool="textract")
    except Exception:
        logger.warning("Textract connector init failed", tool="textract")
        application.state.textract = None

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

    # --- Execution Trail Service ---
    # Per-query observability — every pipeline step writes one row to
    # audit.action_log so the admin /queries/:id timeline can render the
    # full path of the query through the system. Required for the LLM
    # decorator, the LangGraph node wrapper, and the intake services.
    trail_service = None
    if application.state.postgres is not None:
        try:
            from services.execution_trail import ExecutionTrailService
            from utils.context import set_trail_service

            trail_service = ExecutionTrailService(application.state.postgres)
            set_trail_service(trail_service)
            application.state.trail_service = trail_service
            logger.info("Execution Trail Service ready")
        except Exception:
            logger.warning("Execution Trail Service init failed")
            application.state.trail_service = None
    else:
        application.state.trail_service = None

    # --- Create Portal Intake Service ---
    # Wires postgres + sqs + eventbridge with the attachment pipeline
    # connectors (s3, textract, llm_gateway). s3/llm_gateway/textract
    # default to None upstream, so the service degrades gracefully when
    # any of them is missing — attachments and/or entity extraction are
    # then skipped instead of failing the submission.
    try:
        from services.portal_intake import PortalIntakeService

        application.state.portal_intake = PortalIntakeService(
            postgres=application.state.postgres,
            sqs=application.state.sqs,
            eventbridge=application.state.eventbridge,
            settings=settings,
            s3=application.state.s3,
            llm_gateway=application.state.llm_gateway,
            textract=application.state.textract,
        )
        logger.info("Portal Intake Service ready")
    except Exception:
        logger.warning("Portal Intake Service init failed", exc_info=True)
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

    # --- Draft Approval Service ---
    # Backs the admin draft-approval queue. Path A queries halt at
    # PENDING_APPROVAL after ticket creation; this service lists them,
    # sends the email when an admin approves, and flips status to RESOLVED.
    if (
        application.state.postgres is not None
        and graph_api is not None
    ):
        try:
            from services.draft_approval import DraftApprovalService

            application.state.draft_approval_service = DraftApprovalService(
                postgres=application.state.postgres,
                graph_api=graph_api,
                closure_service=closure_service,
            )
            logger.info("Draft Approval Service ready")
        except Exception:
            logger.warning("Draft Approval Service init failed")
            application.state.draft_approval_service = None
    else:
        application.state.draft_approval_service = None

    # --- Email Intake Service ---
    # Wires the 6 helper classes inside email_intake/ together with the
    # connectors. Webhook handler (POST /webhooks/ms-graph) and the
    # reconciliation poller both call email_intake.process_email().
    email_intake = None
    bedrock_for_filter = None
    if (
        application.state.postgres is not None
        and application.state.s3 is not None
        and application.state.sqs is not None
        and application.state.eventbridge is not None
        and graph_api is not None
        and salesforce is not None
    ):
        try:
            from adapters.bedrock import BedrockConnector
            from services.email_intake import EmailIntakeService

            # Bedrock is optional — only used by the relevance filter's
            # Layer 4 LLM classifier, which is off by default.
            try:
                bedrock_for_filter = BedrockConnector(settings)
            except Exception:
                bedrock_for_filter = None

            email_intake = EmailIntakeService(
                graph_api=graph_api,
                postgres=application.state.postgres,
                s3=application.state.s3,
                sqs=application.state.sqs,
                eventbridge=application.state.eventbridge,
                salesforce=salesforce,
                settings=settings,
                closure_service=closure_service,
                bedrock=bedrock_for_filter,
            )
            application.state.email_intake = email_intake
            logger.info("Email Intake Service ready")
        except Exception:
            logger.warning(
                "Email Intake Service init failed — webhook + poller "
                "will not work"
            )
            application.state.email_intake = None
    else:
        application.state.email_intake = None

    # --- Email Reconciliation Poller background task ---
    # Catches anything the Graph webhook missed via /messages/delta.
    # Persists the deltaLink in cache.kv_store between cycles so we
    # only fetch what changed since last poll.
    email_poller = None
    email_poller_task: asyncio.Task | None = None
    if email_intake is not None and graph_api is not None:
        try:
            from services.polling import EmailReconciliationPoller

            email_poller = EmailReconciliationPoller(
                email_intake=email_intake,
                graph_api=graph_api,
                postgres=application.state.postgres,
                sqs=application.state.sqs,
                settings=settings,
            )
            application.state.email_poller = email_poller
            email_poller_task = asyncio.create_task(
                email_poller.start_polling_loop()
            )
            logger.info(
                "Email reconciliation poller started",
                interval_seconds=settings.graph_api_poll_interval_seconds,
            )
        except Exception:
            logger.warning("Email reconciliation poller start failed")
            application.state.email_poller = None
    else:
        application.state.email_poller = None

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

    # --- Pipeline Consumer background task ---
    # Builds the LangGraph pipeline (Steps 7-12 + Path C + Step 15) and
    # starts the SQS consumer that long-polls vqms-email-intake-queue and
    # vqms-query-intake-queue. Without this task running, portal/email
    # submissions land on SQS and never reach Quality Gate or the admin
    # draft-approval queue. All required connectors must be live —
    # otherwise the pipeline cannot run, so skip and log.
    pipeline_consumer = None
    pipeline_consumer_task: asyncio.Task | None = None
    pipeline_required = (
        application.state.postgres is not None
        and application.state.llm_gateway is not None
        and application.state.salesforce is not None
        and application.state.sqs is not None
        and servicenow is not None
        and graph_api is not None
    )
    if pipeline_required:
        try:
            from orchestration.dependencies import create_pipeline

            _, pipeline_consumer = create_pipeline(
                settings=settings,
                postgres=application.state.postgres,
                llm_gateway=application.state.llm_gateway,
                salesforce=application.state.salesforce,
                sqs=application.state.sqs,
                servicenow=servicenow,
                graph_api=graph_api,
                eventbridge=application.state.eventbridge,
            )
            application.state.pipeline_consumer = pipeline_consumer
            pipeline_consumer_task = asyncio.create_task(
                pipeline_consumer.consume_both_queues()
            )
            logger.info(
                "Pipeline consumer started",
                email_queue=settings.sqs_email_intake_queue_url,
                query_queue=settings.sqs_query_intake_queue_url,
            )
        except Exception:
            logger.exception(
                "Pipeline consumer start failed — SQS messages will pile up"
            )
            application.state.pipeline_consumer = None
    else:
        logger.warning(
            "Pipeline consumer not started — required connector(s) missing",
            postgres_ready=application.state.postgres is not None,
            llm_gateway_ready=application.state.llm_gateway is not None,
            salesforce_ready=application.state.salesforce is not None,
            sqs_ready=application.state.sqs is not None,
            servicenow_ready=servicenow is not None,
            graph_api_ready=graph_api is not None,
        )
        application.state.pipeline_consumer = None

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

    logger.info(
        "VQMS startup complete — all connectors initialized",
        log_type=LOG_TYPE_APPLICATION,
    )

    yield  # App runs here

    # --- Shutdown ---
    logger.info("VQMS shutting down", log_type=LOG_TYPE_APPLICATION)

    # Stop the pipeline consumer FIRST so it stops pulling new SQS
    # messages before we tear down the connectors it depends on
    # (postgres, graph_api, servicenow, etc.). PipelineConsumer.stop()
    # only flips a flag — the long-poll loop returns on the next receive
    # cycle (up to 20s), so we also cancel the task so shutdown is
    # bounded.
    if pipeline_consumer is not None:
        pipeline_consumer.stop()
    if pipeline_consumer_task is not None:
        pipeline_consumer_task.cancel()
        try:
            await pipeline_consumer_task
        except (asyncio.CancelledError, Exception):
            pass
        logger.info("Pipeline consumer stopped")

    if email_poller is not None:
        email_poller.stop()
    if email_poller_task is not None:
        email_poller_task.cancel()
        try:
            await email_poller_task
        except (asyncio.CancelledError, Exception):
            pass
        logger.info("Email reconciliation poller stopped")

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

    logger.info("VQMS shutdown complete", log_type=LOG_TYPE_APPLICATION)
