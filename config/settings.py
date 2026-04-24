"""Module: config/settings.py

Application configuration for VQMS.

Loads all environment variables from .env using pydantic-settings.
Every threshold, credential, and connection string is configurable
via environment variables — nothing is hardcoded.

Usage:
    from config.settings import get_settings
    settings = get_settings()
    print(settings.app_name)  # "vqms"
"""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """VQMS application settings loaded from environment variables.

    All fields map directly to environment variable names (case-insensitive).
    Optional fields default to None when not set in .env.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ===========================
    # APPLICATION
    # ===========================
    app_env: str = "development"
    app_name: str = "vqms"
    app_version: str = "0.1.0"
    app_debug: bool = True
    app_port: int = 8000
    log_level: str = "DEBUG"
    correlation_id_header: str = "X-Correlation-ID"
    app_secrets_backend: str = "env"

    # ===========================
    # JWT AUTHENTICATION
    # ===========================
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    session_timeout_seconds: int = 1800
    token_refresh_threshold_seconds: int = 300

    # ===========================
    # AWS GENERAL
    # ===========================
    aws_region: str = "us-east-1"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None
    aws_account_id: str | None = None

    # ===========================
    # LLM PROVIDER
    # ===========================
    # NOTE: CLAUDE.md specifies Bedrock as primary. OpenAI config exists for dev flexibility.
    llm_provider: Literal[
        "bedrock_only",
        "openai_only",
        "bedrock_with_openai_fallback",
        "openai_with_bedrock_fallback",
    ] = "bedrock_with_openai_fallback"
    embedding_provider: Literal[
        "bedrock_only",
        "openai_only",
        "bedrock_with_openai_fallback",
        "openai_with_bedrock_fallback",
    ] = "bedrock_with_openai_fallback"

    # ===========================
    # AMAZON BEDROCK (LLM)
    # ===========================
    # Cross-region inference profile ARN — required for Claude 4+ models.
    # Direct model IDs (anthropic.claude-*) no longer support on-demand
    # throughput for newer models. Use the "us." prefix inference profile.
    bedrock_model_id: str = "us.anthropic.claude-sonnet-4-20250514-v1:0"
    bedrock_region: str = "us-east-1"
    bedrock_max_tokens: int = 4096
    bedrock_temperature: float = 0.1
    bedrock_fallback_model_id: str = "anthropic.claude-3-haiku-20240307-v1:0"
    bedrock_max_retries: int = 3
    bedrock_timeout_seconds: int = 30

    # ===========================
    # AMAZON BEDROCK (Embeddings)
    # ===========================
    bedrock_embedding_model_id: str = "amazon.titan-embed-text-v2:0"
    # Titan Embed v2 supports: 256, 512, 1024 only. NOT 1536.
    # v1 had fixed 1536 dims but doesn't accept dimensions/normalize params.
    bedrock_embedding_dimensions: int = 1024

    # ===========================
    # OPENAI (Fallback / Alternative Provider)
    # ===========================
    openai_api_key: str | None = None
    openai_model_id: str = "gpt-4o"
    openai_embedding_model_id: str = "text-embedding-3-small"
    # Must match bedrock embedding dimensions so vectors are compatible
    openai_embedding_dimensions: int = 1024
    openai_max_tokens: int = 4096
    openai_temperature: float = 0.1
    openai_api_base_url: str = "https://api.openai.com/v1"

    # ===========================
    # POSTGRESQL DATABASE
    # ===========================
    # Two connection modes:
    #   1. LOCAL DEV: SSH tunnel via PEM file (set ssh_host + ssh_private_key_path)
    #   2. DEPLOYMENT: Direct connection via database_url (leave ssh_host empty)
    database_url: str | None = None  # postgresql+asyncpg://user:pass@host:5432/dbname
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "postgres"
    postgres_user: str = "postgres"
    postgres_password: str = ""
    postgres_pool_min: int = 5
    postgres_pool_max: int = 20

    # ===========================
    # SSH TUNNEL (Bastion -> RDS) — LOCAL DEV ONLY
    # ===========================
    # When ssh_host is set, connector uses SSH tunnel through bastion to RDS.
    # In deployment (same VPC), leave ssh_host empty and set database_url above.
    ssh_host: str | None = None
    ssh_port: int = 22
    ssh_username: str = "ec2-user"
    ssh_private_key_path: str | None = None
    rds_host: str | None = None
    rds_port: int = 5432

    # ===========================
    # PGVECTOR (Semantic Memory)
    # ===========================
    pgvector_dimensions: int = 1024
    pgvector_hnsw_m: int = 16
    pgvector_hnsw_ef_construction: int = 64

    # ===========================
    # MICROSOFT GRAPH API (Email)
    # ===========================
    graph_api_tenant_id: str | None = None
    graph_api_client_id: str | None = None
    graph_api_client_secret: str | None = None
    graph_api_mailbox: str = "vendorsupport@yourcompany.com"
    graph_api_poll_interval_seconds: int = 300
    graph_api_webhook_url: str | None = None

    # ===========================
    # SALESFORCE CRM (Vendor Resolution)
    # ===========================
    salesforce_instance_url: str = "https://login.salesforce.com"
    salesforce_username: str | None = None
    salesforce_password: str | None = None
    salesforce_security_token: str | None = None
    salesforce_consumer_key: str | None = None
    salesforce_consumer_secret: str | None = None

    # ===========================
    # SERVICENOW ITSM (Ticket Operations)
    # ===========================
    # You can configure ServiceNow with EITHER:
    #   (a) servicenow_instance_url — the full URL (e.g. https://dev123456.service-now.com), OR
    #   (b) servicenow_instance_name — just the instance short name (e.g. dev123456);
    #       the adapter will build the URL as https://<name>.service-now.com
    # If both are set, servicenow_instance_url wins.
    servicenow_instance_url: str | None = None
    servicenow_instance_name: str | None = None
    servicenow_username: str | None = None
    servicenow_password: str | None = None
    servicenow_client_id: str | None = None
    servicenow_client_secret: str | None = None
    servicenow_assignment_group: str | None = None

    # ===========================
    # AWS S3 (Storage — single bucket, prefix-organized)
    # ===========================
    s3_bucket_data_store: str = "vqms-data-store-001 "

    # ===========================
    # AWS SQS (Queues)
    # ===========================
    sqs_queue_prefix: str = "vqms-"
    sqs_dlq_name: str = "vqms-dlq"
    sqs_max_receive_count: int = 3
    sqs_visibility_timeout: int = 300
    sqs_email_intake_queue_url: str = ""
    sqs_query_intake_queue_url: str = ""
    sqs_email_intake_queue: str = "vqms-email-intake-queue"
    sqs_query_intake_queue: str = "vqms-query-intake-queue"

    # ===========================
    # AWS EVENTBRIDGE (Events)
    # ===========================
    eventbridge_bus_name: str = "vqms-event-bus"
    eventbridge_source: str = "com.vqms"

    # ===========================
    # AWS COMPREHEND (PII Detection)
    # ===========================
    comprehend_language_code: str = "en"

    # ===========================
    # AWS COGNITO (Auth)
    # ===========================
    cognito_user_pool_id: str | None = None
    cognito_client_id: str | None = None
    cognito_domain: str | None = None

    # ===========================
    # PORTAL CONFIGURATION
    # ===========================
    portal_session_ttl_hours: int = 8
    portal_query_id_prefix: str = "VQ"
    portal_sso_enabled: bool = False
    portal_sso_provider: str | None = None
    portal_sso_metadata_url: str | None = None

    # ===========================
    # SLA CONFIGURATION
    # ===========================
    sla_warning_threshold_percent: int = 70
    sla_l1_escalation_threshold_percent: int = 85
    sla_l2_escalation_threshold_percent: int = 95
    sla_default_hours: int = 24

    # ===========================
    # PHASE 6 — SLA MONITOR + CLOSURE
    # ===========================
    # How often the SlaMonitor scans workflow.sla_checkpoints (seconds).
    # Kept short because a missed threshold crossing delays escalation.
    sla_monitor_interval_seconds: int = 60

    # How often AutoCloseScheduler scans workflow.closure_tracking (seconds).
    # Hourly is fine — the auto-close deadline is measured in business days.
    auto_close_interval_seconds: int = 3600

    # Business days between sending a resolution and auto-closing the case.
    auto_close_business_days: int = 5

    # Days after closure during which a vendor reply REOPENS the same case.
    # Outside this window, a reply creates a new linked query_id.
    closure_reopen_window_days: int = 7

    # Keyword match for vendor confirmation detection on replies to a closed
    # or open case. Case-insensitive substring match against the email body.
    # Kept simple — LLM-based intent classification would be overkill here.
    confirmation_keywords: list[str] = [
        "thanks",
        "thank you",
        "resolved",
        "fixed",
        "that worked",
        "works now",
        "appreciate it",
    ]

    # ===========================
    # AGENT CONFIGURATION
    # ===========================
    agent_confidence_threshold: float = 0.85
    agent_max_hops: int = 4
    agent_budget_max_tokens_in: int = 8000
    agent_budget_max_tokens_out: int = 4096
    agent_budget_currency_limit_usd: float = 0.50

    # ===========================
    # KB SEARCH CONFIGURATION
    # ===========================
    kb_match_threshold: float = 0.80
    kb_max_results: int = 5
    kb_resolution_confidence_threshold: float = 0.85

    # ===========================
    # EMAIL RELEVANCE FILTER
    # ===========================
    # Minimum non-whitespace chars across (subject + body) required
    # for an email to be considered substantive enough for the AI
    # pipeline. Kept small so a short-but-real query like
    # "Invoice INV-5678 is $0, please check" still passes.
    email_filter_min_chars: int = 30

    # Case-insensitive words/phrases that, when they make up the
    # entire meaningful content of an email, mark it as noise.
    # Matched against the stripped subject+body text.
    email_filter_noise_patterns: list[str] = [
        "hi",
        "hello",
        "hey",
        "thanks",
        "thank you",
        "ok",
        "okay",
        "noted",
        "received",
        "got it",
        "test",
    ]

    # Gated off in dev to avoid spending on Haiku for every borderline
    # email. Enable in staging/prod once we've seen real traffic.
    email_filter_use_llm_classifier: bool = False

    # Sender domains always allowed even when Salesforce cannot resolve
    # the vendor (e.g. a newly-onboarded vendor whose contact isn't
    # synced yet). Leave empty to reject every unresolved sender.
    email_filter_allowed_sender_domains: list[str] = []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def aws_credentials_kwargs(self) -> dict[str, str]:
        """Return AWS credential kwargs for ``boto3.client(...)``.

        Only includes keys whose values are set in ``.env``. When a key is
        missing, boto3 falls back to its default credential chain (shell
        env vars, ``~/.aws/credentials``, IAM role). Passing ``None``
        explicitly would override that chain, so we filter empties out.
        """
        kwargs: dict[str, str] = {}
        if self.aws_access_key_id:
            kwargs["aws_access_key_id"] = self.aws_access_key_id
        if self.aws_secret_access_key:
            kwargs["aws_secret_access_key"] = self.aws_secret_access_key
        if self.aws_session_token:
            kwargs["aws_session_token"] = self.aws_session_token
        return kwargs


# Module-level singleton — created once, reused across the app
_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the application settings singleton.

    Creates the Settings instance on first call, then returns
    the cached instance on subsequent calls. This avoids re-reading
    .env on every import.
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
