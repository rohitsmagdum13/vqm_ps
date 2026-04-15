# VQMS — Vendor Query Management System

An agentic AI platform that automates vendor query resolution for enterprise support teams. Vendors submit queries via email or a web portal. The system uses LLM-powered analysis, knowledge base search, and automated response generation to resolve queries or route them to human teams.

**Owner:** Hexaware Technologies
**Stack:** Python 3.12 + FastAPI + LangGraph + Amazon Bedrock + PostgreSQL + AWS

---

## Current State

**Phase 4: Response Generation and Delivery** — complete.

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
- MIME parsing, attachment extraction (PDF/Excel/Word/CSV)
- Salesforce vendor identification (3-step fallback: exact email, body extraction, fuzzy name)
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
```

### Run the Backend

**Important:** Port 8000 may be occupied by the old `vqm` project. Use port 8002 (or any free port) for this project.

```bash
# Terminal 1: Start the backend
uv run uvicorn main:app --reload --port 8002
```

Then open: http://localhost:8002/docs (Swagger UI)

Verify health: `curl http://localhost:8002/health` — should return `"database":"connected"`.

### Run the Frontend

The frontend's API URL is configured in `frontend/src/environments/environment.ts`. Make sure `apiUrl` matches the backend port.

```bash
# Terminal 2: Start the frontend
cd frontend
npm install          # First time only
npx ng serve --port 4200
```

Then open: http://localhost:4200/login

### Run Both (Quick Reference)

```bash
# Terminal 1 (backend)
cd C:\Users\ROHIT\Work\Office\Hex_Proj\Main\vqm_ps
uv run uvicorn main:app --reload --port 8002

# Terminal 2 (frontend)
cd C:\Users\ROHIT\Work\Office\Hex_Proj\Main\vqm_ps\frontend
npx ng serve --port 4200
```

### Run Tests

```bash
uv run pytest                    # Run all tests
uv run pytest --cov=src          # With coverage
uv run ruff check .              # Linting
cd frontend && npx ng build      # Verify frontend compiles
```

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

### System
| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/health` | GET | None | Health check |
| `/webhooks/ms-graph` | POST | HMAC | Graph API email notifications |

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
| 5 | Planned | Human review: Path C triage workflow |
| 6 | Planned | SLA monitoring and closure logic |
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
