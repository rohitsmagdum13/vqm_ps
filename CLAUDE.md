# CLAUDE.md — VQMS Agentic AI Platform

## Project Identity
- **Project:** VQMS (Vendor Query Management System) Agentic AI Platform
- **Owner:** Hexaware Technologies
- **Stack:** Python 3.12+, FastAPI, LangGraph, Amazon Bedrock (Claude Sonnet 3.5 for inference, Titan Embed v2 for embeddings), AWS (SQS, EventBridge, S3, CloudWatch, Cognito), PostgreSQL (pgvector), Microsoft Graph API, Salesforce CRM, ServiceNow ITSM, Angular (portal frontend)
- **Package Manager:** uv — all dependency management, virtual env creation, and script running via `uv` only. Never use pip directly.
- **Entry Points:** Two — Email (vendor-support@company.com via Graph API) and Portal (VQMS web portal via API Gateway + Cognito). Both converge into the same AI pipeline after ingestion.
- **Processing Paths:** Three — Path A (AI-Resolved: KB has the answer), Path B (Human-Team-Resolved: KB lacks specific facts, human team investigates), Path C (Low-Confidence: AI unsure, human reviewer validates before proceeding to A or B)
- **Key Constraint:** No Redis anywhere in the stack. PostgreSQL handles all persistent storage, idempotency checks (INSERT ON CONFLICT), short-lived caching (TTL-based cleanup), and vector search (pgvector). This simplifies infrastructure and reduces operational overhead.
- **Architecture:** Multi-agent orchestration via LangGraph state machine, 8-phase bottom-up build plan, 6 business flow variants + 3 processing paths, two-tier memory (PostgreSQL persistent + pgvector semantic / in-graph agent state)

---

## Claude Code Instructions

This file is read automatically by Claude Code at the start of every session. Follow every rule in this file strictly.

### Session Start Checklist
1. Read this `CLAUDE.md` file (you're doing this now)
2. Read `tasks/lessons.md` to review past mistakes and avoid repeating them
3. Read `tasks/todo.md` to see current progress and what's next
4. Read `Flow.md` to understand the current state of the pipeline
5. For detailed reference on phases, module breakdowns, and implementation strategy, read `docs/references/VQMS_Implementation_Plan.docx`

### File Creation Rules
- Always create files from the project root directory
- Use the exact folder structure defined in this file — do not create folders that are not listed here
- Every Python file must have a module-level docstring as its first line
- Every `__init__.py` can be empty but must exist for Python imports to work
- Run `uv run ruff check .` and `uv run pytest` after creating files to verify

### Code Style Rules (ALWAYS ENFORCED)
- **Class-based architecture only.** All services, connectors, pipeline nodes, and business logic must be implemented as classes — not standalone functions. Each module should have a primary class that encapsulates its behavior. Keep classes simple, readable, and single-responsibility.
- **Simple and easy to understand.** Write code that a junior developer can read in one pass. No clever abstractions, no over-engineered patterns. If a class is getting complex, split it into smaller classes.
- **README.md from the start.** Every change, every new file, every new feature, every phase — update `README.md` in the same session. README.md must always reflect the current state of the project. This is not optional and applies from the very first commit.

### Structured Logging Standard (ALWAYS ENFORCED)
- **Direct structlog usage.** All application code uses `import structlog` / `logger = structlog.get_logger(__name__)`. Never use `import logging` / `logging.getLogger()` in application code — stdlib logging is only used inside `src/utils/logger.py` for third-party library log handling.
- **Keyword arguments, not extra dicts.** Log calls use structlog kwargs: `logger.info("msg", key=value)`. Never use `extra={"key": value}`.
- **`tool=` field on every adapter log line.** All adapters in `src/adapters/` must include `tool="<name>"` (e.g., `tool="s3"`, `tool="postgresql"`, `tool="sqs"`, `tool="eventbridge"`, `tool="graph_api"`, `tool="salesforce"`) in every log call for CloudWatch filtering.
- **IST timestamps.** All log timestamps use IST (Indian Standard Time). Never override to UTC.
- **contextvars for correlation_id.** Entry points call `structlog.contextvars.bind_contextvars(correlation_id=cid)` so downstream log calls automatically include it.
- **`LoggingSetup.configure()` at startup.** Called once in `main.py` (project root) after all imports, before `create_app()` is called.

### Frontend Rules (ALWAYS ENFORCED)
- **Angular 17+ strictly.** The frontend portal is built with Angular 17+ using standalone components and signals. Do NOT use React, Vue, Svelte, or any other frontend framework. All frontend code goes in `frontend/` and must be an Angular project.
- **Tailwind CSS** for all styling — no custom CSS frameworks
- Angular CLI for project scaffolding, component generation, and builds
- TypeScript strictly — no plain JavaScript files in the frontend

### What Claude Code Must NEVER Do
- Never commit `.env` — only `.env.copy` gets committed
- Never create deployment files (Dockerfile, CDK, Terraform) without explicit user approval
- Never skip writing docstrings or type hints to save time
- Never use `print()` — always use `structlog` with keyword arguments
- Never hardcode secrets, API keys, or credentials anywhere in code
- Never install packages with `pip` — always use `uv add`
- Never write `boto3` calls that create, delete, or modify AWS resources (create_bucket, create_queue, etc.) — we have limited office IAM privileges
- Never write CDK, SAM, CloudFormation, or Terraform code unless the user explicitly requests it

---

## Development Mode — READ THIS FIRST

**This project is in active DEVELOPMENT mode.** We are NOT writing production-grade code yet. The current focus is:

- **Clarity over cleverness.** Write code that a junior developer can read and understand in one pass. No clever one-liners, no premature abstractions.
- **Simple implementations.** Functions should do one thing, in the most straightforward way possible. If there is a simple approach and a sophisticated approach, pick the simple one.
- **Descriptive names everywhere.** Variable names, function names, class names, and file names should tell you exactly what they do. A good name removes the need for a comment.
- **Comments that explain WHY, not WHAT.** Every non-obvious decision gets a comment explaining the reasoning. Do not write comments that repeat what the code already says.
- **Working skeletons first, polish later.** Get the data flowing end-to-end with basic implementations before optimizing. Stubs and simple implementations are perfectly acceptable at this stage.
- **No over-engineering.** Do not add abstraction layers, design patterns, or infrastructure that is not needed right now. Add complexity only when a real problem forces it.

### What This Means in Practice

- Functions can use simple `if/else` instead of strategy patterns
- Error handling can use basic `try/except` with clear logging — no need for circuit breaker wrappers yet
- Configuration can use plain `.env` loading — no need for hierarchical YAML config merging yet
- Database queries can use straightforward SQL — no need for query builders or complex ORM patterns
- Tests should be simple and readable — basic `assert` statements, not complex test frameworks

**When we move to production**, we will layer on:
- Full circuit breaker and retry patterns
- Comprehensive OpenTelemetry tracing
- AWS-specific hardening (IAM roles, VPC, KMS encryption)
- Performance optimization and load testing
- Blue/green deployment and rollback procedures

---

## Enterprise / Office Project Constraints — READ THIS CAREFULLY

**This is a Hexaware office project.** We are working within a corporate AWS environment. We have **direct access** to pre-provisioned AWS services (S3, SQS, EventBridge, Bedrock) and PostgreSQL on RDS (via SSH tunnel through a bastion host). Claude Code must write all code with these constraints in mind.

### What This Means for Code

1. **No AWS resource creation from code.** We do NOT have permissions to create S3 buckets, SQS queues, EventBridge buses, or any other AWS resource programmatically. All AWS resources are **pre-provisioned by the infra/DevOps team**. Our code only **reads from and writes to** resources that already exist. Never write `boto3` calls that create, delete, or modify AWS resources (e.g., `create_bucket`, `create_queue`, `put_rule`).

2. **Use existing resource ARNs/names from environment variables.** Every AWS resource (bucket name, queue URL, event bus name) comes from `.env` or environment variables — never hardcoded, never created at runtime. If a resource doesn't exist yet, log an error and fail gracefully — do NOT attempt to create it.

3. **We HAVE access to these AWS services — code directly against them:**
   - **S3:** Read/write to pre-provisioned buckets. All connectors talk directly to real S3.
   - **SQS:** Read/write to pre-provisioned queues. All connectors talk directly to real SQS.
   - **EventBridge:** Publish events to the pre-provisioned event bus. All connectors talk directly to real EventBridge.
   - **Bedrock:** Invoke Claude Sonnet 3.5 and Titan Embed v2 models.
   - **PostgreSQL on RDS:** Access via SSH tunnel through a bastion host (see SSH tunnel section below).
   - We do NOT have permissions for: CloudFormation, CDK, Terraform, IAM policy changes, VPC modifications, KMS key creation.
   - Always wrap AWS calls in `try/except` with specific `botocore.exceptions.ClientError` handling. Check for `AccessDeniedException` and `UnauthorizedAccess` errors and log them clearly so we know it's a permissions issue, not a bug.

4. **No infrastructure-as-code unless explicitly requested.** Do not generate CDK, SAM, CloudFormation, Terraform, or Serverless Framework files. If the architecture doc mentions infrastructure definitions, write them as **reference documentation** in `docs/`, not as deployable code.

5. **Secrets come from environment variables, not Secrets Manager directly.** While the architecture doc references AWS Secrets Manager, in our dev environment we load secrets from `.env` files. The code should read from `os.environ` or `pydantic-settings`. Add a `# NOTE: In production, this will come from AWS Secrets Manager` comment where relevant, but do NOT write code that calls `secretsmanager:GetSecretValue` unless the user explicitly confirms we have that permission.

6. **Cloud-only connectors — NO local fallback mode.**
   - All connectors connect directly to real cloud services. There is NO "local" vs "aws" branching.
   - **S3:** `src/storage/s3_client.py` uses boto3 directly. No local filesystem fallback.
   - **SQS:** `src/queues/sqs.py` uses boto3 directly. No in-memory queue fallback.
   - **EventBridge:** `src/events/eventbridge.py` uses boto3 directly. No local event list fallback.
   - **PostgreSQL:** `src/db/connection/` (folder module) connects via SSH tunnel to bastion → RDS. No local SQLite fallback.
   - **Microsoft Graph API:** `src/adapters/graph_api/` (folder module) uses real MSAL auth + Graph API calls. No stub/mock.
   - **PostgreSQL:** Use real PostgreSQL on RDS via SSH tunnel.
   - For **testing**, use `moto` to mock AWS services. Tests do NOT require real AWS credentials.

7. **Adapter pattern — cloud-only, clean abstraction.** Every external system interaction MUST go through an adapter in `src/adapters/`. The adapter provides:
   - A clean async interface that the rest of the codebase imports
   - Proper error handling with `botocore.exceptions.ClientError`
   - Structured logging with correlation_id
   - No branching between local/cloud — only the cloud implementation exists

8. **PostgreSQL via SSH Tunnel.** The RDS instance is NOT directly accessible from local machines. All database connections go through an SSH tunnel to a bastion host:
   - Use the `sshtunnel` library to establish the tunnel
   - SSH config comes from env vars: `SSH_HOST`, `SSH_PORT`, `SSH_USERNAME`, `SSH_PRIVATE_KEY_PATH`, `RDS_HOST`, `RDS_PORT`
   - The tunnel must stay alive for the app lifetime and close on shutdown
   - Connection flow: local machine → SSH tunnel to bastion → bastion forwards to RDS

9. **Microsoft Graph API — real connection.** Email ingestion uses the real Microsoft Graph API:
   - MSAL library for OAuth2 client_credentials flow
   - Fetch emails via GET /users/{mailbox}/messages/{id}
   - Send emails via POST /users/{mailbox}/sendMail
   - Webhook subscription for real-time email detection
   - Reconciliation polling fallback every 5 minutes
   - Auth credentials from env: `GRAPH_API_TENANT_ID`, `GRAPH_API_CLIENT_ID`, `GRAPH_API_CLIENT_SECRET`, `GRAPH_API_MAILBOX`

### Rules Summary for Claude Code

| Situation | Do This | Do NOT Do This |
|-----------|---------|----------------|
| Need an S3 bucket | Read bucket name from env var, use boto3 connector | Call `create_bucket()` |
| Need an SQS queue | Read queue URL from env var, use boto3 connector | Call `create_queue()` |
| Need a secret | Read from `os.environ` | Call `secretsmanager:GetSecretValue` without permission |
| AWS call fails with AccessDenied | Log clearly, raise with context | Silently retry or swallow the error |
| Testing | Use `moto` mocks for AWS | Write "if local" / "if aws" branching |
| Infra setup needed | Document it in `docs/infra_requirements.md` | Write CDK/Terraform/CloudFormation code |
| Need database connection | Use SSH tunnel to bastion → RDS | Connect directly to RDS endpoint |
| Need to send/fetch email | Use MSAL + Graph API | Use stub/mock Graph client |

---

---

## Workflow Orchestration

### 1. Plan Before You Build
- For any non-trivial task (3+ steps), write a plan to `tasks/todo.md` first
- If something goes wrong, stop and re-plan — do not push forward blindly
- Before writing code, confirm: "Does this align with the architecture doc?"

### 2. Keep It Simple
- Start with the simplest working implementation
- Add complexity only when a real problem requires it
- If a function is getting long or confusing, split it into smaller named functions
- Prefer readability over performance at this stage

### 3. Self-Improvement Loop
- After any correction from the user, update `tasks/lessons.md` with the pattern
- Write a note for yourself that prevents the same mistake
- Review lessons at the start of each session

### 4. Verification Before Done
- Run `uv run ruff check .` for linting — fix any errors before moving on
- Run `uv run pytest` for tests — all tests must pass
- If either command fails, fix the issues immediately — do not ask the user what to do
- Check that requirements.txt includes all third-party packages used in the code
- Update `Flow.md` if any pipeline function was added, changed, or wired up

---

## Task Management

### Before Starting Any Task
1. Read `tasks/todo.md` — check what's already done and what's next
2. Read `tasks/lessons.md` — avoid repeating past mistakes
3. Identify which Phase (1-8) the task belongs to — never skip phases

### During a Task
1. **Plan First:** Write plan to `tasks/todo.md` with checkable items using `- [ ]` syntax
2. **Verify Plan:** Check in with the user before starting implementation
3. **Track Progress:** Mark items complete with `- [x]` as you go
4. **Explain Changes:** Give a high-level summary at each step
5. **Test:** Run `uv run pytest` and `uv run ruff check .` after creating/modifying files

### After a Task
1. Update `tasks/todo.md` with what was completed
2. If the user corrected you, add the lesson to `tasks/lessons.md` with this format:
   ```
   ## [Date] — Lesson Title
   **Mistake:** What I did wrong
   **Correction:** What the right approach is
   **Rule:** One-line rule to prevent this in the future
   ```

---

## Living Documentation Rules (ALWAYS ENFORCED)

Two files must stay current with the codebase at all times: `Flow.md` and `README.md`. Treat them like code — if the code changes, these files change in the same session.

### Flow.md — End-to-end runtime walkthrough

**Location:** `Flow.md` (project root)

**Purpose:** Trace exactly how a vendor query moves through the codebase, function by function. Must cover BOTH entry points (email and portal) and all three processing paths (A, B, C). A developer should read this file and know which file to open, which function to call, and what data goes in and out at every step.

**What goes in Flow.md:**
- Only document steps that have working code (or at least a function stub with `NotImplementedError`). Do not describe functions that do not exist in the codebase.
- For every step, include:
  - What triggers this step
  - Which exact file and function gets called (full path like `src/services/email_intake/` -> `fetch_and_parse_email()`)
  - What input it receives (which Pydantic model or raw type)
  - What it does internally (plain English, step by step)
  - What output it produces (which Pydantic model or raw type)
  - Where data gets stored (PostgreSQL table, S3 bucket, or local file)
  - What happens next and why
- If a step is a stub (`NotImplementedError` or `TODO`), include it but mark it clearly: `[STUB — not yet implemented]`
- At the bottom, keep a "What is not built yet" section listing architecture doc steps that have no code at all

**Format:** Numbered walkthrough. Plain English. No marketing language. Write like you're explaining the codebase to a new team member on their first day.

**When to update Flow.md:**
- After completing any phase (1 through 8)
- After adding or changing any function that appears in the query processing pipeline (email or portal path)
- After wiring up a new service, agent, connector, or gate
- After connecting any two components that were previously disconnected
- After implementing a new processing path branch (Path A, B, or C)

### README.md — Project overview and setup

**Location:** `README.md` (project root)

**Purpose:** A developer clones the repo, reads README.md, and knows: what this project does, how to set it up, how to run it, what the current state of development is, and where to find things.

**What goes in README.md:**
- Project name and one-paragraph description (what VQMS does, who it's for)
- Current development phase and what works right now
- Tech stack summary (not a wall of badges — just a plain list)
- Setup instructions: prerequisites, clone, install deps, configure .env, run migrations, start the app
- How to run tests
- Project structure overview (brief — point to CLAUDE.md for the full tree)
- Links to key docs (CLAUDE.md, Flow.md, architecture.md)
- Enterprise constraints note (limited AWS access, local dev mode)
- What is built vs. what is planned (keep this honest and current)

**When to update README.md:**
- After completing any phase
- After adding new setup steps (new dependency, new env var, new migration)
- After changing how to run the project
- After any change that would confuse a developer who last read the README a week ago

### Rules for Claude Code

1. **After every phase completion:** Update both `Flow.md` and `README.md` before reporting the phase as done. This is not optional.
2. **After any pipeline change:** If you add, rename, or rewire any function in the query processing pipeline (email or portal path), update `Flow.md` in the same session.
3. **After any setup change:** If you add a new package, env var, migration, or config file, update `README.md` in the same session.
4. **Never let docs drift from code.** If `Flow.md` describes a function that no longer exists, or `README.md` says "run X" but X has changed, that is a bug. Fix it immediately.
5. **Use real function names and file paths.** No placeholders like "the analysis module" — write `src/orchestration/nodes/query_analysis.py` -> `classify_query_intent()`.
6. **Write like a person, not a brochure.** No "leveraging", no "comprehensive suite of", no "seamlessly integrates". Say what the code does. Period.

---

## Coding Standards for Development Mode

### Naming Convention Rules (ALWAYS ENFORCED)

```python
# VARIABLES: snake_case — descriptive, reads like English
email_message = fetch_email(message_id)       # Good: clear what it holds
vendor_match_result = find_vendor(sender)      # Good: says exactly what it is
em = fetch(mid)                                # Bad: abbreviations are unclear
data = get_data()                              # Bad: "data" tells you nothing

# FUNCTIONS: snake_case — starts with a verb, says what it does
def parse_email_body(raw_html: str) -> str:    # Good: verb + what it acts on
def find_vendor_by_email(email: str):          # Good: specific about the lookup
def process(x):                                # Bad: vague verb, unclear input
def do_stuff():                                # Bad: tells you nothing

# CLASSES: PascalCase — noun, represents a thing or concept
class EmailMessage:                            # Good: clear domain object
class VendorResolutionService:                 # Good: says what the service does
class Helper:                                  # Bad: too vague
class Mgr:                                     # Bad: abbreviation

# CONSTANTS: UPPER_SNAKE_CASE — configuration values and fixed settings
MAX_RETRY_ATTEMPTS = 3                         # Good: clear setting name
DEFAULT_SLA_HOURS = 24                         # Good: includes the unit
CONFIDENCE_THRESHOLD = 0.85                    # Good: domain-specific constant
x = 3                                          # Bad: magic number, no name

# BOOLEANS: should read like a yes/no question
is_duplicate = check_idempotency(message_id)   # Good: reads as "is it a duplicate?"
has_attachments = len(attachments) > 0         # Good: reads as "does it have attachments?"
vendor_found = vendor_match is not None        # Good: reads as "was the vendor found?"
flag = True                                    # Bad: "flag" tells you nothing
```

### Comment Rules (ALWAYS ENFORCED)

```python
# GOOD COMMENTS: Explain WHY, not WHAT

# Check for duplicates before processing to prevent
# the same email from creating multiple tickets
if await is_duplicate_email(message_id):
    logger.info("Skipping duplicate email", message_id=message_id)
    return None

# Salesforce sometimes returns inactive vendor records,
# so we filter them out before matching
active_vendors = [v for v in vendors if v.is_active]

# Using a 7-day TTL because Exchange Online can redeliver
# emails up to 5 days after the original send in recovery mode
IDEMPOTENCY_TTL_SECONDS = 604800  # 7 days

# BAD COMMENTS: Just repeat what the code says

# Set x to 5
x = 5

# Loop through the list
for item in items:

# Check if vendor is not None
if vendor is not None:

# Return the result
return result
```

### Class Structure (Development Mode)

Every module should follow this class-based pattern. Note that this is intentionally simpler than the production skeleton — we prioritize readability and quick understanding.

```python
"""Module: intake/email_intake.py

Email Ingestion Service for VQMS.

This module handles fetching emails from Exchange Online via
Microsoft Graph API, parsing email content, identifying the vendor,
performing thread correlation, and storing the parsed data in
PostgreSQL and S3.

Corresponds to Steps E1-E2 in the VQMS Solution Flow Document
and Steps 2-3 in the VQMS Architecture Document.
"""

from __future__ import annotations

import logging
from datetime import datetime

# Project imports grouped and commented
from models.email import EmailMessage, ParsedEmailPayload

# Set up structured logger for this module
logger = logging.getLogger(__name__)


# --- Domain Exception ---
# Each module defines its own exception so callers can
# handle failures from this specific service separately
class EmailIntakeError(Exception):
    """Raised when email ingestion fails.

    Examples: Graph API unreachable, MIME parsing failure,
    S3 upload timeout, PostgreSQL write failure.
    """


# --- Main Service Class ---

class EmailIntakeService:
    """Handles the full email ingestion pipeline.

    This is the main entry point for email ingestion. It handles
    the full pipeline: fetch from Graph API, check for duplicates,
    parse MIME content, and return a normalized payload.
    """

    def __init__(self, graph_api_connector, postgres_connector, s3_connector):
        """Initialize with required connectors.

        Args:
            graph_api_connector: Microsoft Graph API connector for email fetch/send.
            postgres_connector: PostgreSQL connector for metadata and idempotency.
            s3_connector: S3 connector for raw email storage.
        """
        self.graph_api = graph_api_connector
        self.postgres = postgres_connector
        self.s3 = s3_connector

    async def fetch_and_parse_email(
        self,
        message_id: str,
        *,
        correlation_id: str | None = None,
    ) -> ParsedEmailPayload | None:
        """Fetch a single email from Exchange Online and parse it.

        Args:
            message_id: The Exchange Online message ID to fetch.
            correlation_id: Tracing ID that follows this email through
                the entire VQMS pipeline. If not provided, one will
                be generated.

        Returns:
            ParsedEmailPayload with all extracted fields, or None
            if the email was a duplicate (already processed).

        Raises:
            EmailIntakeError: If the email cannot be fetched or parsed.
                Includes the correlation_id for log tracing.
        """
        # TODO: Implement in Phase 2
        # Steps:
        # 1. Check idempotency key in PostgreSQL (INSERT ON CONFLICT, 7-day TTL cleanup)
        # 2. Fetch from Graph API
        # 3. Parse MIME headers and body
        # 4. Store raw email in S3
        # 5. Identify vendor from sender via Salesforce
        # 6. Thread correlation (In-Reply-To, References, conversationId)
        # 7. Generate IDs (query_id, execution_id, correlation_id)
        # 8. Write metadata to PostgreSQL
        # 9. Publish EmailParsed event to EventBridge
        # 10. Enqueue payload to SQS for AI pipeline
        raise NotImplementedError("Phase 2 implementation pending")
```

---

## Project Folder Structure — 5-Layer Architecture

The VQMS codebase is organized into **5 distinct layers**, each with a clear responsibility. Large modules have been split into **folder modules** (a folder with `__init__.py` + focused sub-files) for maintainability, while preserving all existing imports via re-exports in `__init__.py`. This structure follows the architecture document and coding standards.

```
vqms/
│
├── README.md                        # "Start here" — what this project does, how to run it
├── CLAUDE.md                        # This file — AI assistant instructions
├── Flow.md                          # Runtime walkthrough — follow the data through the system
├── .env                             # Secrets (NEVER committed)
├── .env.copy                        # Template — copy this to .env and fill in values
├── .gitignore                       # Git ignore rules
├── .ruff.toml                       # Linting config (ruff)
├── pyproject.toml                   # Dependencies (uv project config)
├── uv.lock                          # uv lockfile (auto-generated)
├── .python-version                  # 3.12
│
│
│ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
│   src/ — ALL backend Python code lives here.
│   Imports use package names directly (e.g. from models.email import ...).
│   pyproject.toml sets pythonpath = ["src"] for pytest.
│   .ruff.toml sets src = ["src"] for import sorting.
│ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
│
├── main.py                          # Thin entry point — uvicorn main:app
│
├── app/                             # Application bootstrap (extracted from old main.py)
│   ├── __init__.py                  #   Exports: create_app()
│   ├── factory.py                   #   create_app() — FastAPI app creation
│   ├── middleware.py                #   CORS, auth middleware, security headers
│   ├── routes.py                    #   Router registration (include_router calls)
│   └── lifespan.py                  #   Startup/shutdown events (DB pool, SSH tunnel)
│
├── config/                          # Configuration
│   ├── __init__.py
│   ├── settings.py                  #   Load .env, define all config constants
│   └── s3_paths.py                  #   S3 key builder utility
│
├── src/
│   │
│   │ ─ ─ LAYER 1: DATA SHAPES ─ ─ ─
│   ├── models/                      # Pydantic models — the shape of every data object
│   │   ├── __init__.py
│   │   ├── email.py                 #   ParsedEmailPayload, EmailAttachment
│   │   ├── email_dashboard.py       #   EmailDashboardResponse, EmailStats
│   │   ├── query.py                 #   QuerySubmission (portal), UnifiedQueryPayload
│   │   ├── auth.py                  #   UserRecord, LoginRequest, LoginResponse, TokenPayload
│   │   ├── vendor.py                #   VendorProfile, VendorMatch, VendorTier, VendorUpdateRequest
│   │   ├── communication.py         #   CommunicationModels
│   │   ├── ticket.py                #   TicketCreateRequest, TicketInfo
│   │   ├── triage.py                #   TriagePackage, ReviewerDecision (Path C)
│   │   ├── memory.py                #   EpisodicMemoryEntry, VendorContext
│   │   └── workflow.py              #   PipelineState, WorkflowModels
│   │
│   │ ─ ─ LAYER 1B: SERVICES ─ ─ ─
│   ├── services/                    # Business logic services
│   │   ├── __init__.py
│   │   ├── auth.py                  #   authenticate_user, create/validate/blacklist JWT tokens
│   │   ├── polling.py               #   Email polling service
│   │   ├── attachment_manifest.py   #   Attachment manifest generation
│   │   ├── portal_submission.py     #   Portal query submission service
│   │   │
│   │   ├── email_intake/            #   [FOLDER MODULE — split from email_intake.py]
│   │   │   ├── __init__.py          #     Exports: EmailIntakeService
│   │   │   ├── service.py           #     EmailIntakeService class — main orchestrator
│   │   │   ├── parser.py            #     MIME parsing, header extraction, body cleanup
│   │   │   ├── attachment_processor.py  #  Attachment validation, text extraction
│   │   │   ├── vendor_identifier.py #     Vendor identification from sender
│   │   │   ├── thread_correlator.py #     Thread correlation: In-Reply-To, References
│   │   │   └── storage.py           #     S3 raw email storage + PostgreSQL metadata write
│   │   │
│   │   └── email_dashboard/         #   [FOLDER MODULE — split from email_dashboard.py]
│   │       ├── __init__.py          #     Exports: EmailDashboardService
│   │       ├── service.py           #     EmailDashboardService class — main facade
│   │       ├── mappings.py          #     Status/category mapping constants
│   │       ├── queries.py           #     Database query builders
│   │       └── formatters.py        #     Response formatting and serialization
│   │
│   ├── api/                         # API layer (middleware + routes)
│   │   ├── __init__.py
│   │   ├── middleware/
│   │   │   ├── __init__.py
│   │   │   └── auth_middleware.py    #   JWT auth middleware (validates Bearer token, populates request.state)
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── auth.py              #   POST /auth/login, POST /auth/logout
│   │       ├── dashboard.py         #   GET /dashboard/kpis, email dashboard endpoints
│   │       ├── portal_dashboard.py  #   Portal-specific dashboard endpoints
│   │       ├── queries.py           #   POST /queries, GET /queries/{id}
│   │       ├── vendors.py           #   GET /vendors, PUT /vendors/{vendor_id}
│   │       └── webhooks.py          #   POST /webhooks/ms-graph, /webhooks/servicenow
│   │
│   ├── cache/                       # Cache helpers
│   │   ├── __init__.py
│   │   └── cache_client.py          #   CacheClient — PostgreSQL kv_store operations
│   │
│   │ ─ ─ LAYER 3: AI PIPELINE (ORCHESTRATION) ─ ─ ─
│   ├── orchestration/               # LangGraph state machine + all nodes
│   │   ├── __init__.py
│   │   ├── graph.py                 #   The main StateGraph — wires all nodes + edges
│   │   ├── sqs_consumer.py          #   SQS consumer — pulls messages and feeds the graph
│   │   ├── dependencies.py          #   Dependency injection for pipeline nodes
│   │   ├── studio.py                #   LangGraph Studio integration
│   │   ├── nodes/                   #   One file per pipeline step (each is a graph node)
│   │   │   ├── __init__.py
│   │   │   ├── context_loading.py   #     Step 7:  Load vendor profile + history from Salesforce/memory
│   │   │   ├── query_analysis.py    #     Step 8:  LLM Call #1 — intent, entities, confidence
│   │   │   ├── confidence_check.py  #     Decision Point 1: >= 0.85 → continue, < 0.85 → Path C
│   │   │   ├── routing.py           #     Step 9A: Deterministic rules — team, SLA, category
│   │   │   ├── kb_search.py         #     Step 9B: Embed + cosine similarity on pgvector
│   │   │   ├── path_decision.py     #     Decision Point 2: Path A vs Path B
│   │   │   ├── resolution.py        #     Step 10A: LLM Call #2 — full answer from KB (Path A)
│   │   │   ├── acknowledgment.py    #     Step 10B: LLM Call #2 — acknowledgment only (Path B)
│   │   │   ├── quality_gate.py      #     Step 11: 7 quality checks on drafted email
│   │   │   └── delivery.py          #     Step 12: Create ticket + send email via Graph API
│   │   └── prompts/                 #   Versioned prompt templates
│   │       └── prompt_manager.py    #     Prompt loading and versioning
│   │
│   │ ─ ─ LAYER 4: ADAPTERS (External System Connectors) ─ ─ ─
│   ├── adapters/                    # Every external system gets a module
│   │   ├── __init__.py
│   │   ├── bedrock.py               #   Amazon Bedrock — Claude LLM + Titan embeddings
│   │   ├── llm_gateway.py           #   LLM Gateway — unified LLM interface
│   │   ├── openai_llm.py            #   OpenAI LLM adapter
│   │   │
│   │   ├── graph_api/               #   [FOLDER MODULE — split from graph_api.py]
│   │   │   ├── __init__.py          #     Exports: GraphAPIConnector (combines mixins)
│   │   │   ├── client.py            #     GraphAPIClient — MSAL auth, token management
│   │   │   ├── email_fetch.py       #     EmailFetchMixin — fetch_email, list_unread_messages
│   │   │   ├── email_send.py        #     EmailSendMixin — send_email
│   │   │   └── webhook.py           #     WebhookMixin — subscribe_webhook, download_large_attachment
│   │   │
│   │   ├── salesforce/              #   [FOLDER MODULE — split from salesforce.py]
│   │   │   ├── __init__.py          #     Exports: SalesforceAdapter (combines mixins)
│   │   │   ├── client.py            #     SalesforceClient — auth, session, helpers
│   │   │   ├── vendor_lookup.py     #     VendorLookupMixin — vendor search by ID/email/name
│   │   │   └── account_operations.py #    AccountOperationsMixin — account CRUD
│   │   │
│   │   └── servicenow/              #   [FOLDER MODULE — split from servicenow.py]
│   │       ├── __init__.py          #     Exports: ServiceNowConnector (combines mixins)
│   │       ├── client.py            #     ServiceNowClient — lazy httpx client, shared helpers
│   │       ├── ticket_create.py     #     TicketCreateMixin — create_ticket()
│   │       └── ticket_query.py      #     TicketQueryMixin — get_ticket, get_work_notes, update_status
│   │
│   │ ─ ─ LAYER 5: SUPPORTING ─ ─ ─
│   ├── storage/                     # Storage connectors
│   │   ├── __init__.py
│   │   └── s3_client.py             #   AWS S3 — raw email + KB storage
│   │
│   ├── queues/                      # Message queue connectors
│   │   ├── __init__.py
│   │   └── sqs.py                   #   AWS SQS — message queues + DLQ
│   │
│   ├── events/                      # Event publishing
│   │   ├── __init__.py
│   │   └── eventbridge.py           #   AWS EventBridge — publishes all event types
│   │
│   ├── utils/                       # Utility modules
│   │   ├── __init__.py
│   │   ├── helpers.py               #   ist_now(), generate_query_id(), generate_correlation_id()
│   │   ├── logger.py                #   Structured logging (structlog + JSON + LogContext)
│   │   ├── exceptions.py            #   Domain exceptions: DuplicateQueryError, etc.
│   │   └── decorators/              #   [FOLDER MODULE — split from decorators.py]
│   │       ├── __init__.py          #     Exports: log_api_call, log_service_call, log_llm_call, log_policy_decision
│   │       ├── helpers.py           #     Shared helpers: is_known_provider_error, extract_correlation_id
│   │       ├── api.py               #     @log_api_call — FastAPI route handlers
│   │       ├── service.py           #     @log_service_call — service/adapter methods
│   │       ├── llm.py               #     @log_llm_call — LLM factory functions
│   │       └── policy.py            #     @log_policy_decision — confidence/routing decisions
│   │
│   └── db/                          # Database
│       ├── __init__.py
│       ├── connection/              #   [FOLDER MODULE — split from connection.py]
│       │   ├── __init__.py          #     Exports: PostgresConnector (combines mixins)
│       │   ├── client.py            #     PostgresClient — SSH tunnel, asyncpg pool, connect/disconnect
│       │   ├── queries.py           #     QueryMixin — execute, fetch, fetchrow, idempotency, cache_read
│       │   └── health.py            #     HealthMixin — health_check, run_migrations_sync
│       └── migrations/              #   SQL migration files (000–010)
│           ├── 000_reset_schemas.sql
│           ├── 001_create_schemas.sql
│           ├── 002_enable_pgvector.sql
│           ├── 003_create_intake_tables.sql
│           ├── 004_create_workflow_tables.sql
│           ├── 005_create_audit_tables.sql
│           ├── 006_create_memory_tables.sql
│           ├── 007_create_reporting_tables.sql
│           ├── 008_create_cache_tables.sql
│           ├── 009_auth_tables_documentation.sql
│           └── 010_create_portal_queries_table.sql
│
├── tests/                           # Testing (pythonpath includes src/)
│   ├── __init__.py
│   ├── conftest.py                  #   Shared fixtures (mock Bedrock, sample emails, etc.)
│   ├── test_models.py               #   Pydantic model tests (44 tests)
│   ├── test_email_intake.py         #   Email ingestion tests
│   ├── test_portal_intake.py        #   Portal intake tests
│   ├── test_pipeline.py             #   LangGraph pipeline tests
│   ├── test_connectors.py           #   Connector tests (moto for AWS)
│   ├── unit/                        #   Unit tests for auth + vendor
│   │   ├── __init__.py
│   │   ├── test_auth_models.py      #     Auth model validation tests
│   │   ├── test_auth_service.py     #     Auth service tests (login, JWT, blacklist)
│   │   ├── test_auth_middleware.py   #     Middleware behavior tests (skip paths, auth required, token refresh)
│   │   └── test_vendor_routes.py    #     Vendor route tests (list, update, auth required)
│   └── evals/                       #   LLM evaluation tests
│       └── golden_sets/             #     Curated test input/expected output pairs
│
├── tasks/                           # Task tracking
│   ├── todo.md                      #   Active task tracking
│   └── lessons.md                   #   Learnings from corrections
│
├── docs/                            # Documentation
│   ├── api.md                       #   API endpoint documentation
│   ├── architecture.md              #   System architecture overview
│   └── references/                  #   Read-only reference docs
│
├── data/                            # Local data
│   ├── knowledge_base/              #   KB articles for vector search
│   └── storage/                     #   Test artifacts, temp files
│
└── notebooks/                       # Experiments and demos
    └── email_ingestion_agent.ipynb  #   Agent demo notebook
```

### Quick Reference — "Where Do I Put This?"

| I want to...                              | Put it in...                                          |
|-------------------------------------------|-------------------------------------------------------|
| Add a new Pydantic data model             | `src/models/` (one model class per domain concept)     |
| Add email ingestion logic                 | `src/services/email_intake/` (folder module)           |
| Add portal submission logic               | `src/services/portal_submission.py`                    |
| Add a FastAPI route                       | `src/api/routes/` (one file per resource)              |
| Add a new LangGraph pipeline node         | `src/orchestration/nodes/` (one file per step)         |
| Wire up the LangGraph state machine       | `src/orchestration/graph.py`                           |
| Add a new prompt template                 | `src/orchestration/prompts/`                           |
| Add an external system adapter            | `src/adapters/` (folder module for large adapters)     |
| Add a domain exception class              | `src/utils/exceptions.py`                              |
| Add a utility/helper function             | `src/utils/helpers.py`                                 |
| Add a logging decorator                   | `src/utils/decorators/` (folder module)                |
| Add a database migration                  | `src/db/migrations/` (new SQL file)                    |
| Add a config constant                     | `config/settings.py`                                   |
| Add/update environment variable           | `.env` AND `.env.copy`                             |
| Write a unit test                         | `tests/test_<module_name>.py`                      |
| Write an LLM eval test                    | `tests/evals/`                                     |
| Add a golden test set                     | `tests/evals/golden_sets/`                         |
| Add a KB article for vector search        | `data/knowledge_base/`                             |
| Experiment in a notebook                  | `notebooks/`                                       |
| Track a new task                          | `tasks/todo.md`                                    |
| Log a lesson learned                      | `tasks/lessons.md`                                 |
| Update runtime walkthrough                | `Flow.md` (project root)                           |
| Update project overview/setup             | `README.md` (project root)                         |

---

## VQMS System Components Reference

### Entry Points (Two Paths Into the System)
1. **Email Path** — Vendor sends email to vendor-support@company.com. Email Ingestion Service (`src/services/email_intake/`) fetches via Graph API webhook + reconciliation polling (every 5 minutes). Includes: dual detection (webhook + polling), PostgreSQL idempotency check (INSERT ON CONFLICT, 7-day TTL), MIME parsing, attachment extraction (PDF/Excel/Word/CSV/images via pdfplumber/openpyxl/python-docx/Textract), vendor identification from sender email via Salesforce (3-step fallback: exact email → body extraction → fuzzy name match), thread correlation (In-Reply-To/References/conversationId), raw email storage in S3, PostgreSQL metadata write, EventBridge event publish, SQS enqueue. Output: ParsedEmailPayload on vqms-email-intake-queue.
2. **Portal Path** — Vendor logs into VQMS portal (Cognito + optional SSO), fills wizard form (type, details, review), submits via POST /queries with JWT auth. Portal Submission Service (`src/services/portal_submission.py`) validates via Pydantic, generates query_id (VQ-2026-XXXX format), returns query_id instantly (~400ms). Output: query payload on vqms-query-intake-queue. No thread correlation (portal queries are always NEW). No raw email storage. Vendor ID from JWT, not sender email matching.

### AI Pipeline Nodes (LangGraph State Machine — `src/orchestration/`)
1. **Context Loading Node** (`src/orchestration/nodes/context_loading.py`) — Step 7: Loads vendor profile from Salesforce (cached in PostgreSQL, 1-hour TTL), loads episodic memory (last 5 vendor interactions), caches workflow state in PostgreSQL (24-hour TTL), updates status to ANALYZING.
2. **Query Analysis Node** (`src/orchestration/nodes/query_analysis.py`) — Step 8: LLM Call #1 via Bedrock Claude Sonnet 3.5 (temperature 0.1, ~1500 tokens in, ~500 tokens out). Extracts: intent classification, entities (invoice numbers, dates, amounts, PO numbers), urgency level, sentiment, confidence score (0.0–1.0), multi-issue detection, suggested_category. Output: AnalysisResult. Uses 8-layer defense strategy (input validation → prompt engineering → LLM call with retry → output parsing → Pydantic validation → self-correction → safe fallback → audit logging).
3. **Confidence Check Node** (`src/orchestration/nodes/confidence_check.py`) — Decision Point 1: Confidence >= 0.85 → continue to Step 9 (Routing + KB Search). Confidence < 0.85 → Path C (workflow PAUSES for human review).
4. **Routing Node** (`src/orchestration/nodes/routing.py`) — Step 9A: Deterministic rules engine. Evaluates: confidence >= 0.85, urgency == CRITICAL, existing ticket, BLOCK_AUTOMATION flag. Determines team assignment and SLA target based on vendor tier + urgency. Output: RoutingDecision.
5. **KB Search Node** (`src/orchestration/nodes/kb_search.py`) — Step 9B: Embeds query text using Bedrock Titan Embed v2 → vector(1536), cosine similarity search against KB article embeddings in PostgreSQL (`memory.embedding_index` table via pgvector), filtered by category. Returns ranked article matches with similarity scores.
6. **Path Decision Node** (`src/orchestration/nodes/path_decision.py`) — Decision Point 2: KB match >= 80% AND answer has specific facts AND Resolution Agent confidence >= 0.85 → Path A. Otherwise → Path B.
7. **Resolution Node** (`src/orchestration/nodes/resolution.py`) — Step 10A (Path A only): LLM Call #2 via Bedrock Claude Sonnet 3.5 (temperature 0.3, ~3000 tokens in). Generates full resolution email using KB articles as source. Output: DraftResponse with concrete facts, confidence score, and source citations.
8. **Acknowledgment Node** (`src/orchestration/nodes/acknowledgment.py`) — Step 10B (Path B only): LLM Call #2 via Bedrock Claude Sonnet 3.5. Generates ACKNOWLEDGMENT-ONLY email with ticket number, SLA statement, next steps — NO answer content.
9. **Triage Node** (`src/orchestration/nodes/triage.py`) — Path C: Creates TriagePackage (original query + AI analysis + confidence breakdown + suggested routing + suggested draft), pushes to human-review queue, pauses workflow via callback token.
10. **Quality Gate Node** (`src/orchestration/nodes/quality_gate.py`) — Step 11: 7 deterministic checks on every outbound draft. Phase 1 (always): ticket # format (INC-XXXXXXX), SLA wording matches vendor tier policy, required sections present (greeting, body, next steps, closing), restricted terms scan (no internal jargon, no competitor names), response length (50–500 words), source citations (Path A only). Phase 2 (conditional, HIGH+ priority): PII scan via Amazon Comprehend. Max 2 re-drafts before routing to human review.
11. **Delivery Node** (`src/orchestration/nodes/delivery.py`) — Step 12: Creates ticket in ServiceNow, sends validated email to vendor via MS Graph /sendMail, updates case status, publishes completion events.

### Adapters (External System Interfaces — `src/adapters/`)
- **Bedrock** (`src/adapters/bedrock.py`) — ALL LLM inference (Claude Sonnet 3.5) and embedding (Titan Embed v2) calls. Nobody calls LLM providers directly — all calls go through this adapter. Key functions: `llm_complete(prompt, system_prompt, temperature, max_tokens, correlation_id)` returns dict with response_text, tokens_in, tokens_out, cost_usd, latency_ms; `llm_embed(text, correlation_id)` returns vector(1536). Retry with exponential backoff for ThrottlingException and ServiceUnavailableException.
- **LLM Gateway** (`src/adapters/llm_gateway.py`) — Unified LLM interface abstracting over Bedrock and OpenAI.
- **Microsoft Graph API** (`src/adapters/graph_api/`) — Folder module: `client.py` (MSAL auth), `email_fetch.py` (GET /messages), `email_send.py` (/sendMail), `webhook.py` (subscription + large attachments). Combined via `GraphAPIConnector` in `__init__.py`.
- **Salesforce** (`src/adapters/salesforce/`) — Folder module: `client.py` (auth, session), `vendor_lookup.py` (vendor search by ID/email/name), `account_operations.py` (account CRUD). Combined via `SalesforceAdapter` in `__init__.py`.
- **ServiceNow** (`src/adapters/servicenow/`) — Folder module: `client.py` (httpx client, helpers), `ticket_create.py` (POST /api/now/table/incident), `ticket_query.py` (lookup, work notes, status updates). Combined via `ServiceNowConnector` in `__init__.py`.
- **S3** (`src/storage/s3_client.py`) — Upload, download, existence check, list, delete for the single S3 bucket (`vqms-data-store`), prefix-organized by VQ-ID.
- **SQS** (`src/queues/sqs.py`) — Producer/consumer for all SQS queues + DLQ.
- **EventBridge** (`src/events/eventbridge.py`) — Publishes all 20 EventBridge event types.
- **PostgreSQL** (`src/db/connection/`) — Folder module: `client.py` (SSH tunnel, asyncpg pool), `queries.py` (execute, fetch, idempotency, cache), `health.py` (health check, migrations). Combined via `PostgresConnector` in `__init__.py`.

### Data Infrastructure
- **1 S3 Bucket (prefix-organized):** `vqms-data-store` with prefixes: `inbound-emails/`, `attachments/`, `processed/`, `templates/`, `archive/`. All files organized by VQ-ID under their prefix (e.g., `inbound-emails/VQ-2026-0001/raw_email.json`). S3 keys are built via `config/s3_paths.py` → `build_s3_key()`. Vector embeddings are stored in PostgreSQL via pgvector.
- **PostgreSQL Schemas:** intake (email_messages, email_attachments), workflow (case_execution, ticket_link, routing_decision), memory (episodic_memory, vendor_profile_cache, embedding_index), audit (action_log, validation_results), reporting (sla_metrics), cache (idempotency_keys, vendor_cache, workflow_state_cache)
- **SQS Queues + DLQ:** email-intake, query-intake (portal), analysis, vendor-resolution, ticket-ops, routing, communication, escalation, human-review, audit, dlq
- **20 EventBridge Events:** EmailReceived, EmailParsed, QueryReceived, AnalysisCompleted, VendorResolved, TicketCreated, TicketUpdated, DraftPrepared, ValidationPassed, ValidationFailed, EmailSent, SLAWarning70, SLAEscalation85, SLAEscalation95, VendorReplyReceived, ResolutionPrepared, TicketClosed, TicketReopened, HumanReviewRequired, HumanReviewCompleted

### Three Processing Paths (Critical Decision Points)

**Decision Point 1 — Confidence (at Step 8):**
- Confidence >= 0.85 → continue to Step 9 (Routing + KB Search)
- Confidence < 0.85 → Path C (Low-Confidence Human Review — workflow PAUSES until reviewer acts)

**Decision Point 2 — KB Match Quality (at Step 9, only reached if confidence >= 0.85):**
- KB match >= 80% AND answer has specific facts AND Resolution Agent confidence >= 0.85 → **Path A** (AI drafts resolution email with full answer)
- Otherwise → **Path B** (AI drafts acknowledgment only, human team investigates, AI drafts resolution from team's notes later)

---

## Email Ingestion Pipeline — Defense-in-Depth (7 Layers)

The email ingestion system (`src/services/email_intake/`) implements 7 layers of resilience to ensure no email is ever lost or silently dropped.

### Layer 1 — Dual Detection
Two independent mechanisms catch incoming emails simultaneously:
- **Webhook (real-time):** Microsoft sends a push notification when a new email arrives (<5 seconds latency).
- **Reconciliation Polling (every 5 minutes):** Scheduled poll fetches unread messages via `GET /messages?$filter=isRead eq false&$top=50`.
Both paths feed into the same idempotency check — if both detect the same email, it's only processed once.

### Layer 2 — Idempotency
PostgreSQL `INSERT ON CONFLICT DO NOTHING` with a 7-day TTL (background cleanup job) ensures the same email is never processed twice, even if both webhook and polling pick it up. The check uses a unique constraint on message_id, preventing race conditions between concurrent workers.

### Layer 3 — Retry with Exponential Backoff
Each external call has a retry decorator: Graph API fetch (3 attempts), S3 upload (2 attempts), Salesforce vendor lookup (3 attempts).

### Layer 4 — Graceful Degradation (Critical vs Non-Critical Steps)
The pipeline classifies every step as either **critical** or **non-critical**:
- **Critical steps** (E1, E2.2, E2.6, E2.7, E2.9): If these fail, the error propagates and SQS retries. Without these, the email can't be read, tracked, or queued.
- **Non-critical steps** (E2.1, E2.3, E2.4, E2.5, E2.8): If these fail, the system logs a warning and continues with sensible defaults (no vendor match, no thread context, no raw archive, no event broadcast).

### Layer 5 — Dead Letter Queue
If all retries on a critical step fail, the SQS message moves to a DLQ. CloudWatch alarm fires when DLQ depth > 0, paging the on-call engineer.

### Layer 6 — Checkpoint and Resume
The system can pick up processing from where it left off after a failure, avoiding reprocessing completed steps.

### Layer 7 — Alerting and Monitoring
CloudWatch dashboard tracks: `emails_processed_total`, `emails_duplicate_skipped`, `emails_failed_to_dlq`, `vendor_not_found_count`, `avg_processing_time_ms`, `p99_processing_time_ms`. Alert thresholds: DLQ depth > 0 pages on-call; processing time > 30s sends Slack warning; Salesforce down > 5 minutes triggers team alert.

---

## Attachment Processing Pipeline

Vendor emails frequently contain invoices (PDF), purchase orders (Excel), contracts (Word), and screenshots (PNG). Without processing these, many queries lack enough information for the AI to resolve them.

### Extraction Flow
1. **Receive:** Graph API returns small attachments (< 3 MB) inline as Base64. Large attachments (> 3 MB) require a separate API call.
2. **Validate:** Check against safety and size limits.
3. **Store Binary to S3:** Files go to `s3://vqms-data-store/attachments/{query_id}/{att_id}_{filename}`.
4. **Extract Text:** File-type-specific extraction using `pdfplumber` (PDF), `openpyxl` (Excel), `python-docx` (Word), direct read (CSV/TXT), or Amazon Textract for OCR on images/scanned documents. Truncated to 5,000 characters per attachment.
5. **Save Metadata to PostgreSQL:** `attachment_id`, `query_id`, `filename`, `content_type`, `size_bytes`, `s3_key`, `extracted_text`, `extraction_status` → `intake.email_attachments` table.
6. **Include in Payload:** Extracted text is sent alongside the email body to the Query Analysis Agent.

### Safety and Size Guardrails

| Rule | Limit | Reason |
|------|-------|--------|
| Max file size | 10 MB per attachment | Processing time protection |
| Max total size | 50 MB per email | Memory protection |
| Max extracted text | 5,000 characters per attachment | Token limit for Claude (~1,250 tokens) |
| Blocked file types | `.exe`, `.bat`, `.cmd`, `.ps1`, `.sh`, `.js` | Security — executables never processed |
| Max attachment count | 10 per email | Abuse prevention |
| Malware scan | Before storing to S3 | Never store or process infected files |

---

## Processing Paths — Runtime Summary

### Path A: AI-Resolved (Happy Path)
1. Query arrives (email or portal) → ingestion → SQS queue
2. LangGraph Orchestrator loads context (vendor profile from Salesforce, episodic memory, workflow state)
3. Query Analysis Agent (LLM Call #1): intent, entities, urgency, sentiment, confidence
4. Confidence >= 0.85 → continue
5. Parallel: Routing (deterministic rules) + KB Search (Titan Embed v2 → pgvector cosine similarity)
6. KB match >= 80% with specific facts → **Path A**
7. Resolution Agent (LLM Call #2): generates full answer email using KB articles as source
8. Quality & Governance Gate: 7 checks (ticket #, SLA wording, sections, restricted terms, length, citations, PII)
9. Ticket created in ServiceNow (team MONITORS, not investigates)
10. Resolution email sent to vendor via Graph API
11. Closure: vendor confirms or auto-close after 5 business days

**Metrics (reference example):** ~11 seconds total, ~$0.033 cost, 2 LLM calls, zero human involvement.

### Path B: Human-Team-Resolved
1–5. Same as Path A through KB Search
6. KB does NOT have specific facts → **Path B**
7. Communication Drafting Agent: generates ACKNOWLEDGMENT email only (no answer, just "we received it, ticket is INC..., team is reviewing")
8. Quality & Governance Gate: same 7 checks
9. Ticket created in ServiceNow (team MUST investigate)
10. Acknowledgment email sent to vendor
11. SLA monitor starts — critical because human team has real investigation time
12. Human team investigates (opens ServiceNow ticket, uses internal systems to find answer)
13. Team marks ticket RESOLVED with resolution notes
14. ResolutionPrepared event triggers Communication Drafting Agent → generates resolution email from team's notes (LLM Call #3)
15. Quality gate validates again → resolution email sent to vendor
16. Closure: same as Path A

**Metrics:** ~10 seconds for acknowledgment, minutes to hours for resolution, ~$0.05 total cost.

### Path C: Low-Confidence Human Review
1–3. Same as Path A through Query Analysis Agent
4. Confidence < 0.85 → **Path C** (workflow PAUSES entirely)
5. TriagePackage created: original query + AI's analysis + confidence breakdown + suggested routing + suggested draft
6. Package pushed to vqms-human-review-queue
7. Workflow pauses via callback token — NOTHING happens until human acts
8. Human reviewer logs in (Cognito auth), reviews TriagePackage, corrects classification/vendor/routing
9. Reviewer submits → workflow RESUMES with corrected data
10. Corrected data now has HIGH confidence (human-validated) → continues to Step 9 (Routing + KB Search)
11. From here, follows Path A or Path B depending on KB match quality
12. **SLA clock starts AFTER human review completes** — review time does NOT count against SLA

**Metrics:** Review adds minutes to hours (reviewer availability), then ~$0.03–$0.05 depending on Path A or B.

### Key Path Differences for Implementation

| Aspect | Path A | Path B | Path C |
|--------|--------|--------|--------|
| LLM calls | 2 (analysis + resolution) | 2–3 (analysis + ack + resolution from notes) | Same as A or B after review |
| Ticket purpose | Team monitors | Team investigates | Depends on resumed path |
| Email type | Resolution (full answer) | Acknowledgment, then resolution later | Depends on resumed path |
| SLA starts | At ticket creation | At ticket creation | AFTER human review completes |
| Human involvement | None | Investigation team | Reviewer first, then possibly team |
| KB used | Yes (source of facts) | No (lacks specifics) | Depends on resumed path |

---

## Query Analysis Agent — Defense Strategy (8 Layers)

The Query Analysis Agent is the most critical component because every vendor query passes through it. It implements an 8-layer defense strategy against the 15 identified failure points:

| Layer | Name | Purpose |
|-------|------|---------|
| 1 | Input Validation | Catch bad/empty/malicious data before calling the LLM |
| 2 | Prompt Engineering | Structured prompts with explicit JSON schema to make output predictable |
| 3 | LLM Call with Retry | Retry transient Bedrock API failures (timeouts, throttling) |
| 4 | Output Parsing | Extract JSON from the LLM response, handling markdown fences and preamble |
| 5 | Pydantic Validation | Enforce schema, field types, and value ranges on parsed output |
| 6 | Self-Correction | If parsing or validation fails, send the error back to Claude and ask it to fix its own response |
| 7 | Safe Fallback | If all else fails, produce a low-confidence AnalysisResult that routes to Path C — the system never crashes |
| 8 | Audit and Monitoring | Log every input, prompt, raw LLM response, parsed output, and validation result |

---

## API Endpoints

All endpoints are served by FastAPI (via `src/api/routes/`) behind API Gateway with Cognito JWT authorization.

| Endpoint | Method | Purpose | Auth |
|----------|--------|---------|------|
| `/queries` | POST | Portal query submission (Step P6) | Vendor JWT |
| `/queries/{id}` | GET | Query status + detail for vendor dashboard | Vendor JWT |
| `/dashboard/kpis` | GET | Portal dashboard KPIs (Step P2) | Vendor JWT |
| `/triage/{id}/review` | POST | Human reviewer submits corrections (Step 8C.2) | Reviewer JWT |
| `/triage/queue` | GET | List pending triage packages for review portal | Reviewer JWT |
| `/webhooks/ms-graph` | POST | MS Graph email notification webhook (Step E2.1) | HMAC/Token |
| `/webhooks/servicenow` | POST | ServiceNow resolution-prepared callback (Step 15) | HMAC/Token |
| `/admin/metrics` | GET | SLA, path, cost reporting metrics | Admin JWT |
| `/auth/login` | POST | User authentication — returns JWT | None (public) |
| `/auth/logout` | POST | Blacklist JWT token (invalidate session) | Bearer JWT |
| `/vendors` | GET | List all active vendors from Salesforce standard Account | Bearer JWT |
| `/vendors/{vendor_id}` | PUT | Update vendor fields in Salesforce standard Account | Bearer JWT |

**Security rule:** `vendor_id` is always extracted from JWT claims, NEVER from request payload.

---

## Architecture-to-Code Mapping

| Document Component | Code Module | Phase |
|---|---|---|
| Email Ingestion (Steps E1-E2) | `src/services/email_intake/` | Phase 2 |
| Portal Submission (Steps P1-P6) | `src/api/routes/` + `src/services/portal_submission.py` | Phase 2 |
| LangGraph Orchestrator (Step 7) | `src/orchestration/graph.py` | Phase 3 |
| Query Analysis Agent (Step 8) | `src/orchestration/nodes/query_analysis.py` | Phase 3 |
| Routing + KB Search (Step 9) | `src/orchestration/nodes/routing.py` + `src/orchestration/nodes/kb_search.py` | Phase 3 |
| Resolution Agent (Step 10A) | `src/orchestration/nodes/resolution.py` | Phase 4 |
| Communication Agent (Step 10B) | `src/orchestration/nodes/acknowledgment.py` | Phase 4 |
| Quality Gate (Step 11) | `src/orchestration/nodes/quality_gate.py` | Phase 4 |
| Ticket + Email Delivery (Step 12) | `src/orchestration/nodes/delivery.py` + `src/adapters/servicenow/` + `src/adapters/graph_api/` | Phase 4 |
| Path C Triage (Steps 8C.1-8C.3) | `src/orchestration/nodes/triage.py` + `src/api/routes/` (triage endpoints) | Phase 5 |
| SLA Monitor (Step 13) | Background monitoring module | Phase 6 |
| Closure/Reopen (Step 16) | Closure module | Phase 6 |
| Vendor Portal (Angular) | `frontend/src/` | Phase 7 |

---

## Module Breakdown with Dependencies

| Module | Responsibility | Key Dependencies |
|--------|---------------|------------------|
| `src/services/email_intake/` | MS Graph webhook/polling, MIME parsing, vendor identification, thread correlation, idempotency, SQS publishing | `src/adapters/graph_api/`, `src/adapters/salesforce/`, `src/db/connection/`, `src/queues/sqs.py`, `src/storage/s3_client.py` |
| `src/services/portal_submission.py` | JWT-based query submission, Pydantic validation, ID generation, idempotency, SQS publishing | `src/db/connection/`, `src/queues/sqs.py` |
| `src/orchestration/graph.py` | LangGraph workflow graph: context loading, agent routing, parallel KB+routing, confidence branching, Path A/B/C dispatch | All `src/orchestration/nodes/`, `src/adapters/` |
| `src/orchestration/nodes/query_analysis.py` | LLM Call #1: intent classification, entity extraction, confidence scoring, sentiment analysis | `src/adapters/bedrock.py`, `src/db/connection/` |
| `src/orchestration/nodes/routing.py` | Deterministic rules engine: confidence, urgency, team assignment, SLA calculation | `src/db/connection/` |
| `src/orchestration/nodes/kb_search.py` | Embedding + cosine similarity search over pgvector (memory.embedding_index), category-filtered | `src/adapters/bedrock.py`, `src/db/connection/` |
| `src/orchestration/nodes/resolution.py` | LLM Call #2: draft resolution email from KB facts + vendor context | `src/adapters/bedrock.py` |
| `src/orchestration/nodes/acknowledgment.py` | LLM Call: draft acknowledgment email (Path B) or resolution email from human notes (Step 15) | `src/adapters/bedrock.py` |
| `src/orchestration/nodes/quality_gate.py` | 7-check validation: ticket format (INC-XXXXXXX), SLA wording, required sections (greeting, body, next steps, closing), restricted terms, length (50–500 words), source citations, PII scan | Rule engine, Amazon Comprehend |
| `src/orchestration/nodes/delivery.py` | ServiceNow ticket creation + MS Graph email delivery | `src/adapters/servicenow/`, `src/adapters/graph_api/` |

---

## Database Design Strategy

### PostgreSQL Schema Namespaces
- **intake:** `email_messages`, `email_attachments` (email path metadata and S3 keys)
- **workflow:** `case_execution` (central state table: status, analysis_result, routing), `ticket_link`, `routing_decision`
- **audit:** `action_log` (every state transition with correlation_id, timestamp, actor, action), `validation_results`
- **memory:** `episodic_memory` (vendor query history indexed by vendor_id), `vendor_profile_cache`, `embedding_index`
- **reporting:** `sla_metrics`, path_metrics, cost_metrics

### PostgreSQL Cache Tables (Replaces Redis — No Redis in Stack)
- `cache.idempotency_keys` — UNIQUE constraint on `key` column (VARCHAR 512), `created_at` (IST timestamp), `source` (email/portal), `correlation_id` (UUID). Check-and-insert via single atomic `INSERT ... ON CONFLICT DO NOTHING`. Background job purges keys older than 7 days.
- `cache.vendor_cache` — 1h TTL, Salesforce vendor profile cache, `expires_at` column checked on reads
- `cache.workflow_state_cache` — 24h TTL, workflow state cache, `expires_at` column checked on reads
- **Scheduled cleanup task** runs every 15 minutes to delete expired rows from all cache tables

### S3 Bucket (Single Bucket, Prefix-Organized)

All files live in one bucket (`vqms-data-store`), organized by prefix + VQ-ID:

```
vqms-data-store/
├── inbound-emails/VQ-YYYY-NNNN/raw_email.json
├── attachments/VQ-YYYY-NNNN/{att_id}_{filename}
├── attachments/VQ-YYYY-NNNN/_manifest.json
├── processed/VQ-YYYY-NNNN/email_analysis.json
├── processed/VQ-YYYY-NNNN/response_draft.json
├── processed/VQ-YYYY-NNNN/ticket_payload.json
├── processed/VQ-YYYY-NNNN/resolution_summary.json
├── templates/response_templates/{category}.json
└── archive/VQ-YYYY-NNNN/_archive_bundle.json
```

S3 keys are built exclusively via `config/s3_paths.py` → `build_s3_key(prefix, query_id, filename)`. No hardcoded S3 paths anywhere else.

### Vector Search via pgvector
KB article embeddings are stored in the `memory.embedding_index` table using the pgvector extension. The KB Search node embeds the query text via Titan Embed v2 (1536 dimensions), then runs a cosine similarity query filtered by category. This keeps all vector operations inside PostgreSQL without requiring a separate vector database.

---

## Integration Strategy

All external integrations are built behind adapter interfaces in `src/adapters/` so they can be stubbed during testing:

**Integration Priority Order (connect in this sequence):**
1. PostgreSQL — foundation for everything; connect first via SSH tunnel to bastion
2. Amazon Bedrock — needed for Query Analysis Agent (LLM) and KB Search (embeddings)
3. Amazon S3 — needed for raw email storage, attachments, and KB articles
4. Amazon SQS — needed for async message passing between intake and pipeline
5. Microsoft Graph API — needed for email fetch and send
6. Salesforce CRM — needed for vendor identification
7. ServiceNow ITSM — needed for ticket creation
8. Amazon EventBridge — needed for event-driven audit trail
9. AWS Cognito — needed for portal authentication

**Connector Details:**

1. **Salesforce CRM Adapter** (`src/adapters/salesforce/`) — Folder module: `client.py` (auth, session), `vendor_lookup.py` (vendor search), `account_operations.py` (account CRUD). Combined via `SalesforceAdapter`. Used in Steps E2.5 and 7.3.
2. **ServiceNow ITSM Adapter** (`src/adapters/servicenow/`) — Folder module: `client.py` (httpx client), `ticket_create.py` (incident creation), `ticket_query.py` (lookup, work notes, status). Combined via `ServiceNowConnector`. Used in Steps 12A, 12B, 14, 15.
3. **Microsoft Graph API Adapter** (`src/adapters/graph_api/`) — Folder module: `client.py` (MSAL auth), `email_fetch.py` (GET /messages), `email_send.py` (/sendMail), `webhook.py` (subscription). Combined via `GraphAPIConnector`. Used in Steps E2.1, 12A, 12B, 15, and closure detection.
4. **Amazon Bedrock Adapter** (`src/adapters/bedrock.py`) — LLM inference (Claude Sonnet 3.5) and embedding (Titan Embed v2). Used in Steps 8, 9B, 10A, 10B, 15.
5. **PostgreSQL Connector** (`src/db/connection/`) — Folder module: `client.py` (SSH tunnel, asyncpg pool), `queries.py` (execute, fetch, idempotency, cache), `health.py` (health check, migrations). Combined via `PostgresConnector`. Used in Steps E2.1, P6.4, 7.2, 7.3, and throughout.

**Build stubs first.** Each connector should have a corresponding mock/stub that returns realistic test data, allowing the full pipeline to be exercised end-to-end locally before connecting real services.

---

## Error Handling Strategy

- Use domain-specific exception classes defined in `src/utils/exceptions.py` (not bare Exception or generic errors):

| Exception | When Raised | HTTP Status | Recovery |
|-----------|-------------|-------------|----------|
| `DuplicateQueryError` | Idempotency check finds existing entry | 409 Conflict | Skip processing, return existing query_id |
| `VendorNotFoundError` | Vendor resolution fails | 404 / 422 | Continue with vendor_id=None in email path |
| `KBSearchTimeoutError` | KB vector search exceeds timeout | 500 | Route to Path B (no KB match) |
| `QualityGateFailedError` | Draft fails validation after max re-drafts | N/A (internal) | Route to human review |
| `SLABreachedError` | SLA timer exceeds threshold | N/A (event) | Escalation event published |
| `BedrockTimeoutError` | LLM call exceeds timeout | 500 | Retry with backoff, then Path C fallback |
| `GraphAPIError` | MS Graph API call fails | 502 | Retry with backoff |

- **Critical vs Non-Critical Step Pattern:**
  - Critical steps (fetch, parse, generate IDs, DB write, SQS enqueue): Exceptions propagate upward. SQS retries the message. After max retries, message moves to DLQ.
  - Non-critical steps (idempotency check, S3 storage, vendor lookup, thread correlation, EventBridge publish): Exceptions caught with try/except, warning logged, pipeline continues with safe defaults.
- All SQS consumers must implement DLQ handling with 3 retries (vqms-dlq)
- Idempotency guards on both entry points (PostgreSQL INSERT ON CONFLICT with 7-day TTL cleanup) prevent duplicate processing
- Quality Gate failures trigger DRAFT_REJECTED status and route to human review — never silently fail
- LLM parsing failures (Pydantic validation of AnalysisResult or DraftResponse) retry once, then route to Path C (low confidence)
- External API failures (Salesforce, ServiceNow, MS Graph) use exponential backoff with circuit breaker pattern (simple retry in dev mode)

---

## Validation Strategy

Pydantic models enforce validation at every boundary:
- **QuerySubmission:** validates portal intake payload (type, subject, description, priority, reference)
- **ParsedEmailPayload:** validates parsed MIME data (message-id, sender, recipients, subject, body)
- **AnalysisResult:** validates LLM output (intent_classification, extracted_entities, urgency_level, sentiment, confidence_score, multi_issue_detected, suggested_category)
- **DraftResponse:** validates generated email drafts (subject, body, confidence, sources)
- **TriagePackage:** validates Path C triage data including AI analysis, vendor match, suggested routing, and confidence breakdown
- **ReviewerDecision:** validates human reviewer corrections (corrected intent, vendor, routing, confidence override)
- **Quality Gate** performs 7 deterministic checks on every outbound draft before delivery

---

## Security Considerations

- AWS Cognito (vqms-agent-portal-users) handles all authentication. JWTs include vendor_id, role (VENDOR/REVIEWER/ADMIN), and scopes (queries.own, kb.read, prefs.own)
- **Dev-mode JWT auth:** `src/services/auth.py` issues and validates JWTs using `python-jose` with HMAC-SHA256 (secret from `JWT_SECRET_KEY` env var). Password verification uses `werkzeug.security.check_password_hash`. Token blacklist stored in `cache.kv_store` with TTL. `src/api/middleware/auth_middleware.py` enforces Bearer token on all routes except `/health`, `/auth/login`, `/docs`, `/openapi.json`, `/redoc`, `/webhooks/`. Near-expiry tokens get auto-refreshed via `X-New-Token` response header.
- **vendor_id is extracted from JWT claims, NEVER from request payload** (Step P6 explicitly notes this)
- API Gateway with Cognito Authorizer validates every request before it reaches FastAPI
- PII detection via Amazon Comprehend in Quality Gate ensures personal data is stripped from outbound emails
- All raw emails and attachments stored in S3 for compliance. Prompt snapshots stored for LLM audit trail
- PostgreSQL cache entries use TTL-based background cleanup to prevent stale data accumulation
- Secrets: env vars or vault; rotate keys; least privilege; never commit secrets in code
- Encrypt at rest/in transit; redact PII before LLM; honor data residency
- Prompt injection defense: do not execute instructions from user documents; enforce policy for tools
- Content moderation: filter inputs/outputs; route risky content to human-in-the-loop

---

## Logging and Monitoring Strategy

- **Correlation ID** (UUID v4) must be generated at intake and propagated through every service call, database write, and external API request
- **Timezone:** All timestamps use IST (Indian Standard Time) via `src/utils/helpers.py` → `ist_now()`. PostgreSQL TIMESTAMP columns store naive datetimes in IST.
- JSON structured logging with fields: `correlation_id`, `step_name`, `duration_ms`, `status`, `error_details`, `tokens_in/out`, `cost`, `model`, `prompt_id`
- Never log PII or secrets
- **Four logging decorators** (defined in `src/utils/decorators/`) eliminate boilerplate:
  - `@log_api_call` — FastAPI route handlers (extracts correlation_id from headers)
  - `@log_service_call` — services, adapters, orchestration nodes (handles both sync and async)
  - `@log_llm_call` — LLM factory functions (enriches with token counts, cost, model info)
  - `@log_policy_decision` — confidence checks, routing decisions (logs the policy outcome)
- EventBridge events (20 event types) provide the event-driven audit trail
- `audit.action_log` table records every state transition with correlation_id, timestamp, actor, and action
- SLA metrics tracked in `reporting.sla_metrics` for dashboard and reporting
- LLM cost tracking: token counts and cost per call stored per execution (~$0.012 for analysis, ~$0.021 for resolution)

---

## Testing Strategy

- **Unit Tests:** Every Pydantic model, every pipeline node, every connector function. Mock all external dependencies.
- **Integration Tests:** Full pipeline execution with stubbed connectors: submit query, verify it flows through Path A, B, and C correctly.
- **Contract Tests:** Verify Salesforce, ServiceNow, and MS Graph connector contracts match real API schemas.
- **End-to-End Tests:** Submit via portal and email, verify ticket creation, email delivery, SLA tracking, and closure.
- **Quality Gate Tests:** Test all 7 checks with passing and failing drafts. Verify PII detection blocks sensitive data.
- **SLA Timer Tests:** Verify 70/85/95% escalation thresholds fire correctly. Test Path C SLA clock behavior (starts after review, not before).
- **Load Tests:** Concurrent query submission via both entry points. Verify idempotency, caching, and SQS throughput.
- **LLM-specific Evaluation:**
  - Golden sets: curated inputs with expected constraints (faithfulness, completeness, style, safety)
  - RAG eval: retrieval precision@k, source diversity, citation accuracy
  - Agent eval: steps ≤ max hops, cost ≤ budget, policy adherence
  - Use RAGAS and LangChain evaluators for LLM-as-a-judge scoring

---

## Build Order — 8 Phases

Follow this exact phase order. Do NOT skip phases or build out of sequence. Each phase has gate criteria that must be met before proceeding.

### Phase 1: Foundation and Data Layer
**Duration Estimate:** 1–2 weeks
**Purpose:** Establish the database schema, Pydantic models, and project skeleton that all subsequent phases depend on.
**Entry Criteria:** Python 3.12+ installed, uv configured, project repo initialized. RDS PostgreSQL accessible via SSH tunnel. .env file configured.

**What to Build:**
- Project scaffolding: full folder structure under src/ (models/, intake/, pipeline/nodes/, pipeline/prompts/, connectors/, config/, utils/, db/migrations/) plus tests/, docs/
- Configuration module (`config/settings.py`): pydantic-settings BaseSettings loading from .env, all configurable thresholds
- Utility modules: `src/utils/helpers.py` (ist_now, generate_query_id, generate_correlation_id), `src/utils/logger.py` (structlog config), `src/utils/exceptions.py` (domain exceptions), `src/utils/decorators/` (4 logging decorators)
- All Pydantic models in `src/models/` (ParsedEmailPayload, QuerySubmission, AnalysisResult, DraftResponse, QualityGateResult, TriagePackage, ReviewerDecision, RoutingDecision, SLATarget, KBArticleMatch, KBSearchResult, TicketCreateRequest, TicketInfo, EpisodicMemoryEntry, VendorContext, PipelineState TypedDict)
- PostgreSQL schema (intake, workflow, audit, memory, reporting, cache namespaces)
- Database migration files in `src/db/migrations/` (include pgvector extension, memory.embedding_index with vector(1536))
- PostgreSQL connector (`src/db/connection/`): folder module with `client.py` (SSH tunnel, asyncpg pool), `queries.py` (CRUD helpers, idempotency check, cache read/write with expires_at), `health.py` (health check, migrations)
- FastAPI project structure with health check endpoint
- `.env` configuration

**Gate Criteria:** All models pass validation tests. Database migrations run cleanly. PostgreSQL connector connects via SSH tunnel and runs queries. Idempotency check works (first insert returns True, second returns False). Logging produces valid JSON with correlation_id. Health check returns 200. `uv run ruff check .` passes. `uv run pytest` passes.

### Phase 2: Intake Services (Email + Portal)
**Duration Estimate:** 2–3 weeks
**Purpose:** Build both entry points so queries can enter the system.
**Entry Criteria:** Phase 1 gate passed. All models, DB schema, and PostgreSQL connector working.

**What to Build:**
- (A) Portal intake: POST /queries endpoint with JWT auth, Pydantic validation, ID generation, idempotency check, PostgreSQL insert, EventBridge publish, SQS enqueue, HTTP 201 response
- (B) Email intake: MS Graph webhook receiver, MIME parser, attachment extraction, vendor identification (Salesforce lookup + fallback chain), thread correlation, raw email S3 storage, SQS enqueue

**Gate Criteria:** Both paths produce valid SQS messages. Idempotency works. Vendor ID resolved (or UNRESOLVED for email). Thread correlation returns NEW/EXISTING_OPEN/REPLY_TO_CLOSED.

### Phase 3: AI Pipeline Core (Steps 7–9)
**Duration Estimate:** 2–3 weeks
**Purpose:** Build the LangGraph orchestrator, Query Analysis Agent (LLM Call #1), routing engine, and KB search.
**Entry Criteria:** Phase 2 gate passed. Both intake paths working, messages arriving in SQS. Bedrock model access confirmed (Claude Sonnet 3.5 and Titan Embed v2).

**What to Build:**
- (A) LangGraph graph (`src/orchestration/graph.py`) with SQS consumer (`src/orchestration/sqs_consumer.py`), context loading node (Step 7)
- (B) Query Analysis node (Step 8: prompt template → Bedrock Claude → parse AnalysisResult → confidence branching at 0.85)
- (C) Routing node (Step 9A: deterministic rules engine)
- (D) KB Search node (Step 9B: embed query → cosine similarity on pgvector in PostgreSQL)
- (E) Decision point: KB match >= 80% routes to Path A; otherwise Path B

**Gate Criteria:** LangGraph graph executes end-to-end. Analysis produces valid AnalysisResult. Routing produces valid RoutingDecision. KB search returns ranked articles. Confidence branching correctly divides Path A/B/C.

### Phase 4: Response Generation and Delivery (Steps 10–12)
**Duration Estimate:** 2 weeks
**Purpose:** Build the Resolution Agent (Path A), Communication Agent (Path B), Quality Gate, ticket creation, and email delivery.
**Entry Criteria:** Phase 3 gate passed. Pipeline routes queries to Path A or Path B correctly.

**What to Build:**
- (A) Resolution node (Step 10A): LLM Call #2 using KB facts
- (B) Acknowledgment node (Step 10B): acknowledgment-only email
- (C) Quality Gate node (Step 11): 7-check validation
- (D) Delivery node (Step 12): ServiceNow ticket creation + MS Graph email delivery
- (E) Status updates: PostgreSQL, EventBridge events

**Gate Criteria:** Both Path A and Path B produce validated emails. Quality Gate catches PII, restricted terms, and format violations. Ticket created in ServiceNow. Email sent via MS Graph.

### Phase 5: Human Review and Path C (Steps 8C.1–8C.3)
**Duration Estimate:** 1–2 weeks
**Purpose:** Build the low-confidence human review workflow.
**Entry Criteria:** Phase 4 gate passed. Path A and Path B fully working end-to-end.

**What to Build:**
- (A) TriagePackage creation in triage node, callback token generation, workflow pause
- (B) Human review API: GET /triage/queue, POST /triage/{id}/review
- (C) Workflow resume with corrected data

**Gate Criteria:** Workflow pauses on low confidence. Triage package contains all required fields. Reviewer corrections resume workflow through standard pipeline.

### Phase 6: SLA Monitoring and Closure (Steps 13–16)
**Duration Estimate:** 1–2 weeks
**Purpose:** Build SLA monitoring, Path B human investigation flow, and closure/reopen logic.
**Entry Criteria:** Phase 5 gate passed. All three paths (A, B, C) working end-to-end.

**What to Build:**
- (A) SLA Monitor: timer with 70/85/95% escalation
- (B) Path B resolution flow: ServiceNow webhook → Communication Agent → Quality Gate → email delivery
- (C) Closure logic: confirmation detection, 5-day auto-close, reopen vs new-linked-ticket
- (D) Episodic memory: save closure summary for future context

**Gate Criteria:** SLA escalation fires at correct thresholds. Path B end-to-end works. Auto-closure works. Reopen creates correct ticket state. Episodic memory saved.

### Phase 7: Frontend Portal (Angular)
**Duration Estimate:** 2–3 weeks
**Purpose:** Build the Angular vendor portal and human review triage portal.
**Entry Criteria:** Phase 6 gate passed. All backend functionality working. API endpoints stable.

**What to Build:**
- (A) **Angular project structure** with 6 modules:
  - Auth Module: login page, auth guard, JWT interceptor (Cognito-based with role-based routing)
  - Vendor Module: dashboard, query list, query detail, new query wizard (3-step: type → details → review)
  - Reviewer Module: triage queue, review detail, correction form
  - Admin Module: metrics dashboard, SLA charts, path distribution, cost tracking
  - Shared Module: header, sidebar, status badge, loading spinner, toast notifications
  - Core Module: API service, auth service, error interceptor, config service
- (B) Vendor portal features: dashboard (open/resolved counts, avg time, recent queries), query wizard, query detail with status timeline and SLA countdown
- (C) Triage review portal: triage queue with confidence scores, full triage package display, correction form (override intent, vendor, routing, confidence)
- (D) Admin dashboard: SLA compliance by path/tier, path distribution pie chart, LLM cost per query, processing time P99
- (E) Technical: Angular 17+ with standalone components and signals, Tailwind CSS, lazy-loaded modules, role-based route guards, responsive design

**Gate Criteria:** Vendor can log in, see dashboard, submit a query, and track status. Reviewer can log in, see triage queue, and submit corrections. Admin can see metrics with real data. JWT auth works end-to-end with Cognito.

### Phase 8: Integration Testing, Hardening, and Production Readiness
**Duration Estimate:** 2–3 weeks
**Purpose:** Replace all stubs with real integrations, run end-to-end tests, harden for production.
**Entry Criteria:** Phase 7 gate passed. All features working individually.

**What to Build:**
- (A) Replace all stub connectors with real connections
- (B) End-to-end test suite for all 3 paths
- (C) Load testing
- (D) Security audit
- (E) Monitoring setup
- (F) Documentation (API docs, runbook, architecture diagrams)

**Gate Criteria:** All 3 paths work with real services. Reference scenario (Rajesh, TechNova, Path A, ~11s, ~$0.033) works end-to-end. Load test passes. Security audit clean.

---

## Prerequisite Files (Create If Missing)

Before starting any phase, make sure these files exist. If they don't, create them:

```
tasks/todo.md          → Start with: "# VQMS Task Tracker\n\n## Current Phase: 1\n"
tasks/lessons.md       → Start with: "# VQMS Lessons Learned\n"
Flow.md                → Runtime walkthrough of what is built (update after every phase)
README.md              → Project overview and setup (update after every phase)
.env.copy              → Copy the template from the Environment Variables section below
.gitignore             → Must include: .env, __pycache__/, *.pyc, .venv/, data/logs/, data/storage/, uv.lock
```

---

## Dependencies

### Canonical Dependencies for VQMS

```
# ===========================
# Core Framework
# ===========================
fastapi
uvicorn[standard]
pydantic>=2.0
pydantic-settings

# ===========================
# AI / LLM — Amazon Bedrock + LangChain/LangGraph
# ===========================
boto3
botocore
langchain>=0.3
langchain-aws
langchain-community
langgraph>=0.2
langsmith

# ===========================
# Database — PostgreSQL + pgvector
# ===========================
asyncpg
psycopg2-binary
pgvector
sqlalchemy[asyncio]
alembic
sshtunnel                     # SSH tunnel to bastion host for RDS access

# ===========================
# API & Web — External Service Connectors
# ===========================
httpx
aiohttp
requests
msal                          # Microsoft Graph API auth
simple-salesforce             # Salesforce CRM connector
pysnow                        # ServiceNow ITSM connector

# ===========================
# Email & Attachment Processing
# ===========================
python-multipart
email-validator
pdfplumber                    # PDF text extraction
openpyxl                      # Excel file reading
python-docx                   # Word document reading

# ===========================
# Observability & Logging
# ===========================
structlog
opentelemetry-api
opentelemetry-sdk
opentelemetry-instrumentation-fastapi
opentelemetry-exporter-otlp

# ===========================
# Templating & Prompts
# ===========================
jinja2

# ===========================
# Security & Compliance
# ===========================
cryptography
python-jose[cryptography]

# ===========================
# Utilities
# ===========================
python-dotenv
pyyaml
tenacity                      # Retry with exponential backoff
python-dateutil
orjson                        # Fast JSON serialization

# ===========================
# Testing
# ===========================
pytest
pytest-asyncio
pytest-cov
pytest-mock
moto[s3,sqs,events]           # AWS service mocking
ragas                         # RAG evaluation framework
deepeval                      # LLM-as-a-judge evaluation

# ===========================
# Dev Tools
# ===========================
ruff
mypy
pre-commit
```

> **Note:** The project uses `uv` as the package manager. The actual source of truth for dependencies is `pyproject.toml`. If someone cannot use `uv`, they can install from `requirements.txt` via `pip install -r requirements.txt`.

### requirements.txt Maintenance Rule (ALWAYS ENFORCED)

The requirements.txt file must ALWAYS stay in sync with the codebase. Follow these rules:

- **When installing a new package:** Always use `uv add <package>` to install, then immediately add the package to requirements.txt under the correct category group with a comment explaining what it is used for.
- **When removing a package:** Remove it from both pyproject.toml and requirements.txt.
- **When creating any new .py file:** After writing the file, check if it imports any new third-party package. If yes, add it to requirements.txt immediately.
- **Before finishing any task:** Run a quick scan of all imports and verify requirements.txt has every third-party package listed.
- **Never leave requirements.txt out of date.** If you install something and forget to add it to requirements.txt, that is a mistake — log it in tasks/lessons.md.
- **Format:** Group packages by category with comment headers. One package per line. Add a short inline comment for packages whose purpose is not obvious.

---

## Environment Variables (.env.copy)

```env
# ============================================================
# VQMS Environment Variables Template
# Copy this file to .env and fill in real values
# NEVER commit .env to git — only .env.copy is committed
# ============================================================

# ===========================
# APPLICATION
# ===========================
APP_ENV=development                          # development | staging | production
APP_NAME=vqms
APP_VERSION=1.0.0
APP_DEBUG=true                               # true in dev, false in production
APP_PORT=8000
LOG_LEVEL=DEBUG                              # DEBUG | INFO | WARNING | ERROR
CORRELATION_ID_HEADER=X-Correlation-ID

# ===========================
# SECRETS BACKEND
# ===========================
APP_SECRETS_BACKEND=env                      # "env" or "secretsmanager" — use .env in dev

# ===========================
# AWS GENERAL
# ===========================
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=<your-aws-access-key>
AWS_SECRET_ACCESS_KEY=<your-aws-secret-key>
AWS_SESSION_TOKEN=<optional-session-token>
AWS_ACCOUNT_ID=<your-aws-account-id>

# ===========================
# AMAZON BEDROCK (LLM)
# ===========================
BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
BEDROCK_REGION=us-east-1
BEDROCK_MAX_TOKENS=4096
BEDROCK_TEMPERATURE=0.1
BEDROCK_FALLBACK_MODEL_ID=anthropic.claude-3-haiku-20240307-v1:0
BEDROCK_MAX_RETRIES=3
BEDROCK_TIMEOUT_SECONDS=30

# ===========================
# AMAZON BEDROCK (Embeddings)
# ===========================
BEDROCK_EMBEDDING_MODEL_ID=amazon.titan-embed-text-v2:0
BEDROCK_EMBEDDING_DIMENSIONS=1536

# ===========================
# POSTGRESQL DATABASE
# ===========================
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=vqms
POSTGRES_USER=<your-db-user>
POSTGRES_PASSWORD=<your-db-password>
POSTGRES_POOL_MIN=5
POSTGRES_POOL_MAX=20
DATABASE_URL=postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}

# ===========================
# SSH TUNNEL (Bastion → RDS)
# ===========================
SSH_HOST=<bastion-host-ip-or-dns>
SSH_PORT=22
SSH_USERNAME=<ssh-username>
SSH_PRIVATE_KEY_PATH=<path-to-private-key.pem>
RDS_HOST=<rds-endpoint.region.rds.amazonaws.com>
RDS_PORT=5432

# ===========================
# PGVECTOR (Semantic Memory)
# ===========================
PGVECTOR_DIMENSIONS=1536
PGVECTOR_HNSW_M=16
PGVECTOR_HNSW_EF_CONSTRUCTION=64

# ===========================
# MICROSOFT GRAPH API (Email)
# ===========================
GRAPH_API_TENANT_ID=<your-azure-tenant-id>
GRAPH_API_CLIENT_ID=<your-azure-app-client-id>
GRAPH_API_CLIENT_SECRET=<your-azure-app-client-secret>
GRAPH_API_MAILBOX=vendorsupport@yourcompany.com
GRAPH_API_POLL_INTERVAL_SECONDS=300
GRAPH_API_WEBHOOK_URL=<optional-webhook-notification-url>

# ===========================
# SALESFORCE CRM (Vendor Resolution)
# ===========================
SALESFORCE_INSTANCE_URL=https://yourcompany.my.salesforce.com
SALESFORCE_USERNAME=<your-sf-username>
SALESFORCE_PASSWORD=<your-sf-password>
SALESFORCE_SECURITY_TOKEN=<your-sf-security-token>
SALESFORCE_CONSUMER_KEY=<your-sf-consumer-key>
SALESFORCE_CONSUMER_SECRET=<your-sf-consumer-secret>

# ===========================
# SERVICENOW ITSM (Ticket Operations)
# ===========================
SERVICENOW_INSTANCE_URL=https://yourcompany.service-now.com
SERVICENOW_USERNAME=<your-snow-username>
SERVICENOW_PASSWORD=<your-snow-password>
SERVICENOW_CLIENT_ID=<your-snow-oauth-client-id>
SERVICENOW_CLIENT_SECRET=<your-snow-oauth-client-secret>

# ===========================
# AWS S3 (Storage — single bucket, prefix-organized)
# ===========================
S3_BUCKET_DATA_STORE=vqms-data-store

# ===========================
# AWS SQS (Queues)
# ===========================
SQS_QUEUE_PREFIX=vqms-
SQS_DLQ_NAME=vqms-dlq
SQS_MAX_RECEIVE_COUNT=3
SQS_VISIBILITY_TIMEOUT=300

# ===========================
# AWS EVENTBRIDGE (Events)
# ===========================
EVENTBRIDGE_BUS_NAME=vqms-event-bus
EVENTBRIDGE_SOURCE=com.vqms

# ===========================
# AWS COMPREHEND (PII Detection)
# ===========================
COMPREHEND_LANGUAGE_CODE=en

# ===========================
# AWS COGNITO (Auth)
# ===========================
COGNITO_USER_POOL_ID=<your-user-pool-id>
COGNITO_CLIENT_ID=<your-cognito-client-id>
COGNITO_DOMAIN=<your-cognito-domain>

# ===========================
# PORTAL CONFIGURATION
# ===========================
PORTAL_SESSION_TTL_HOURS=8
PORTAL_QUERY_ID_PREFIX=VQ
PORTAL_SSO_ENABLED=false
PORTAL_SSO_PROVIDER=<okta|azure_ad>
PORTAL_SSO_METADATA_URL=<your-sso-metadata-url>

# ===========================
# AWS SECRETS MANAGER
# ===========================
SECRETS_MANAGER_PREFIX=vqms/

# ===========================
# OPENTELEMETRY (Observability)
# ===========================
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
OTEL_SERVICE_NAME=vqms
OTEL_TRACES_SAMPLER=parentbased_traceid_ratio
OTEL_TRACES_SAMPLER_ARG=1.0

# ===========================
# SLA CONFIGURATION
# ===========================
SLA_WARNING_THRESHOLD_PERCENT=70
SLA_L1_ESCALATION_THRESHOLD_PERCENT=85
SLA_L2_ESCALATION_THRESHOLD_PERCENT=95
SLA_DEFAULT_HOURS=24

# ===========================
# AGENT CONFIGURATION
# ===========================
AGENT_CONFIDENCE_THRESHOLD=0.85
AGENT_MAX_HOPS=4
AGENT_BUDGET_MAX_TOKENS_IN=8000
AGENT_BUDGET_MAX_TOKENS_OUT=4096
AGENT_BUDGET_CURRENCY_LIMIT_USD=0.50

# ===========================
# KB SEARCH CONFIGURATION
# ===========================
KB_MATCH_THRESHOLD=0.80                      # Minimum cosine similarity for KB article match
KB_MAX_RESULTS=5                             # Max KB articles to return per search
KB_RESOLUTION_CONFIDENCE_THRESHOLD=0.85      # Min Resolution Agent confidence to proceed with Path A
```

---

## Deployment Readiness (Production — NOT Created During Dev Mode)

When ready for production deployment:
- Dockerize the FastAPI application and SQS consumers
- Deploy to EC2 or ECS behind API Gateway
- Angular frontend deployed to S3 + CloudFront
- Database migrations run via a CI/CD pipeline
- Environment-specific configuration via AWS Systems Manager Parameter Store or Secrets Manager
- Blue/green deployment with rollback capability

**Do NOT create any deployment artifacts during development mode.** This section is for reference only.

---

## Final Development Checklist

Before declaring the system complete, verify every item below:

### Data Layer
- [ ] PostgreSQL schema deployed with all namespaces (intake, workflow, audit, memory, reporting, cache)
- [ ] pgvector extension enabled and memory.embedding_index table created with vector(1536)
- [ ] PostgreSQL cache tables operational with correct TTLs for idempotency, vendor cache, workflow state
- [ ] Cache cleanup task running every 15 minutes
- [ ] S3 bucket created (vqms-data-store, prefix-organized: inbound-emails/, attachments/, processed/, templates/, archive/)
- [ ] Database migrations baselined and version-controlled

### Entry Points
- [ ] Portal path: POST /queries returns query_id in < 500ms
- [ ] Email path: webhook + polling ingestion processes emails in < 5 seconds
- [ ] Idempotency guards reject duplicate submissions on both paths
- [ ] Thread correlation correctly identifies NEW, EXISTING_OPEN, REPLY_TO_CLOSED

### AI Pipeline
- [ ] LangGraph orchestrator consumes from SQS and executes full graph
- [ ] Query Analysis Agent classifies intent with > 0.85 confidence for clear queries
- [ ] Confidence branching correctly routes to Path A/B (>= 0.85) or Path C (< 0.85)
- [ ] KB search returns ranked articles filtered by category
- [ ] Routing engine assigns correct team and SLA based on rules

### Response Generation
- [ ] Resolution Agent (Path A) drafts email with specific KB-sourced facts
- [ ] Communication Drafting Agent (Path B) drafts acknowledgment with ticket number and SLA
- [ ] Quality Gate passes all 7 checks on valid drafts and rejects invalid ones (ticket format INC-XXXXXXX, SLA wording, required sections, restricted terms, length, citations, PII)
- [ ] PII detection strips sensitive data from outbound emails
- [ ] ServiceNow tickets created with correct assignment and metadata
- [ ] Emails delivered via MS Graph /sendMail with correct threading

### Path C
- [ ] Low-confidence queries pause workflow via callback token
- [ ] Triage portal displays TriagePackage for reviewer
- [ ] Reviewer corrections resume workflow with validated data

### SLA
- [ ] SLA monitor fires escalation at 70/85/95% thresholds
- [ ] Path C SLA clock starts after review, not before
- [ ] SLA metrics recorded in reporting.sla_metrics

### Closure
- [ ] Confirmation replies close tickets
- [ ] 5-business-day auto-closure works
- [ ] Reopen vs new-linked-ticket decision works correctly
- [ ] Episodic memory saved on closure

### Frontend
- [ ] Vendor portal: login, dashboard, wizard, query tracking
- [ ] Triage portal: queue, review, correction submission

### Monitoring & Security
- [ ] Correlation ID propagated across all services
- [ ] EventBridge events published for all state transitions
- [ ] Audit log records every action with timestamp and actor
- [ ] JWT auth enforced on all endpoints via Cognito Authorizer
- [ ] vendor_id extracted from JWT, never from payload

### Testing
- [ ] All 3 paths (A, B, C) pass end-to-end integration tests
- [ ] Reference scenario (Rajesh, TechNova, Path A, ~11s, ~$0.033) works end-to-end

---

## Scope Control

### What to DO (development mode)
- Create every file with proper module docstrings, imports, and type hints
- Write clear, commented function signatures with descriptive docstrings
- Use `TODO` comments with phase references for unimplemented logic
- Create all Pydantic models with field descriptions and validation rules
- Create all SQL migration files with proper schema definitions
- Write simple, readable unit tests for every model and utility function
- Follow the build order — never jump ahead to later phases

### What NOT to do (save for production)
- Do NOT create deployment files (Dockerfile, CDK, SAM, CloudFormation, Terraform, CI/CD) until explicitly approved
- Do NOT write code that creates, deletes, or modifies AWS resources (limited office IAM privileges)
- Do NOT call AWS Secrets Manager directly — read secrets from environment variables in dev
- Do NOT build complex abstraction layers (Protocol classes, factory patterns) until needed
- Do NOT add OpenTelemetry instrumentation on every function — basic logging is enough for now
- Do NOT implement full circuit breaker patterns — simple retry with backoff is sufficient
- Do NOT build rate limiters with token bucket algorithms — basic semaphore limits are fine
- Do NOT optimize for performance — optimize for readability and correctness first

---

## Common Mistakes to Avoid

- Do not start with UI or dashboards — the value is in the backend pipeline
- Do not tightly couple orchestration with integrations — components communicate through clean interfaces
- Do not mix parsing logic with business logic — email parsing is mechanical, business decisions happen in pipeline nodes
- Do not call Bedrock directly from every module — all LLM calls AND embedding calls go through `src/adapters/bedrock.py` or `src/adapters/llm_gateway.py`
- Do not create a ticket before thread correlation is checked — always check for existing tickets first
- Do not skip idempotency — every external write must be idempotent (PostgreSQL INSERT ON CONFLICT, check-before-create)
- Do not build every branch before one happy path works — get new-email-to-acknowledgment working first
- Do not leave audit logging until later — every side-effect writes to audit.action_log from day one
- Do not hardcode prompts across files — versioned templates in `src/orchestration/prompts/` loaded by the prompt manager
- Do not forget dead letter queue handling — every SQS queue has vqms-dlq as its DLQ
- Do not write local/mock fallback code in connectors — all connectors connect to real cloud services; use `moto` for tests only
- Do not write boto3 resource creation calls — infra is pre-provisioned by the DevOps team
- Do not treat portal and email paths as separate systems — they MUST converge into the same unified pipeline at the LangGraph orchestrator
- Do not confuse Path A and Path B email types — Path A sends RESOLUTION (full answer), Path B sends ACKNOWLEDGMENT (no answer, just confirmation)
- Do not start SLA timers for Path C before human review completes — review time is excluded from SLA
- Do not send any email to the vendor during Path C pause — workflow is fully stopped until reviewer acts
- Do not skip KB search even for Path B — the KB search result (low/no match) is what DETERMINES it is Path B
- Do not use the Resolution Agent for Path B acknowledgments — Resolution node is Path A only; Acknowledgment node handles Path B
- Do not extract vendor_id from request payload — always from JWT claims
- Do not silently swallow Quality Gate failures — trigger DRAFT_REJECTED status and route to human review

---

## Design Checklists

### Agent Design Checklist
- [ ] Single responsibility and focused tool scope
- [ ] System prompt minimal, task-oriented, and versioned
- [ ] Self-check and reviewer loop defined
- [ ] Stop conditions and max hops defined
- [ ] Policy enforcement integrated

### RAG Checklist
- [ ] Proper chunking by semantic boundaries with metadata (document_id, chunk_id, source_url, timestamp)
- [ ] Filter strategies defined (category, tenant, language, freshness)
- [ ] Retrieval metrics instrumented
- [ ] Source citations enforced
- [ ] PII redaction before index

### Ops Checklist (for production readiness — Phase 8)
- [ ] Rate limits per provider/tenant
- [ ] Circuit breakers configured
- [ ] Budget manager active
- [ ] Observability (logs/traces/metrics)
- [ ] Runbooks and rollback plan

---

## Risks, Dependencies, and Assumptions

### Risks
- **Bedrock latency:** LLM calls target ~3-4 seconds per call. Latency spikes could impact Path A's ~11-second target. Mitigation: set timeout and fallback to Path B if resolution LLM call exceeds threshold.
- **KB quality:** Path A resolution quality depends entirely on KB article accuracy and coverage. Poor KB articles produce incorrect AI responses despite high confidence. Mitigation: KB article review process and quality scoring.
- **Salesforce vendor matching:** Email path depends on matching sender email to Salesforce contacts. Vendors using personal email may result in UNRESOLVED. Mitigation: fallback chain (email → body extraction → fuzzy name match).
- **SLA timer accuracy:** Timer granularity may affect very short SLAs. Mitigation: test with real SLA windows. Use database-level timestamps, not application-level.
- **PostgreSQL as cache (no Redis):** Higher latency for idempotency checks and cache reads compared to Redis. Mitigation: proper indexing on idempotency_keys and cache tables. Idempotency check is INSERT, not SELECT+INSERT. Monitor query latency.
- **Graph API webhook reliability:** Missed email notifications possible. Mitigation: reconciliation polling every 5 minutes catches anything webhook missed. Both feed into same idempotency check.
- **Prompt injection in vendor emails:** LLM could follow instructions embedded in vendor email body. Mitigation: prompt engineering with clear system/user boundary. Never execute instructions from user documents. Content moderation layer.

### Dependencies
- AWS account with Bedrock access (Claude Sonnet 3.5 and Titan Embed v2 model access)
- Salesforce CRM instance with vendor master data and API credentials
- ServiceNow ITSM instance with incident table access
- Microsoft 365 tenant with Graph API permissions for shared mailbox and sendMail
- Cognito user pool (vqms-agent-portal-users) configured with vendor and reviewer roles
- Knowledge base articles loaded into PostgreSQL pgvector (memory.embedding_index) with embeddings

### Assumptions
- The confidence threshold of 0.85 for Path A/B vs Path C is a **configurable parameter**, not hardcoded
- KB articles are pre-embedded and stored in PostgreSQL via pgvector (`memory.embedding_index`). The embedding pipeline is outside scope of this plan
- Prompt templates (query-analysis, resolution, acknowledgment) are pre-authored and versioned in `src/orchestration/prompts/`
- The 7-check Quality Gate rules are defined in **configuration**, not hardcoded
- SLA tiers and escalation thresholds are loaded from **configuration** (Silver + High = 4 hours)
- The Angular frontend communicates only through the FastAPI REST API — no direct database or AWS access from the browser
- All AWS resources (S3 buckets, SQS queues, EventBridge bus) are pre-provisioned by the DevOps team before Phase 2 begins

---

## Core Principles
- **Development First:** We are writing development code — simple, clear, easy to understand. Production hardening comes later.
- **5-Layer Architecture:** Models → Intake → Pipeline → Connectors → Supporting Files. Every piece of code belongs to one of these layers.
- **Standards for Naming, Not Complexity:** Follow the coding standards for naming conventions, project structure, and documentation. Skip the advanced patterns (circuit breakers, token buckets, full OpenTelemetry) until production mode.
- **Architecture Aligned:** Every pipeline node, connector, integration, queue, event, and flow must trace back to the VQMS architecture doc and solution flow doc.
- **Two Entry Points, One Pipeline:** Email and Portal paths produce different payloads on different queues but converge into the same unified AI pipeline at the LangGraph Orchestrator (`src/orchestration/graph.py`). Code must handle both origins cleanly.
- **Three Paths Are First-Class:** Path A (AI-Resolved), Path B (Human-Team-Resolved), and Path C (Low-Confidence) are not edge cases — they are core system behavior. Every component from routing to communication drafting to SLA monitoring must be path-aware.
- **Bottom-Up Build:** Models → connectors → intake → pipeline nodes → orchestration. Never top-down.
- **Simplicity First:** Make every change as simple as possible. Minimal code impact.
- **Comments That Teach:** Write comments that explain the WHY. A new developer should be able to read any file and understand the reasoning behind decisions.
- **Descriptive Names Over Clever Code:** If a name is good enough, you do not need a comment. If you need a comment to explain what a variable holds, rename the variable.
- **Correlation Everywhere:** Every function in the pipeline must accept and propagate `correlation_id`.
- **Idempotency Everywhere:** Every external write must be idempotent. Use PostgreSQL INSERT ON CONFLICT for dedup, check-before-create for ServiceNow.
- **No Deployment Without Approval:** Infrastructure and deployment files are gated behind explicit user approval.
- **Office AWS Constraints:** This is an enterprise project with limited IAM privileges. All code connects to real cloud services. Never create AWS resources from code.
- **Configurable Thresholds:** Confidence threshold (0.85), KB match threshold (0.80), SLA targets, Quality Gate rules — all must be configurable, not hardcoded.
