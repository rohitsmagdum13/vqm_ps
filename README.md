# VQMS — Vendor Query Management System

An agentic AI platform that automates vendor query resolution for enterprise support teams. Vendors submit queries via email or a web portal. The system uses LLM-powered analysis, knowledge base search, and automated response generation to resolve queries or route them to human teams.

**Owner:** Hexaware Technologies
**Stack:** Python 3.12 + FastAPI + LangGraph + Amazon Bedrock + PostgreSQL + AWS

---

## Current State

**Phase 6: SLA Monitoring and Closure** — complete.

### What Works Right Now

**Authentication:**
- Login with username/password (POST /auth/login) — returns JWT token
- Logout with token blacklisting (POST /auth/logout)
- JWT middleware protects all endpoints (Bearer token required)
- Auto-refresh: near-expiry tokens get silently renewed via X-New-Token header
- Swagger UI has an Authorize button — paste your JWT to test all protected endpoints

**Portal Intake (vendor submits a query via web form):**
- POST /queries — validates input, generates VQ-2026-XXXX query ID, stores in PostgreSQL, publishes to EventBridge, enqueues to SQS
- GET /queries/{query_id} — check query status (vendor can only see their own queries)
- SHA-256 idempotency — same vendor + subject + description = 409 Duplicate

**Email Intake (vendor sends email to vendor-support@company.com):**
- Microsoft Graph API webhook + reconciliation polling (every 5 min)
- Graph-side `$filter` drops auto-reply / out-of-office / NDR subjects before they reach us
- MIME parsing, attachment extraction (PDF/Excel/Word/CSV)
- Salesforce vendor identification (3-step fallback: exact email, body extraction, fuzzy name)
- **Relevance filter (4 layers)** — rejects hello-only messages, unknown senders, newsletters, and auto-submitted mail BEFORE any Bedrock cost. Optional Haiku classifier for borderline cases (off by default). See `src/services/email_intake/relevance_filter.py`.
- Thread correlation (In-Reply-To, References, conversationId)
- Raw email storage in S3, metadata in PostgreSQL
- GET /emails — paginated email chains with filtering and search
- GET /emails/stats — dashboard statistics
- GET /emails/{query_id} — single email chain detail with attachments

**AI Pipeline (LangGraph state machine):**
- Context loading (vendor profile from Salesforce + episodic memory)
- Query analysis (LLM Call #1 via Bedrock Claude — 8-layer defense strategy)
- Confidence check (>= 0.85 continues, < 0.85 routes to Path C)
- Routing (deterministic rules: team assignment, SLA target)
- KB search (Titan Embed v2 embeddings, pgvector cosine similarity)
- Path decision (KB match >= 80% = Path A, otherwise Path B)
- Resolution drafting — Path A (LLM Call #2: full answer from KB articles)
- Acknowledgment drafting — Path B (LLM Call #2: receipt confirmation only)
- Quality Gate (7 deterministic checks: ticket format, SLA wording, required sections, restricted terms, word count, source citations, PII scan)
- Delivery (ServiceNow ticket creation + Graph API email send)
- SQS consumer pulls from both intake queues and feeds the graph

**Human Review (Path C — low confidence < 0.85):**
- Triage node persists a TriagePackage to `workflow.triage_packages` and PAUSES the workflow (status=PAUSED, processing_path=C)
- HumanReviewRequired event published to EventBridge
- GET /triage/queue — reviewer queue of pending packages (oldest first, limit clamped to [1, 200])
- GET /triage/{query_id} — full triage package with AI analysis, confidence breakdown, suggested routing
- POST /triage/{query_id}/review — reviewer submits corrections (corrected_intent, corrected_vendor_id, confidence_override, reviewer_notes); `reviewer_id` is always taken from JWT sub, never from request body
- On review: audit row written to `workflow.reviewer_decisions`, package flipped to REVIEWED, corrected analysis written back to `workflow.case_execution`, query re-enqueued to the intake SQS queue with `resume_context.from_triage=True`
- Workflow resume re-enters `context_loading` with confidence now 1.0 (or reviewer's override) and naturally flows to Path A or Path B — no parallel "reviewed" branch
- Graceful degradation: if SQS is unavailable, audit trail is still persisted and `resume_method="db_only"` is returned

**SLA Monitoring, Closure, and Episodic Memory (Phase 6):**
- `SlaMonitor` — asyncio background task, ticks every `sla_monitor_interval_seconds` (default 60s). Scans `workflow.sla_checkpoints` for active cases and publishes `SLAWarning70` / `SLAEscalation85` / `SLAEscalation95` at 70% / 85% / 95% elapsed. Idempotent via per-threshold boolean flags — each event fires once per case.
- `ResolutionFromNotesNode` (Step 15) — when ServiceNow marks a Path B ticket RESOLVED, `POST /webhooks/servicenow` re-enqueues the case with `resume_context.action="prepare_resolution"`. The LangGraph entry-switch routes it directly to `resolution_from_notes → quality_gate → delivery`, skipping the intake nodes. The node fetches ServiceNow work notes, renders the `resolution_from_notes_v1` prompt with vendor-tier-aware SLA phrasing (Platinum / Gold / Silver / Bronze), calls the LLM gateway, and produces a `DraftResponse`.
- `ClosureService` — single close_case write path: updates `workflow.case_execution.status=CLOSED`, flips `workflow.sla_checkpoints.last_status=CLOSED` so SLA monitor ignores it, updates ServiceNow to `Closed`, publishes `TicketClosed`, and calls `EpisodicMemoryWriter.save_closure`. Three entry points: `detect_confirmation` (email-intake-driven keyword match on `settings.confirmation_keywords`), `handle_reopen` (inside window → flip to AWAITING_RESOLUTION + re-enqueue with `is_reopen=True`; outside window → create new linked query_id via `workflow.case_execution.linked_query_id`), and `AutoCloseScheduler.tick`.
- `AutoCloseScheduler` — asyncio background task, ticks every `auto_close_interval_seconds` (default 3600s). Selects rows from `workflow.closure_tracking` with `auto_close_deadline <= now()` and calls `close_case(reason="AUTO_CLOSED")`. `DateHelper.add_business_days` skips Sat/Sun (no holiday calendar in dev mode).
- `EpisodicMemoryWriter` — on every close, INSERTs one row into `memory.episodic_memory` with `{memory_id, vendor_id, query_id, intent, resolution_path, outcome, resolved_at, summary}`. Summary is deterministic in dev mode (`"{intent} for {vendor_id}: {processing_path} resolution, closed with {reason}"`). These rows are what `context_loading._load_episodic_memory()` surfaces on future queries from the same vendor — the system learns from its own history.

**Vendor Management (Salesforce Vendor_Account__c):**
- GET /vendors — list all active vendors, sorted ascending (V-001 first)
- POST /vendors — create a new vendor (auto-generates V-XXX ID, returns full record)
- PUT /vendors/{vendor_id} — update vendor fields (returns full record after update)
- DELETE /vendors/{vendor_id} — permanently delete a vendor

**Infrastructure:**
- PostgreSQL on RDS via SSH tunnel (6 schemas, 14+ tables, pgvector)
- AWS S3 (single bucket, prefix-organized)
- AWS SQS (intake queues + DLQ)
- AWS EventBridge (event publishing)
- Amazon Bedrock (Claude Sonnet 3.5 + Titan Embed v2)
- OpenAI fallback (GPT-4o + text-embedding-3-small)
- ServiceNow ITSM (ticket creation + status updates via httpx)
- Microsoft Graph API (email fetch + send via httpx + MSAL)
- Structured logging (structlog, IST timestamps, correlation IDs)

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.12, FastAPI, LangGraph |
| AI/LLM | Amazon Bedrock (Claude Sonnet 3.5, Titan Embed v2), OpenAI (dev fallback) |
| Database | PostgreSQL on RDS (pgvector for embeddings), SSH tunnel via bastion |
| Cloud | AWS (S3, SQS, EventBridge, Cognito) |
| Integrations | Microsoft Graph API (email), Salesforce CRM (vendors), ServiceNow ITSM (tickets) |
| Auth | JWT (HMAC-SHA256) via python-jose, werkzeug password hashing |
| Frontend | Angular 17+ (standalone components, zero CSS — browser defaults) |
| Package Manager | uv (never use pip directly) |

---

## Setup

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) installed
- SSH key for bastion host access to RDS
- AWS credentials with Bedrock, S3, SQS, EventBridge access
- Salesforce API credentials
- Microsoft Graph API credentials (for email features)

### Install

```bash
git clone <repo-url>
cd vqm_ps
cp .env.copy .env       # Fill in real credentials
uv sync                  # Install all dependencies
```

### Configure .env

Key environment variables (see `.env.copy` for the full template):

```env
# Database (via SSH tunnel)
POSTGRES_HOST=localhost
POSTGRES_DB=vqms
SSH_HOST=<bastion-ip>
SSH_PRIVATE_KEY_PATH=<path-to-key.pem>
RDS_HOST=<rds-endpoint>

# Auth
JWT_SECRET_KEY=<your-secret-key>

# AWS
AWS_REGION=us-east-1
S3_BUCKET_DATA_STORE=vqms-data-store

# Salesforce
SALESFORCE_INSTANCE_URL=https://yourcompany.my.salesforce.com
SALESFORCE_USERNAME=<sf-user>

# Microsoft Graph API
GRAPH_API_TENANT_ID=<azure-tenant-id>
GRAPH_API_CLIENT_ID=<azure-client-id>
GRAPH_API_MAILBOX=vendorsupport@yourcompany.com

# Email Relevance Filter (drops noise before Bedrock)
EMAIL_FILTER_MIN_CHARS=30
EMAIL_FILTER_NOISE_PATTERNS=["hi","hello","hey","thanks","thank you","ok","okay","noted","received","got it","test"]
EMAIL_FILTER_USE_LLM_CLASSIFIER=false     # Flip to true to enable Haiku classifier on borderline emails
EMAIL_FILTER_ALLOWED_SENDER_DOMAINS=[]    # Sender domains allowed even when Salesforce can't resolve them
```

---

## Commands

All backend commands are run with `uv` (never `pip` directly). Frontend commands use `npx ng` or `npm`. Run these from the project root unless noted.

### Run the Backend

```bash
uv run uvicorn main:app --reload --port 8002
```

- Swagger UI: http://localhost:8002/docs
- Health check: `curl http://localhost:8002/health` — should return `"database":"connected"`
- Port 8000 may be occupied by the old `vqm` project — use 8002 (or any free port).

### Run the Frontend

```bash
cd frontend
npm install                    # First time only
npx ng serve --port 4200       # Or: npm start (defaults to 4200)
```

Then open: http://localhost:4200/login

The frontend's API URL is configured in `frontend/src/environments/environment.ts`. Make sure `apiUrl` matches the backend port.

### Run Both (Two Terminals)

```bash
# Terminal 1 (backend)
cd C:\Users\ROHIT\Work\Office\Hex_Proj\Main\vqm_ps
uv run uvicorn main:app --reload --port 8002

# Terminal 2 (frontend)
cd C:\Users\ROHIT\Work\Office\Hex_Proj\Main\vqm_ps\frontend
npx ng serve --port 4200
```

### Database Setup

```bash
uv run python scripts/run_migrations.py        # Apply all SQL migrations (000–010)
uv run python scripts/seed_admin_user.py       # Create the default admin_user / admin123
uv run python scripts/seed_knowledge_base.py   # Load KB articles + Titan embeddings into pgvector
```

### Tests, Linting, Type Checks

```bash
uv run pytest                                  # Run all backend tests
uv run pytest --cov=src --cov-report=term-missing  # With coverage report
uv run pytest tests/test_email_intake.py       # Run a single test file
uv run pytest -k "test_login"                  # Run tests matching a keyword
uv run ruff check .                            # Lint backend
uv run ruff check . --fix                      # Lint + auto-fix
cd frontend && npx ng build                    # Verify frontend compiles
cd frontend && npx ng test                     # Run frontend unit tests
```

### Dependency Management (uv)

```bash
uv sync                              # Install all backend deps from pyproject.toml
uv add <package>                     # Add a new package (updates pyproject.toml)
uv add --dev <package>               # Add a dev-only dependency
uv remove <package>                  # Remove a package
uv lock --upgrade                    # Upgrade all packages to latest versions
```

### Diagnostic / Smoke-Test Scripts (`scripts/`)

```bash
uv run python scripts/check_db.py                    # Verify SSH tunnel + PostgreSQL connectivity
uv run python scripts/check_aws_access.py            # Verify AWS credentials (S3, SQS, EventBridge)
uv run python scripts/check_bedrock.py               # Verify Bedrock model access (Claude + Titan)
uv run python scripts/check_graphapi.py              # Verify Microsoft Graph API auth + mailbox
uv run python scripts/check_servicenow.py            # Verify ServiceNow API auth
uv run python scripts/check_s3_access.py             # Verify S3 bucket access
uv run python scripts/check_iam_permissions.py       # Audit IAM permissions
uv run python scripts/check_email_poller.py          # Run one poller cycle and exit
uv run python scripts/check_embedding.py             # Test Titan embedding call
uv run python scripts/check_textract.py              # Test Textract OCR
uv run python scripts/check_thread_correlation.py    # Verify thread correlation logic
uv run python scripts/check_pipeline_artifacts.py    # List S3 artifacts written by pipeline
uv run python scripts/list_unread_emails.py          # List unread emails in the mailbox
uv run python scripts/mark_unread_mails_read.py      # Mark all unread mails as read
uv run python scripts/smoke_test_email_intake.py     # End-to-end smoke test of email intake
uv run python scripts/test_email_ingestion.py        # Drive a synthetic email through ingestion
uv run python scripts/test_portal_submission.py      # POST a synthetic portal query
uv run python scripts/run_email_to_analysis.py       # Drive intake → query analysis
uv run python scripts/run_email_to_quality_gate.py   # Full pipeline (Phase 1 → Phase 6) on first unread email
uv run python scripts/run_pipeline_to_quality_gate.py  # Drive full pipeline up to quality gate
uv run python scripts/find_vqms_tickets.py           # List VQMS tickets in ServiceNow
uv run python scripts/inspect_ticket.py <INC-XXXXX>  # Inspect a single ServiceNow ticket
uv run python scripts/describe_vendor_account.py     # Show Salesforce Vendor_Account__c schema
```

### Run a Specific Email Through the Full Pipeline

`scripts/run_email_to_quality_gate.py` runs the **complete end-to-end pipeline** in one process: Phase 1 (intake) → Phase 2 (real SQS hop) → Phase 3 (AI pipeline: Steps 7–11) → Phase 4 (delivery: Step 12) → Phase 6 (SLA monitor + closure + episodic memory).

By default it picks the **first unread email** in the mailbox. To run it against a **specific email by message_id**, pass `--message-id`:

```bash
# Process one specific email by its Microsoft Graph message_id
uv run python scripts/run_email_to_quality_gate.py --message-id "AAMkAGI2..."
```

Get a valid `message_id` first:

```bash
uv run python scripts/list_unread_emails.py        # Lists unread emails with their message_id values
```

Useful flag combinations for `run_email_to_quality_gate.py`:

```bash
# Real ServiceNow ticket but DO NOT email the vendor (safe dev run)
uv run python scripts/run_email_to_quality_gate.py --message-id "AAMkAGI2..." --no-email-send

# Stop before delivery — no ServiceNow ticket, no email send
uv run python scripts/run_email_to_quality_gate.py --message-id "AAMkAGI2..." --skip-delivery --skip-phase6

# Skip the real SQS hop (use intake payload directly)
uv run python scripts/run_email_to_quality_gate.py --message-id "AAMkAGI2..." --no-sqs-hop

# Skip Salesforce vendor lookup (mock vendor as None)
uv run python scripts/run_email_to_quality_gate.py --message-id "AAMkAGI2..." --skip-salesforce

# Full flow + simulate vendor confirmation (writes episodic_memory row)
uv run python scripts/run_email_to_quality_gate.py --message-id "AAMkAGI2..." --simulate-close
```

| Flag | What it does |
|------|--------------|
| `--message-id "<id>"` | Process this specific email instead of the first unread one |
| `--skip-salesforce` | Replace Salesforce connector with a mock (vendor stays unresolved) |
| `--no-sqs-hop` | Skip the real SQS enqueue/receive — pass payload directly to the graph |
| `--skip-delivery` | Stub out Step 12 (no ServiceNow ticket, no email send) |
| `--no-email-send` | Keep ServiceNow ticket creation but stub out Graph API send (no vendor email) |
| `--skip-phase6` | Skip the SLA monitor / closure tracking / auto-close section |
| `--simulate-close` | After delivery, call `ClosureService.close_case` (VENDOR_CONFIRMED) to demo episodic memory |

**Prerequisites:** `.env` configured with Graph API + AWS + PostgreSQL + Bedrock (or OpenAI) + ServiceNow credentials, KB seeded (`scripts/seed_knowledge_base.py --clear`), and migration 012 applied.

### Test the Full Portal Flow

1. Start backend: `uv run uvicorn main:app --reload --port 8002`
2. Start frontend: `cd frontend && npx ng serve --port 4200`
3. Open http://localhost:4200/login
4. Login with `admin_user` / `admin123` (or your credentials)
5. Portal dashboard shows KPIs (open, resolved, total) and query table
6. Click "+ New Query" → select type → fill details → review → submit
7. See query ID confirmation (VQ-2026-XXXX) → back to portal → query appears in table
8. Click query ID → see full query detail

**Note:** No styling — browser defaults only. Auth is real JWT (HMAC-SHA256, not fake).

### Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Login returns 500 | Wrong server running on that port | Check `curl http://localhost:<port>/health` — response must include `"database":"connected"` |
| "Submission failed" on new query | CORS preflight blocked | Verify backend has the OPTIONS middleware fix. Restart backend. |
| Health shows `"database":"disconnected"` | SSH tunnel to bastion not connected | Check SSH key, bastion host, RDS endpoint in .env |
| Port already in use | Old `vqm` server or zombie process | Use a different port, or find and kill the process |

---

## How to Use Swagger UI

### Step 1: Login

1. Open http://localhost:8002/docs
2. Expand **POST /auth/login**
3. Click "Try it out", enter:
   ```json
   {
     "username_or_email": "admin_user",
     "password": "admin123"
   }
   ```
4. Click Execute — copy the `token` from the response

### Step 2: Authorize

1. Click the **Authorize** button (top-right, lock icon)
2. Paste the token (no "Bearer " prefix needed — Swagger adds it)
3. Click Authorize, then Close

### Step 3: Test Any Endpoint

All endpoints now send your JWT automatically. Try:
- **GET /vendors** — returns vendors sorted V-001 to V-025
- **POST /vendors** — create a vendor (all fields shown in Swagger example)
- **PUT /vendors/V-001** — update a vendor (returns full record)
- **DELETE /vendors/V-026** — delete a vendor
- **GET /emails** — returns ingested email chains
- **POST /queries** — submit a new vendor query

See `docs/api_testing_guide.md` for ready-to-use test examples.

---

## API Endpoints

### Authentication
| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/auth/login` | POST | None | Login — returns JWT token |
| `/auth/logout` | POST | Bearer | Blacklist current token |

### Portal Queries
| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/queries` | GET | Bearer + X-Vendor-ID | List all queries for a vendor |
| `/queries` | POST | Bearer + X-Vendor-ID | Submit a vendor query |
| `/queries/{query_id}` | GET | Bearer + X-Vendor-ID | Get full query detail |

### Portal Dashboard
| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/dashboard/kpis` | GET | Bearer + X-Vendor-ID | Vendor KPIs (open, resolved, avg time, total) |

### Email Dashboard
| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/emails` | GET | Bearer | Paginated email chains (filter, search, sort) |
| `/emails/stats` | GET | Bearer | Dashboard statistics |
| `/emails/{query_id}` | GET | Bearer | Single email chain detail |
| `/emails/{query_id}/attachments/{id}/download` | GET | Bearer | Presigned S3 download URL |

### Vendor Management (ADMIN only)
| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/vendors` | GET | Bearer | List all active vendors (sorted V-001..V-NNN) |
| `/vendors` | POST | Bearer | Create a new vendor (auto-generates V-XXX ID) |
| `/vendors/{vendor_id}` | PUT | Bearer | Update vendor fields (returns full record) |
| `/vendors/{vendor_id}` | DELETE | Bearer | Permanently delete a vendor |

### Admin Email Send/Reply (ADMIN only)
| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/admin/email/send` | POST | Bearer (multipart/form-data) | Compose and send a fresh email to one or more vendors. Form fields: `to`, `subject`, `body_html`, optional `cc`/`bcc` (comma-separated), `vendor_id`, `query_id`, `files[]`. Optional `X-Request-Id` header dedupes replays. |
| `/admin/email/queries/{query_id}/reply` | POST | Bearer (multipart/form-data) | Reply on the existing email trail attached to `query_id`. Vendor receives the reply inside the same Outlook/Gmail conversation as the original — Graph's `/messages/{id}/reply` preserves `conversationId`, In-Reply-To, and References headers. Form fields: `body_html`, optional `cc`/`bcc`, `to_override` (defaults to original sender), `reply_to_message_id` (defaults to latest inbound), `files[]`. |

Tracking: every send creates a row in `intake.admin_outbound_emails` (plus `intake.admin_outbound_attachments` per file) with status `QUEUED -> SENT` (or `FAILED` on Graph error). Audit row written to `audit.action_log` with `actor=<admin email>`, `action=admin_email_send|admin_email_reply`. Quality Gate is intentionally skipped for admin sends (logged with `quality_gate=skipped_admin_actor`).

### Human Review / Triage (REVIEWER or ADMIN only)
| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/triage/queue` | GET | Bearer | List pending triage packages (oldest first, `limit` clamped to [1, 200]) |
| `/triage/{query_id}` | GET | Bearer | Full TriagePackage detail (original query + AI analysis + confidence breakdown + suggested routing) |
| `/triage/{query_id}/review` | POST | Bearer | Submit reviewer corrections — re-enqueues the query so the pipeline resumes with corrected analysis. Returns `{status, query_id, resume_method}` |

### System
| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/health` | GET | None | Health check |
| `/webhooks/ms-graph` | POST | HMAC | Graph API email notifications |
| `/webhooks/servicenow` | POST | HMAC (no JWT) | ServiceNow resolution-prepared callback — `{ticket_id, status, correlation_id?}`. When `status == "RESOLVED"`, looks up the case via `workflow.ticket_link`, re-enqueues to the intake SQS with `resume_context.action=prepare_resolution`, which triggers Step 15 (resolution drafted from work notes). Returns `{status: "enqueued" | "ignored" | "error", query_id?, reason?}` |

---

## Project Structure

```
vqm_ps/
├── main.py                      # FastAPI entry point (lifespan, routes, middleware)
├── CLAUDE.md                    # AI assistant instructions (full architecture)
├── Flow.md                      # Runtime data flow walkthrough
├── README.md                    # This file
│
├── src/
│   ├── models/                  # Layer 1: Pydantic data models
│   ├── services/                # Business logic (auth, portal intake, email dashboard)
│   ├── api/                     # API layer (middleware, routes)
│   │   ├── middleware/          #   JWT auth middleware
│   │   └── routes/              #   auth, queries, vendors, dashboard, webhooks
│   ├── orchestration/           # Layer 3: LangGraph pipeline + nodes + prompts
│   ├── adapters/                # Layer 4: Salesforce, Bedrock, Graph API, LLM Gateway
│   ├── storage/                 #   S3 connector
│   ├── queues/                  #   SQS connector
│   ├── events/                  #   EventBridge connector
│   ├── db/                      #   PostgreSQL connector + SQL migrations
│   ├── cache/                   #   PostgreSQL-backed cache (token blacklist)
│   ├── config/                  #   Settings (pydantic-settings from .env)
│   └── utils/                   #   Helpers, logging, exceptions, decorators
│
├── tests/                       # All tests (models, services, routes, pipeline)
├── docs/                        # Documentation
│   ├── system_flow_guide.md     #   System flow with ASCII diagrams
│   ├── detailed_technical_guide.md  # Deep-dive technical guide
│   └── api_testing_guide.md     #   API testing examples for Swagger UI
├── data/                        # Knowledge base articles
└── tasks/                       # Task tracking and lessons learned
```

---

## Three Processing Paths

Every vendor query follows one of three paths:

```
                    Query arrives (email or portal)
                              |
                    AI analyzes intent + entities
                              |
                    Confidence score >= 0.85?
                       /              \
                     YES               NO
                      |                 |
              KB has answer?        PATH C
                 /       \         (human reviews
               YES        NO       AI analysis,
                |          |        corrects, then
             PATH A     PATH B      resumes A or B)
          (AI resolves  (AI sends
           full answer)  ack only,
                        human team
                        investigates)
```

| Path | What Happens | LLM Calls | Human Needed? |
|------|-------------|-----------|---------------|
| **A** | AI drafts full resolution from KB articles | 2 | No |
| **B** | AI sends acknowledgment, human team investigates | 2-3 | Yes (investigation) |
| **C** | Low confidence — human reviewer validates AI analysis first | 2-3 | Yes (review + maybe investigation) |

---

## Build Phases

| Phase | Status | Description |
|-------|--------|-------------|
| 1 | Done | Foundation: models, DB schema, connectors, config |
| 2 | Done | Intake: email ingestion + portal submission |
| 3 | Done | AI Pipeline: LangGraph, query analysis, routing, KB search |
| 4 | Done | Response generation: resolution, acknowledgment, quality gate, delivery |
| 5 | Done | Human review: Path C triage workflow (persist + pause + reviewer API + resume via SQS) |
| 6 | Done | SLA monitoring (70/85/95% thresholds), Path B resolution-from-notes (Step 15), closure + auto-close, episodic memory write-back |
| 7 | Planned | Frontend: Angular vendor portal + triage portal |
| 8 | Planned | Integration testing, hardening, production readiness |

---

## Key Documentation

| File | What It Covers |
|------|----------------|
| `CLAUDE.md` | Full architecture, coding standards, build plan, all constraints |
| `Flow.md` | Runtime walkthrough — follow the data through every function |
| `docs/system_flow_guide.md` | System flow with ASCII diagrams (overview) |
| `docs/detailed_technical_guide.md` | Deep-dive: every service, function, table, and SQL query |
| `docs/api_testing_guide.md` | Ready-to-use API test examples for Swagger UI |
| `tasks/todo.md` | Current task tracking |
| `tasks/lessons.md` | Lessons learned from past mistakes |
