# Phase 1: Foundation and Data Layer — Implementation Plan

## Context

VQMS is a fresh project with only a stub `main.py`, empty `pyproject.toml`, and a comprehensive `CLAUDE.md` (1650 lines of architecture). No folder structure, dependencies, models, or database schema exist yet. Phase 1 establishes the foundation that all subsequent phases depend on: project skeleton, configuration, utilities, Pydantic models, database schema, and the PostgreSQL connector with SSH tunnel support.

**Security Note:** The existing `.env` contains real AWS credentials, OpenAI API keys, Graph API secrets, Salesforce passwords, and RDS credentials. These must NEVER be committed. The `.gitignore` must be created before any git operations.

---

## Key Decisions

| Decision | Resolution | Rationale |
|----------|-----------|-----------|
| OpenAI in settings.py? | **Yes** — include both Bedrock and OpenAI sections | `.env` uses `LLM_PROVIDER=openai_only`; team's current reality. Costs nothing to support both. |
| APP_*_BACKEND flags? | **No** — remove from `.env.copy` | CLAUDE.md says "no local fallback — cloud only". Keep `APP_SECRETS_BACKEND=env` only. |
| `.env.copy` sanitization | Use CLAUDE.md template + add OpenAI section with placeholders | Real credentials must never appear in committed files |

---

## Step 1: Project Skeleton

**Goal:** Full folder structure, dependencies, config files. No business logic.

### Directories to create (with empty `__init__.py`):
- `models/`, `intake/`, `pipeline/`, `pipeline/nodes/`, `connectors/`, `config/`, `utils/`, `tests/`, `tests/evals/`

### Directories to create (no `__init__.py`):
- `pipeline/prompts/`, `db/migrations/`, `tests/evals/golden_sets/`, `data/knowledge_base/`, `data/storage/`, `data/logs/`, `notebooks/`, `tasks/`

### Root files to create:
- `.gitignore` — `.env`, `__pycache__/`, `*.pyc`, `.venv/`, `data/logs/`, `data/storage/`, `uv.lock`, `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`, `*.egg-info/`, `dist/`, `build/`, `.idea/`, `.vscode/`, `*.pem`
- `.ruff.toml` — target Python 3.12, line-length 120, select E/F/W/I rules
- `.env.copy` — sanitized template from CLAUDE.md + OpenAI section with placeholders
- `tasks/todo.md` — Phase 1 checklist
- `tasks/lessons.md` — empty with header
- `Flow.md` — initial placeholder
- `docs/api.md`, `docs/architecture.md` — empty placeholders

### Files to modify:
- `pyproject.toml` — add ALL dependencies from CLAUDE.md (40+ packages) + `openai` package + dev dependency group
- `.python-version` — already "3.12", no change needed
- `main.py` — update to FastAPI app stub with health check
- `README.md` — write initial project overview

### Verification:
```bash
uv sync
uv run python -c "import models; import intake; import pipeline; import connectors; import config; import utils"
```

---

## Step 2: config/settings.py

**Goal:** Single `Settings` class via pydantic-settings loading all `.env` variables.

### File: `config/settings.py`
- One `Settings(BaseSettings)` class with `SettingsConfigDict(env_file=".env")`
- 20 field groups: APP, AWS, LLM Provider, Bedrock LLM, Bedrock Embeddings, OpenAI, PostgreSQL, SSH Tunnel, pgvector, Graph API, Salesforce, ServiceNow, S3, SQS, EventBridge, Cognito, Portal, SLA, Agent, KB Search
- `get_settings()` singleton function (create once, cache in module-level variable)
- Re-export from `config/__init__.py`

### Key fields:
- `llm_provider: Literal["bedrock_only", "openai_only", "bedrock_with_openai_fallback", "openai_with_bedrock_fallback"]`
- `embedding_provider: Literal[...]` (same options)
- `openai_api_key: str | None = None` (optional — only needed when provider is openai)
- All thresholds as configurable fields with defaults matching `.env` values

### Verification:
```bash
uv run python -c "from config.settings import get_settings; s = get_settings(); print(s.app_name, s.llm_provider)"
```

---

## Step 3: Utility Modules

### 3a. `utils/helpers.py`
- `class TimeHelper` — `ist_now() -> datetime` using `ZoneInfo("Asia/Kolkata")`, returns naive datetime
- `class IdGenerator` — `generate_query_id(prefix="VQ") -> str` (VQ-2026-XXXX format, UUID-based sequence for now with TODO for DB counter), `generate_correlation_id() -> str`, `generate_execution_id() -> str`

### 3b. `utils/logging_setup.py`
- `@dataclass class LogContext` — `correlation_id`, `step_name`, `query_id`, `vendor_id`
- `class LoggingSetup` — `configure()` sets up structlog with JSON rendering, IST timestamper, rotating file handler (`data/logs/vqms.log`, 10MB, 5 backups), suppresses noisy loggers (uvicorn, httpx, boto)

### 3c. `utils/exceptions.py`
- Base: `VQMSError(Exception)` with `correlation_id` attribute
- Subclasses: `DuplicateQueryError`, `VendorNotFoundError`, `KBSearchTimeoutError`, `QualityGateFailedError`, `SLABreachedError`, `BedrockTimeoutError`, `GraphAPIError`
- Each stores context fields as attributes for structured logging

### 3d. `utils/decorators.py`
- `@log_api_call` — wraps FastAPI handlers, extracts correlation_id from headers, logs entry/exit with duration_ms
- `@log_service_call` — wraps service/connector methods, logs function name + duration
- `@log_llm_call` — wraps LLM calls, logs tokens_in/out, cost, model, latency
- `@log_policy_decision` — wraps confidence/routing decisions, logs threshold + outcome
- All handle both sync and async via `functools.wraps` + `asyncio.iscoroutinefunction` check

### Verification:
```bash
uv run python -c "from utils.helpers import TimeHelper; print(TimeHelper.ist_now())"
uv run python -c "from utils.helpers import IdGenerator; print(IdGenerator.generate_correlation_id())"
uv run python -c "from utils.logging_setup import LoggingSetup; LoggingSetup.configure()"
```

---

## Step 4: All Pydantic Models

**Goal:** All 11 model files + PipelineState TypedDict + unit tests.

### Files and key classes:

| File | Classes | Key validations |
|------|---------|-----------------|
| `models/email.py` | `EmailAttachment`, `ParsedEmailPayload` | source must be "email" |
| `models/query.py` | `QuerySubmission`, `UnifiedQueryPayload` | subject 5-500 chars, description 10-5000 chars |
| `models/vendor.py` | `VendorTier`, `VendorProfile`, `VendorMatch` | tier is Literal enum |
| `models/analysis.py` | `AnalysisResult` | confidence_score 0.0-1.0 |
| `models/routing.py` | `RoutingDecision`, `SLATarget` | — |
| `models/kb.py` | `KBArticleMatch`, `KBSearchResult` | similarity_score 0.0-1.0 |
| `models/ticket.py` | `TicketCreateRequest`, `TicketInfo` | ticket_id format INC-XXXXXXX |
| `models/draft.py` | `DraftResponse`, `QualityGateResult` | draft_type Literal, confidence 0.0-1.0 |
| `models/triage.py` | `TriagePackage`, `ReviewerDecision` | references other models |
| `models/memory.py` | `EpisodicMemoryEntry`, `VendorContext` | resolution_path Literal["A","B","C"] |
| `models/pipeline_state.py` | `PipelineState` (TypedDict) | Not a BaseModel — LangGraph requirement |

### All BaseModels use:
- `model_config = ConfigDict(frozen=True)` for immutability
- `Field(description="...")` on every field
- Module-level docstring

### Test file: `tests/test_models.py`
- Valid data construction for every model
- Invalid data rejection (ValidationError) for key constraints
- Frozen immutability check (assignment raises error)
- ~30-40 test cases total

### Verification:
```bash
uv run pytest tests/test_models.py -v
```

---

## Step 5: Database Schema + PostgreSQL Connector

### 5a. SQL Migrations (`db/migrations/`)

| File | What it creates |
|------|----------------|
| `001_create_schemas.sql` | 6 schemas: intake, workflow, audit, memory, reporting, cache |
| `002_enable_pgvector.sql` | `CREATE EXTENSION IF NOT EXISTS vector` |
| `003_create_intake_tables.sql` | `intake.email_messages`, `intake.email_attachments` |
| `004_create_workflow_tables.sql` | `workflow.case_execution`, `workflow.ticket_link`, `workflow.routing_decision` |
| `005_create_audit_tables.sql` | `audit.action_log`, `audit.validation_results` |
| `006_create_memory_tables.sql` | `memory.episodic_memory`, `memory.vendor_profile_cache`, `memory.embedding_index` (vector(1536) + HNSW index) |
| `007_create_reporting_tables.sql` | `reporting.sla_metrics` |
| `008_create_cache_tables.sql` | `cache.idempotency_keys` (UNIQUE on key), `cache.vendor_cache`, `cache.workflow_state_cache` |

### 5b. `connectors/postgres.py` — `PostgresConnector` class

**Key methods:**
- `__init__(settings)` — stores config
- `async connect()` — creates SSH tunnel via `sshtunnel.SSHTunnelForwarder`, then `asyncpg.create_pool` on tunnel's local port
- `async disconnect()` — closes pool + tunnel
- `async execute(query, *args)` — run SQL
- `async fetch(query, *args)` — fetch rows as list[dict]
- `async fetchrow(query, *args)` — fetch single row
- `async check_idempotency(key, source, correlation_id) -> bool` — `INSERT ON CONFLICT DO NOTHING`, returns True if new
- `async run_migrations(migrations_dir)` — reads and executes SQL files in order

**Windows note:** SSH key path uses backslashes — use `pathlib.Path` to normalize.

### 5c. Tests: `tests/test_postgres_connector.py`
- Unit tests with mocked asyncpg pool for idempotency logic
- Integration tests marked `@pytest.mark.integration` for real SSH tunnel connection

### Verification:
```bash
# Run migrations against RDS via SSH tunnel
# Verify schemas exist: SELECT schema_name FROM information_schema.schemata
# Test idempotency: first insert True, second insert False
```

---

## Step 6: Gate Check

### Checklist:
- [ ] All models validate with sample data — `uv run pytest tests/test_models.py`
- [ ] Migrations ran — all 6 schemas + tables exist in RDS
- [ ] pgvector extension enabled — can store/query vectors
- [ ] PostgreSQL connector connects via SSH tunnel, runs queries
- [ ] Idempotency works — first insert True, second False
- [ ] Logging produces JSON with correlation_id field
- [ ] `uv run ruff check .` — 0 errors
- [ ] `uv run pytest` — all green
- [ ] `Flow.md` updated with Phase 1 state
- [ ] `README.md` updated with setup instructions + current state
- [ ] `tasks/todo.md` updated — Phase 1 items marked complete

---

## Risks

| Risk | Mitigation |
|------|-----------|
| `pgvector` extension requires RDS superuser | Test `CREATE EXTENSION` early; ask DevOps if permission denied |
| `sshtunnel` on Windows with .pem key | Test SSH tunnel connection in Step 5 before writing full connector |
| Large dependency tree conflicts | Run `uv sync` in Step 1; resolve conflicts immediately |
| `asyncpg` + SSH tunnel lifecycle | Add health check method; simple reconnect in dev mode |

---

## File Count: ~53 new files, ~5 modified
