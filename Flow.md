# VQMS — End-to-End Runtime Walkthrough

_This file traces exactly how a vendor query moves through the codebase. Updated after every phase._

## Current State: Phase 4 — Response Generation and Delivery (Complete)

Phases 1-4 are complete. Both entry points produce messages on SQS. The LangGraph pipeline consumes them, runs query analysis (LLM Call #1), confidence gating, routing, KB search, path decision, response drafting (LLM Call #2), quality gate validation, ServiceNow ticket creation, and email delivery. All three processing paths (A, B, C) are wired with real nodes (except triage placeholder for Phase 5). 358 tests pass.

---

## Email Path (Steps E1 → E2.9)

### Trigger: Incoming email to vendor-support mailbox

**Two detection mechanisms (Layer 1 — Dual Detection):**
- **Webhook (real-time):** Microsoft Graph API sends a POST to `POST /webhooks/ms-graph`
  - File: `src/intake/routes.py` -> `ms_graph_webhook()`
  - Extracts message_id from the notification resource path
  - Calls `email_intake.process_email(message_id)`
- **Reconciliation Polling (every 5 minutes):** Background poller fetches unread messages
  - File: `src/intake/polling.py` -> `ReconciliationPoller.poll_once()`
  - Calls `graph_api.list_unread_messages(top=50)`
  - For each unread message, calls `email_intake.process_email(message_id)`
  - Duplicates (already processed via webhook) return None — expected and silent

### 10-Step Email Processing Pipeline

File: `src/intake/email_intake.py` -> `EmailIntakeService.process_email(message_id)`

**Input:** Exchange Online message_id (string)
**Output:** `ParsedEmailPayload` (from `src/models/email.py`) or None (duplicate)

| Step | Code | Critical? | What it does |
|------|------|-----------|-------------|
| E2.1 | `self._postgres.check_idempotency(message_id, "email", ...)` | YES | INSERT ON CONFLICT — returns False if duplicate, pipeline stops |
| E1 | `self._graph_api.fetch_email(message_id)` | YES | GET /users/{mailbox}/messages/{id}?$expand=attachments |
| E2.2 | `self._parse_email_fields(raw_email)` | YES | Extract sender, recipients, subject, body, headers, conversationId |
| E2.7 | `IdGenerator.generate_query_id()` / `generate_execution_id()` | YES | Generate VQ-2026-XXXX and UUID v4 |
| E2.3 | `self._store_raw_email(raw_email, query_id)` | no | Upload raw JSON to S3 `inbound-emails/{query_id}/raw_email.json` (single bucket: vqms-data-store) |
| E2.4 | `self._process_attachments(raw_email, query_id)` | no | Validate → store to S3 `attachments/{query_id}/{att_id}_{filename}` → extract text → store `_manifest.json` |
| E2.5 | `self._identify_vendor(parsed)` | no | Salesforce 3-step fallback: exact email → body extraction → fuzzy name |
| E2.6 | `self._determine_thread_status(raw_email)` | no | Check conversationId in workflow.case_execution → NEW / EXISTING_OPEN / REPLY_TO_CLOSED |
| E2.8 | `self._store_email_metadata(...)` + `self._create_case_execution(...)` | YES | INSERT into intake.email_messages + workflow.case_execution |
| E2.9a | `self._eventbridge.publish_event("EmailParsed", ...)` | no | Publish audit event |
| E2.9b | `self._sqs.send_message(queue_url, payload)` | YES | Enqueue UnifiedQueryPayload to vqms-email-intake-queue |

**Critical steps** propagate errors (SQS retries). **Non-critical steps** log warnings and continue with safe defaults (None, empty list, "NEW").

### Attachment Processing

File: `src/intake/email_intake.py` -> `EmailIntakeService._process_attachments()`

Safety guardrails:
- Blocked extensions: .exe, .bat, .cmd, .ps1, .sh, .js → skipped
- Max file size: 10 MB per attachment → skipped
- Max total size: 50 MB per email → remaining skipped
- Max count: 10 attachments per email
- Text extraction: PDF (pdfplumber), Excel (openpyxl), Word (python-docx), CSV/TXT (direct decode)
- Text truncated to 5,000 chars per attachment
- After processing, stores `attachments/{query_id}/_manifest.json` via `AttachmentManifestBuilder`

### S3 Storage Architecture

Single bucket (`vqms-data-store`) with prefix-based organization:

```
vqms-data-store/
├── inbound-emails/VQ-YYYY-NNNN/raw_email.json
├── attachments/VQ-YYYY-NNNN/{att_id}_{filename}
├── attachments/VQ-YYYY-NNNN/_manifest.json
├── processed/VQ-YYYY-NNNN/email_analysis.json       [Phase 3+]
├── processed/VQ-YYYY-NNNN/response_draft.json       [Phase 4+]
├── processed/VQ-YYYY-NNNN/ticket_payload.json        [Phase 4+]
├── processed/VQ-YYYY-NNNN/resolution_summary.json    [Phase 4+]
├── templates/response_templates/{category}.json       [Phase 4+]
└── archive/VQ-YYYY-NNNN/_archive_bundle.json         [Phase 6+]
```

All S3 keys are built using `src/config/s3_paths.py` -> `build_s3_key(prefix, query_id, filename)`. No hardcoded S3 paths anywhere else in the codebase.

### Vendor Identification (3-Step Fallback)

File: `src/connectors/salesforce.py` -> `SalesforceConnector.identify_vendor()`

1. Exact email match on Salesforce Contact → `VendorMatch(match_method="exact_email", confidence=1.0)`
2. Extract emails from body text, try each → `VendorMatch(match_method="body_extraction", confidence=0.8)`
3. Fuzzy name match on Account → `VendorMatch(match_method="fuzzy_name", confidence=0.6)`
4. All fail → returns None, pipeline continues with vendor_id=None

---

## Portal Path (Steps P1 → P6)

### Frontend: Angular Portal (Phase 7 — IMPLEMENTED)

The vendor portal is an Angular 17+ standalone app in `frontend/`. Zero CSS — browser defaults only. Uses real JWT auth.

| Step | Route | What happens | Server call |
|------|-------|-------------|-------------|
| P1 — Login | /login | Username/email + password form | POST /auth/login → JWT |
| P2 — Dashboard | /portal | KPIs + query list table | GET /dashboard/kpis + GET /queries |
| P3 — Select Type | /new-query-type | Pick query type (radio/select) | None (browser only) |
| P4 — Details | /new-query-details | Subject, description, priority, reference | None (browser only) |
| P5+P6 — Review & Submit | /new-query-review | Review all fields, submit | POST /queries |
| — Query Detail | /query-status/:id | Full query info | GET /queries/{id} |

**Auth flow:** JWT token + X-Vendor-ID (= tenant from login response) injected by Angular HTTP interceptor on every request. Token auto-refresh captured via X-New-Token response header.

**Key files:**
- `frontend/src/app/services/auth.service.ts` — login, logout, token management
- `frontend/src/app/services/query.service.ts` — all query HTTP calls
- `frontend/src/app/services/wizard.service.ts` — multi-step form state
- `frontend/src/app/interceptors/auth.interceptor.ts` — Bearer + X-Vendor-ID injection
- `frontend/src/app/guards/auth.guard.ts` — route protection

### Backend: Portal Submission

File: `src/api/routes/queries.py` -> `submit_query(request, submission)`

**Input:** HTTP POST with JSON body (validated as `QuerySubmission` from `src/models/query.py`), X-Vendor-ID header
**Output:** `{"query_id": "VQ-2026-XXXX", "status": "RECEIVED", "created_at": "..."}` (HTTP 201)

### Processing Steps

File: `src/services/portal_submission.py` -> `PortalIntakeService.submit_query(submission, vendor_id)`

| Step | What it does |
|------|-------------|
| 1 | Generate SHA-256 idempotency key from vendor_id + subject + description |
| 2 | Check idempotency via `postgres.check_idempotency(key, "portal")` → DuplicateQueryError if exists (HTTP 409) |
| 3 | Generate query_id (VQ-2026-XXXX) and execution_id (UUID v4) |
| 4 | Calculate SLA deadline based on priority (Critical=4h, High=8h, Medium=24h, Low=48h) |
| 5 | INSERT into workflow.case_execution (status=RECEIVED, source=portal) — workflow state tracking |
| 6 | INSERT into intake.portal_queries (subject, query_type, priority, description, reference_number, sla_deadline) — raw submission data |
| 7 | Build UnifiedQueryPayload (thread_status always "NEW" for portal) |
| 8a | [NON-CRITICAL] Publish "QueryReceived" event to EventBridge |
| 8b | [CRITICAL] Enqueue UnifiedQueryPayload to vqms-query-intake-queue via SQS |

### Portal API Endpoints

| Endpoint | File | Purpose |
|----------|------|---------|
| GET /queries | `src/api/routes/queries.py` -> `list_queries()` | List all queries for a vendor (newest first) |
| POST /queries | `src/api/routes/queries.py` -> `submit_query()` | Submit a new query |
| GET /queries/{query_id} | `src/api/routes/queries.py` -> `get_query_status()` | Full query detail (vendor can only see own queries) |
| GET /dashboard/kpis | `src/api/routes/portal_dashboard.py` -> `get_kpis()` | KPIs: open, resolved, avg resolution hours, total |

---

## Connectors (Layer 4)

All external system interactions go through connectors in `src/connectors/`. Every connector uses direct structlog logging with a `tool=` field (e.g., `tool="s3"`, `tool="postgresql"`) for CloudWatch filtering.

| Connector | File | What it does |
|-----------|------|-------------|
| PostgresConnector | `src/connectors/postgres.py` | SSH tunnel → RDS, asyncpg pool, idempotency, cache read/write, migrations |
| S3Connector | `src/connectors/s3.py` | upload_file, download_file, generate_presigned_url, object_exists, list_objects, delete_object (single bucket: vqms-data-store, prefix-organized) |
| SQSConnector | `src/connectors/sqs.py` | send_message, receive_messages, delete_message (orjson serialization) |
| EventBridgeConnector | `src/connectors/eventbridge.py` | publish_event with 20 valid event types, detail enrichment with correlation_id |
| GraphAPIConnector | `src/connectors/graph_api.py` | MSAL OAuth2, fetch_email, send_email, list_unread_messages, webhook subscription (httpx + tenacity retry) |
| SalesforceConnector | `src/adapters/salesforce.py` | 3-step vendor identification, find_vendor_by_email, fuzzy_name_match (simple-salesforce + asyncio.to_thread) |
| ServiceNowConnector | `src/adapters/servicenow.py` | httpx.AsyncClient, create_ticket, update_ticket_status, get_ticket, get_work_notes. Lazy client init. Priority mapping CRITICAL→1..LOW→4. |
| BedrockConnector | `src/adapters/bedrock.py` | LLM inference (Claude Sonnet 3.5 via Messages API) + embeddings (Titan Embed v2, 1536 dims). Retry with tenacity on ThrottlingException/ServiceUnavailableException. Cost tracking per call. |
| OpenAIConnector | `src/adapters/openai_llm.py` | OpenAI Chat Completions (GPT-4o) + Embeddings (text-embedding-3-small). Retry with tenacity on RateLimitError/APIConnectionError/APITimeoutError. Cost tracking per call. Used as fallback behind LLM Gateway. |
| LLMGateway | `src/adapters/llm_gateway.py` | Unified LLM gateway. Routes `llm_complete()` and `llm_embed()` to Bedrock (primary) or OpenAI (fallback) based on `llm_provider` setting. Four modes: bedrock_only, openai_only, bedrock_with_openai_fallback, openai_with_bedrock_fallback. Pipeline nodes call the gateway, not individual connectors. |

---

## AI Pipeline (Steps 7-9) — LangGraph State Machine

### Overview

File: `src/orchestration/graph.py` -> `build_pipeline_graph()`

The LangGraph orchestrator wires 10 real nodes + 1 placeholder (triage) into a StateGraph. The SQS consumer (`src/orchestration/sqs_consumer.py` -> `PipelineConsumer`) pulls messages from both intake queues and feeds them into the graph.

```
START → context_loading → query_analysis → confidence_check
    ─(processing_path=="C")─→ triage [STUB — Phase 5] → END
    ─(else)─→ routing → kb_search → path_decision
        ─(processing_path=="A")─→ resolution → quality_gate → delivery → END
        ─(processing_path=="B")─→ acknowledgment → quality_gate → delivery → END
```

### Step 7: Context Loading

File: `src/pipeline/nodes/context_loading.py` -> `ContextLoadingNode.execute(state)`

**Input:** PipelineState with unified_payload containing vendor_id
**Output:** `{vendor_context: dict, status: "ANALYZING"}`

1. Extract vendor_id from unified_payload
2. If no vendor_id → set vendor_context=None, return
3. Cache check: `postgres.cache_read("cache.vendor_cache", "vendor_id", vendor_id)`
   - Hit → build VendorProfile from cached data
   - Miss → `salesforce.find_vendor_by_id(vendor_id)` → build profile from SF data
   - Both fail → default BRONZE profile ("Unknown Vendor")
4. Load episodic memory: `postgres.fetch("SELECT ... FROM memory.episodic_memory WHERE vendor_id=$1 LIMIT 5")`
   - Non-critical: failure returns empty list, pipeline continues
5. Build VendorContext (frozen Pydantic model), write to state as dict via `model_dump()`

### Step 8: Query Analysis (LLM Call #1)

File: `src/pipeline/nodes/query_analysis.py` -> `QueryAnalysisNode.execute(state)`

**Input:** PipelineState with unified_payload and vendor_context
**Output:** `{analysis_result: dict}` containing intent, entities, urgency, sentiment, confidence, category

Uses 8-layer defense strategy:

| Layer | Name | What it does |
|-------|------|-------------|
| 1 | Input Validation | Empty body → safe fallback (confidence=0.3). Truncate body to 10000 chars. |
| 2 | Prompt Engineering | Render `query_analysis_v1.j2` via `PromptManager.render()` |
| 3 | LLM Call | `bedrock.llm_complete(prompt, system_prompt, temperature=0.1)` |
| 4 | Output Parsing | Extract first `{...}` block from response. Handle markdown fences and preamble text. |
| 5 | Pydantic Validation | Build AnalysisResult from parsed JSON + LLM metrics |
| 6 | Self-Correction | Send error back to Claude, ask it to fix its own response (1 retry) |
| 7 | Safe Fallback | AnalysisResult with confidence=0.3, intent=UNKNOWN → routes to Path C |
| 8 | Audit | structlog with all metrics |

### Decision Point 1: Confidence Check

File: `src/pipeline/nodes/confidence_check.py` -> `ConfidenceCheckNode.execute(state)`

- confidence >= 0.85 → continue to routing + KB search
- confidence < 0.85 → processing_path="C", status="PAUSED" (Path C)

### Step 9A: Routing (Deterministic Rules)

File: `src/pipeline/nodes/routing.py` -> `RoutingNode.execute(state)`

**Team assignment** by suggested_category:
- billing/invoice/payment → finance-ops
- delivery/shipping/logistics → supply-chain
- contract/agreement/terms/legal → legal-compliance
- technical/integration/api/product → tech-support
- default → general-support

**SLA calculation** by tier × urgency:
- PLATINUM base 4h, GOLD 8h, SILVER 16h, BRONZE 24h
- Multipliers: CRITICAL ×0.25, HIGH ×0.5, MEDIUM ×1.0, LOW ×1.5
- Example: GOLD + HIGH = 8h × 0.5 = 4h

### Step 9B: KB Search (Embed + pgvector)

File: `src/pipeline/nodes/kb_search.py` -> `KBSearchNode.execute(state)`

1. Build search text from subject + body (truncate to 2000 chars)
2. Embed via `bedrock.llm_embed(search_text)` → vector(1536)
3. pgvector cosine similarity query: `SELECT ... FROM memory.embedding_index WHERE is_active=true ORDER BY embedding <=> $1::vector LIMIT 5`
4. Compute best_match_score and has_sufficient_match (>= 0.80 threshold)
5. Error handling: embedding failure or DB timeout → empty result → forces Path B

### Decision Point 2: Path Decision

File: `src/pipeline/nodes/path_decision.py` -> `PathDecisionNode.execute(state)`

- has_sufficient_match=True AND top match content > 100 chars → processing_path="A" (Path A)
- Otherwise → processing_path="B", routing_decision.requires_human_investigation=True (Path B)
- Status set to "DRAFTING"

### Prompt Templates

File: `src/pipeline/prompts/prompt_manager.py` -> `PromptManager`

Jinja2 templates with StrictUndefined (raises on missing vars):
- `query_analysis_v1.j2` — LLM Call #1: intent, entities, confidence
- `resolution_v1.j2` — LLM Call #2 Path A: full answer from KB
- `acknowledgment_v1.j2` — LLM Call #2 Path B: acknowledgment only
- `resolution_from_notes_v1.j2` — LLM Call #3 Path B: resolution from team's notes

### SQS Consumer

File: `src/pipeline/consumer.py` -> `PipelineConsumer`

- `process_message(message)` — deserialize → build initial PipelineState → `graph.ainvoke()` → return result
- `start_consumer(queue_url)` — long-poll loop: receive → process → delete on success
- `consume_both_queues()` — `asyncio.gather` two consumers (email + query intake queues)
- On failure, message stays in queue for SQS retry (up to 3 times, then DLQ)

### Step 10A: Resolution — Path A (LLM Call #2)

File: `src/orchestration/nodes/resolution.py` -> `ResolutionNode.execute(state)`

**Input:** PipelineState with processing_path="A", vendor_context, analysis_result, kb_search_result, routing_decision
**Output:** `{draft_response: dict, status: "VALIDATING"}` or `{draft_response: None, status: "DRAFT_FAILED"}`

1. Extract vendor name, tier, KB articles, analysis entities, and routing SLA from state
2. Format KB articles for prompt (article_id, content_snippet, similarity_score)
3. Render `resolution_v1.j2` via PromptManager — includes vendor name, tier SLA statement, KB articles, entities, "PENDING" ticket placeholder
4. LLM Call #2: `llm_gateway.llm_complete(prompt, system_prompt, temperature=0.3)` — higher temperature than analysis for more natural email style
5. Parse JSON from response (3 strategies: direct parse, markdown fences, brace extraction)
6. Build DraftResponse: `draft_type="RESOLUTION"`, subject, body_html, confidence, sources (KB article IDs)
7. On LLM failure or parse failure → status="DRAFT_FAILED", draft_response=None

SLA statements by tier: PLATINUM (2-hour priority), GOLD (4-hour priority), SILVER (8-hour priority), BRONZE (24-hour standard).

### Step 10B: Acknowledgment — Path B (LLM Call #2)

File: `src/orchestration/nodes/acknowledgment.py` -> `AcknowledgmentNode.execute(state)`

**Input:** PipelineState with processing_path="B", vendor_context, analysis_result, routing_decision
**Output:** `{draft_response: dict, status: "VALIDATING"}` or `{draft_response: None, status: "DRAFT_FAILED"}`

1. Extract vendor name, tier, analysis intent, and assigned_team from state
2. Render `acknowledgment_v1.j2` via PromptManager — includes vendor name, tier SLA statement, assigned_team, "PENDING" ticket placeholder
3. LLM Call #2: `llm_gateway.llm_complete(prompt, system_prompt, temperature=0.3)`
4. Parse JSON from response (same 3 strategies as Resolution)
5. Build DraftResponse: `draft_type="ACKNOWLEDGMENT"`, subject, body_html, confidence, `sources=[]` (always empty — no KB facts used)
6. On failure → status="DRAFT_FAILED", draft_response=None

**Key difference from Resolution:** Acknowledgment NEVER contains an answer. It confirms receipt, gives the ticket number, states the SLA, and says the team is investigating.

### Step 11: Quality Gate (7 Deterministic Checks)

File: `src/orchestration/nodes/quality_gate.py` -> `QualityGateNode.execute(state)`

**Input:** PipelineState with draft_response and processing_path
**Output:** `{quality_gate_result: dict, status: "DELIVERING" | "DRAFT_REJECTED"}`

7 checks run on every outbound draft:

| # | Check | What it validates | Failure condition |
|---|-------|------------------|-------------------|
| 1 | Ticket number | "PENDING" or INC-XXXXXXX present in body | No ticket reference found |
| 2 | SLA wording | SLA-related keywords in body (prioritizing, service agreement, etc.) | No SLA language |
| 3 | Required sections | Greeting (Dear/Hello/Hi), next steps (next step/will/follow up), closing (regards/sincerely/thank you) | Missing any section |
| 4 | Restricted terms | 14 blocked terms: "internal only", "jira", "slack channel", "confluence", "do not share", "confidential internal", "meeting notes", "standup", "sprint", "backlog", "pagerduty", "grafana", "terraform", "kubectl" | Any restricted term found |
| 5 | Word count | 50-500 words | Below 50 or above 500 |
| 6 | Source citations | Non-empty sources list (Path A RESOLUTION only; skipped for Path B) | Path A with empty sources |
| 7 | PII scan | SSN pattern (XXX-XX-XXXX) and credit card (16 consecutive digits) | PII pattern detected |

Returns `QualityGateResult`: `{passed: bool, checks_run: 7, checks_passed: int, failed_checks: [str]}`.
- All pass → status="DELIVERING"
- Any fail → status="DRAFT_REJECTED" (orchestrator decides whether to re-draft or route to human review)

### Step 12: Delivery (ServiceNow Ticket + Graph API Email)

File: `src/orchestration/nodes/delivery.py` -> `DeliveryNode.execute(state)`

**Input:** PipelineState with draft_response, routing_decision, unified_payload, vendor_context, analysis_result
**Output:** `{ticket_info: dict | None, status: "RESOLVED" | "AWAITING_RESOLUTION" | "DELIVERY_FAILED"}`

3-phase execution:

| Phase | What it does | On failure |
|-------|-------------|------------|
| 1. Create ticket | `servicenow.create_ticket(TicketCreateRequest)` → INC-XXXXXXX | status="DELIVERY_FAILED", ticket_info=None, email NOT sent |
| 2. Replace placeholder | String replace "PENDING" → INC-XXXXXXX in subject and body_html | N/A (pure string operation) |
| 3. Send email | `graph_api.send_email(to, subject, body_html, reply_to_message_id)` | status="DELIVERY_FAILED", ticket_info still returned |

Path-specific behavior:
- **Path A (RESOLUTION):** Final status = "RESOLVED" — ticket is for monitoring only, vendor got the answer
- **Path B (ACKNOWLEDGMENT):** Final status = "AWAITING_RESOLUTION" — ticket is for investigation, human team must act

Edge cases:
- No sender_email (portal submissions) → email send skipped, ticket still created, success status returned
- Email source → `reply_to_message_id` from unified_payload passed to Graph API for thread continuation

### ServiceNow Connector

File: `src/adapters/servicenow.py` -> `ServiceNowConnector`

httpx.AsyncClient with basic auth. Lazy client initialization via `_get_client()`.

| Method | What it does |
|--------|-------------|
| `create_ticket(request)` | POST /api/now/table/incident → returns TicketInfo with INC number |
| `update_ticket_status(ticket_id, new_status)` | Find sys_id by number, PATCH /api/now/table/incident/{sys_id} |
| `get_ticket(ticket_id)` | Find sys_id by number, GET /api/now/table/incident/{sys_id} |
| `get_work_notes(ticket_id)` | GET /api/now/table/sys_journal_field?element=work_notes&element_id={sys_id} |
| `close()` | Close httpx client |

Priority mapping: CRITICAL→1, HIGH→2, MEDIUM→3, LOW→4.

### Dependency Injection

File: `src/orchestration/dependencies.py` -> `create_pipeline(settings, postgres, llm_gateway, salesforce, sqs, servicenow, graph_api)`

Instantiates all 10 pipeline nodes (injecting LLMGateway into query_analysis, kb_search, resolution, acknowledgment; ServiceNow + Graph API into delivery), builds the graph via `build_pipeline_graph()`, creates the consumer. Returns `(compiled_graph, pipeline_consumer)`. Called from `main.py` lifespan.

---

## Application Startup

File: `main.py` (project root) -> `lifespan(app)`

1. Load settings from `.env`
2. Create and connect PostgresConnector (SSH tunnel + asyncpg pool)
3. Initialize AuthService with PostgresConnector
4. Create SalesforceConnector (lazy init — no connection at startup)
5. Create S3Connector, SQSConnector, EventBridgeConnector
6. Create LLMGateway (wraps BedrockConnector primary + OpenAIConnector fallback)
7. Create GraphAPIConnector (httpx + MSAL, lazy init)
8. Create ServiceNowConnector (httpx + basic auth, lazy client init)
9. Build PortalIntakeService with postgres + sqs + eventbridge
10. Build EmailDashboardService with postgres + s3 + settings (read-only)
11. Store everything on `app.state`
12. On shutdown: close ServiceNow httpx client, close Graph API httpx client, disconnect PostgreSQL

---

## Email Dashboard API (Read-Only)

File: `src/dashboard/routes.py` + `src/dashboard/service.py`

Read-only endpoints serving email data for the frontend dashboard. Groups emails into conversation threads using `conversation_id` from Graph API. Falls back to `query_id` for standalone emails.

| Endpoint | What it does |
|----------|-------------|
| `GET /emails` | Paginated list of email chains. Filters: status (New/Reopened/Resolved), priority (High/Medium/Low), search (ILIKE on subject/sender). Sort by timestamp/status/priority. Uses 4-query pattern: count → thread keys → emails → attachments (no N+1). |
| `GET /emails/stats` | Aggregate counts: total, by status category, by priority, today, this week. Single-pass query with `COUNT(*) FILTER`. |
| `GET /emails/{query_id}` | Single email chain. If conversation_id exists, returns full thread. Batch-fetches attachments. |
| `GET /emails/{query_id}/attachments/{attachment_id}/download` | Presigned S3 URL (1-hour expiry) via `S3Connector.generate_presigned_url()`. |

Status mapping: DB `RECEIVED/ANALYZING/ROUTING/...` → `"New"`, `REOPENED` → `"Reopened"`, `RESOLVED/CLOSED` → `"Resolved"`.
Priority mapping: `routing_decision.priority` → `"High"/"Medium"/"Low"` (default `"Medium"` when routing hasn't run).

---

## Authentication Flow (JWT)

### Login: `POST /auth/login`

File: `src/api/routes/auth.py` -> `login()`

**Input:** `LoginRequest` (from `src/models/auth.py`) — `username_or_email`, `password`
**Output:** `LoginResponse` — `token`, `user_name`, `email`, `role`, `tenant`, `vendor_id`

| Step | Code | What it does |
|------|------|-------------|
| 1 | `authenticate_user(username_or_email, password)` | Calls `src/services/auth.py` -> `authenticate_user()` |
| 2 | `pg.fetchrow("SELECT ... FROM public.tbl_users WHERE ...")` | User lookup by username or email |
| 3 | `check_password_hash(user.password, password)` | Verify password via werkzeug (runs in `asyncio.to_thread`) |
| 4 | `pg.fetchrow("SELECT ... FROM public.tbl_user_roles WHERE ...")` | Role lookup for the user |
| 5 | `create_access_token(user_name, role, tenant)` | Generate JWT with `python-jose` (HMAC-SHA256, 30-min expiry) |
| 6 | Return `LoginResponse` | Token + user details returned to client |

### Logout: `POST /auth/logout`

File: `src/api/routes/auth.py` -> `logout()`

**Input:** Bearer token in Authorization header
**Output:** `{"detail": "Logged out"}`

| Step | Code | What it does |
|------|------|-------------|
| 1 | Extract token from `Authorization: Bearer <token>` header | |
| 2 | `blacklist_token(token)` | Decode JWT, extract JTI, store `vqms:auth:blacklist:{jti}` in `cache.kv_store` with 30-min TTL |

### Middleware: `AuthMiddleware`

File: `src/api/middleware/auth_middleware.py`

Applied to every request. Skip paths: `/health`, `/auth/login`, `/docs`, `/openapi.json`, `/redoc`, `/webhooks/`.

| Step | Code | What it does |
|------|------|-------------|
| 1 | Check if path is in skip list | If yes, pass through without auth |
| 2 | Extract `Authorization: Bearer <token>` | If missing, return 401 |
| 3 | `validate_token(token)` | Decode JWT, check expiry, check blacklist in `cache.kv_store` |
| 4 | Populate `request.state` | Sets `username`, `role`, `tenant`, `is_authenticated` |
| 5 | `refresh_token_if_expiring(payload)` | If token expires within 300s, generate new token, add `X-New-Token` response header |

---

## Vendor CRUD Flow

### List Vendors: `GET /vendors`

File: `src/api/routes/vendors.py` -> `get_all_vendors()`

**Input:** Bearer JWT (authenticated request)
**Output:** List of vendor account dicts from Salesforce

| Step | Code | What it does |
|------|------|-------------|
| 1 | `request.app.state.salesforce.get_all_active_vendors()` | Queries Salesforce Account object (SOQL), returns cleaned list of active vendors with standard + custom fields |

### Update Vendor: `PUT /vendors/{vendor_id}`

File: `src/api/routes/vendors.py` -> `update_vendor()`

**Input:** `VendorUpdateRequest` (from `src/models/vendor.py`) — at least one updatable field
**Output:** `VendorUpdateResult` — `success`, `vendor_id`, `updated_fields`

| Step | Code | What it does |
|------|------|-------------|
| 1 | `body.to_salesforce_fields()` | Convert Pydantic model to Salesforce field names (e.g., `website` → `Website`) |
| 2 | `request.app.state.salesforce.update_vendor_account(vendor_id, sf_fields)` | Find Account by `Vendor_ID__c`, apply updates via simple-salesforce |

---

## What is not built yet

- Path C — Human review triage portal + workflow pause/resume (Phase 5)
- SLA monitoring and closure/reopen logic (Phase 6)
- Angular frontend portal — triage portal, admin dashboard (Phase 7)
- Path B resolution from team's work notes (Step 15 — Phase 6)
- PII detection via Amazon Comprehend (Quality Gate stub exists, Phase 8)
- Integration testing and hardening (Phase 8)
