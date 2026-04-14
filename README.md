# VQMS — Vendor Query Management System

An agentic AI platform that automates vendor query resolution for enterprise support teams. Vendors submit queries via email or a web portal. The system uses LLM-powered analysis, knowledge base search, and automated response generation to resolve queries or route them to human teams.

## Current State

**Phase 3: AI Pipeline Core (Steps 7-9)** — complete.

What works right now:
- Project skeleton with 5-layer architecture
- Configuration loading from `.env` via pydantic-settings
- Structured logging via direct structlog (IST timestamps, correlation IDs, `tool=` field on connectors)
- All Pydantic data models for the full pipeline (22 models, 44 tests)
- PostgreSQL schema (6 schemas, 14 tables, pgvector) with SSH tunnel connector
- Idempotency check via `INSERT ON CONFLICT`
- **Email intake:** Graph API webhook + reconciliation polling, MIME parsing, attachment extraction (PDF/Excel/Word/CSV) with manifest, Salesforce vendor identification (3-step fallback), thread correlation, S3 storage (single bucket, prefix-organized), SQS enqueue
- **Portal intake:** POST /queries with Pydantic validation, idempotency (SHA-256 hash), EventBridge events, SQS enqueue
- **FastAPI routes:** POST /queries (201), GET /queries/{id}, POST /webhooks/ms-graph
- **AWS connectors:** S3, SQS, EventBridge (all using asyncio.to_thread)
- **External API connectors:** Microsoft Graph API (MSAL + httpx + tenacity retry), Salesforce CRM (simple-salesforce)
- **Amazon Bedrock connector:** LLM inference (Claude Sonnet 3.5) + embeddings (Titan Embed v2). Retry with tenacity, cost tracking per call.
- **OpenAI connector:** Chat Completions (GPT-4o) + Embeddings (text-embedding-3-small). Retry with tenacity, cost tracking per call.
- **LLM Gateway:** Unified interface routing to Bedrock (primary) or OpenAI (fallback). Four modes: bedrock_only, openai_only, bedrock_with_openai_fallback, openai_with_bedrock_fallback.
- **LangGraph AI pipeline:** Context loading → Query analysis (8-layer defense) → Confidence check → Routing → KB search → Path decision. Three processing paths (A/B/C) wired with conditional edges.
- **Prompt templates:** Jinja2 with StrictUndefined for query analysis, resolution, acknowledgment, resolution-from-notes
- **SQS consumer:** Pulls from both intake queues, feeds graph, deletes on success
- **JWT authentication:** Login/logout endpoints, auth middleware (Bearer token validation on all protected routes), token blacklist via PostgreSQL `cache.kv_store`, auto-refresh for near-expiry tokens
- **Vendor CRUD:** List all active vendors from Salesforce, update vendor fields (website, tier, category, payment terms, SLA settings)
- 273 tests passing, ruff clean

## Tech Stack

- **Backend:** Python 3.12, FastAPI, LangGraph
- **AI:** Amazon Bedrock (Claude Sonnet 3.5, Titan Embed v2), OpenAI (dev fallback)
- **Database:** PostgreSQL on RDS (pgvector for embeddings), accessed via SSH tunnel
- **Cloud:** AWS (S3, SQS, EventBridge, Cognito)
- **Integrations:** Microsoft Graph API (email), Salesforce CRM, ServiceNow ITSM
- **Frontend:** Angular 17+ (Phase 7)
- **Package Manager:** uv

## Setup

### Prerequisites
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) installed
- SSH key for bastion host access to RDS
- `.env` file with credentials (copy from `.env.copy`)

### Install
```bash
git clone <repo-url>
cd vqm
cp .env.copy .env       # Fill in real credentials
uv sync                  # Install all dependencies
```

### Run
```bash
uv run uvicorn main:app --reload --port 8000
```

### Test
```bash
uv run pytest
uv run ruff check .
```

## Project Structure

```
vqm/
├── src/                 # All backend Python code
│   ├── main.py          # FastAPI entry point (lifespan, routes, health check)
│   ├── models/          # Layer 1: Pydantic data models (22 models)
│   ├── intake/          # Layer 2: Email + portal entry points + routes + polling
│   ├── dashboard/       # Email dashboard API (read-only endpoints + service)
│   ├── pipeline/        # Layer 3: LangGraph AI pipeline + nodes + prompts
│   ├── connectors/      # Layer 4: S3, SQS, EventBridge, Graph API, Salesforce, PostgreSQL, Bedrock, OpenAI, LLM Gateway
│   ├── services/        # Business logic (auth service: login, JWT, blacklist)
│   ├── api/             # API layer (auth middleware, auth routes, vendor routes)
│   ├── cache/           # Cache helpers (pg_cache: token blacklist via cache.kv_store)
│   ├── config/          # Configuration (pydantic-settings)
│   ├── utils/           # Helpers, logging, exceptions, decorators
│   └── db/migrations/   # SQL schema migrations (10 files)
├── tests/               # 273 tests (models, connectors, intake, routes, pipeline, auth, vendors)
├── docs/                # Documentation and reference materials
├── data/                # Knowledge base articles, local storage
└── tasks/               # Task tracking and lessons learned
```

See `CLAUDE.md` for the full architecture, coding standards, and build plan.
See `Flow.md` for the runtime data flow walkthrough.

## API Endpoints

### Intake
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check — returns 200 |
| `/queries` | POST | Portal query submission (requires X-Vendor-ID header) |
| `/queries/{id}` | GET | Query status lookup (requires X-Vendor-ID header) |
| `/webhooks/ms-graph` | POST | MS Graph email notification webhook |

### Email Dashboard (read-only)
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/emails` | GET | Paginated list of email chains (filter by status, priority, search) |
| `/emails/stats` | GET | Dashboard summary statistics (counts by status, priority, time) |
| `/emails/{query_id}` | GET | Single email chain detail with full thread |
| `/emails/{query_id}/attachments/{attachment_id}/download` | GET | Presigned S3 download URL for attachment |

### Authentication
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/auth/login` | POST | Authenticate user — returns JWT token |
| `/auth/logout` | POST | Blacklist JWT token (requires Bearer token) |

### Vendor Management
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/vendors` | GET | List all active vendors from Salesforce (requires Bearer token) |
| `/vendors/{vendor_id}` | PUT | Update vendor fields in Salesforce (requires Bearer token) |

### Environment Variables (Auth)
Add these to your `.env` file (see `.env.copy` for template):
```
JWT_SECRET_KEY=<your-jwt-secret-key>
JWT_ALGORITHM=HS256
SESSION_TIMEOUT_SECONDS=1800
TOKEN_REFRESH_THRESHOLD_SECONDS=300
```

## Build Phases

1. **Foundation and Data Layer** — complete
2. **Intake Services (Email + Portal)** — complete
3. **AI Pipeline Core (LangGraph, Query Analysis, Routing, KB Search)** — complete
4. Response Generation and Delivery
5. Human Review and Path C
6. SLA Monitoring and Closure
7. Frontend Portal (Angular)
8. Integration Testing and Hardening
