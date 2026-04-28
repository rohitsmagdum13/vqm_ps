# VQMS — End-to-End Runtime Walkthrough

_This file traces exactly how a vendor query moves through the codebase. Updated after every phase._

## Current State: Phase 5 — Human Review and Path C (Complete)

Phases 1-5 are complete. Both entry points produce messages on SQS. The LangGraph pipeline consumes them, runs query analysis (LLM Call #1), confidence gating, routing, KB search, path decision, response drafting (LLM Call #2), quality gate validation, ServiceNow ticket creation, and email delivery. Low-confidence queries now route to Path C: the triage node persists a TriagePackage, PAUSES the workflow, and publishes HumanReviewRequired. A human reviewer submits corrections via `/triage/{id}/review`, which re-enqueues the query onto `sqs_query_intake_queue_url` with `resume_context.from_triage=True` so the standard pipeline restarts from context_loading with high confidence. All 11 pipeline nodes are real (no placeholders). 408 tests pass (3 unrelated pre-existing failures in portal_intake and queries routes).

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
| E1 | `self._graph_api.fetch_email(message_id)` | YES | GET /users/{mailbox}/messages/{id}?$expand=attachments (Graph $filter also excludes Automatic reply / Out of office / Undeliverable / Delivery Status Notification / Mail Delivery Failure subjects — see `adapters/graph_api/email_fetch.py:UNREAD_FILTER`) |
| E2.2 | `EmailParser.parse_email_fields(raw_email)` | YES | Extract sender, recipients, subject, body, headers, conversationId |
| E2.2a | `self._vendor_identifier.identify(parsed)` | no | Salesforce 3-step fallback: exact email → body extraction → fuzzy name. **Moved ahead of the filter so the sender allowlist can use the result.** |
| E2.2b | `self._relevance_filter.evaluate(parsed, raw_email, vendor_id, ...)` | YES | 4-layer drop of obvious noise BEFORE any storage or SQS work — sender allowlist → content sanity (length + noise words + Auto-Submitted / List-Unsubscribe / Precedence headers) → optional Haiku classifier. If `accept=False`, pipeline stops early — see "Email Relevance Filter" below. |
| E2.7 | `IdGenerator.generate_query_id()` / `generate_execution_id()` | YES | Generate VQ-2026-XXXX and UUID v4 |
| E2.3 | `self._store_raw_email(raw_email, query_id)` | no | Upload raw JSON to S3 `inbound-emails/{query_id}/raw_email.json` (single bucket: vqms-data-store) |
| E2.4 | `self._process_attachments(raw_email, query_id)` | no | Validate → store to S3 `attachments/{query_id}/{att_id}_{filename}` → extract text → store `_manifest.json` |
| E2.6 | `self._determine_thread_status(raw_email)` | no | Check conversationId in workflow.case_execution → NEW / EXISTING_OPEN / REPLY_TO_CLOSED |
| E2.8 | `self._store_email_metadata(...)` + `self._create_case_execution(...)` | YES | INSERT into intake.email_messages + workflow.case_execution |
| E2.9a | `self._eventbridge.publish_event("EmailParsed", ...)` | no | Publish audit event |
| E2.9b | `self._sqs.send_message(queue_url, payload)` | YES | Enqueue UnifiedQueryPayload to vqms-email-intake-queue |

**Critical steps** propagate errors (SQS retries). **Non-critical steps** log warnings and continue with safe defaults (None, empty list, "NEW").

### Email Relevance Filter (Step E2.2b)

File: `src/services/email_intake/relevance_filter.py` → `EmailRelevanceFilter.evaluate()`

Purpose: drop obvious noise (hello-only messages, out-of-office auto-replies, unknown senders, newsletters) BEFORE the email ever reaches the expensive Bedrock pipeline. A 4-layer chain, cheapest first.

| Layer | Check | Action on fail |
|-------|-------|----------------|
| 0 (Graph) | `$filter` at `list_unread_messages` excludes auto-reply subjects server-side | Email never fetched |
| 1 (sender_allowlist) | If vendor is `UNRESOLVED` AND sender domain not in `email_filter_allowed_sender_domains` | `auto_reply_ask_details` — send polite "please register" note once, mark read |
| 2 (content_sanity) | Combined subject+body (quoted-reply stripped) < `email_filter_min_chars` chars, OR matches noise pattern alone, OR headers include `Auto-Submitted`, `X-Auto-Response-Suppress`, `List-Unsubscribe`, or `Precedence: bulk/list/junk`, OR subject starts with auto-reply prefix | `drop` silently, or `thread_only` for empty `RE:` replies |
| 3 (llm_classifier) | Only when `email_filter_use_llm_classifier=true` AND content length is borderline (30–200 chars). One Haiku call with temperature 0 returns `{is_query, reason}`. Fails OPEN on any error. | `auto_reply_ask_details` |

Returns `RelevanceDecision(accept, reason, action, layer)` from `src/models/email.py`.

When `accept=False`, `EmailIntakeService._handle_rejected_email()` logs the rejection with `tool="email_intake"` and, for `auto_reply_ask_details`, sends a one-line reply asking for more detail via `graph_api.send_email`. No SQS enqueue. No downstream cost.

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
| ServiceNowConnector | `src/adapters/servicenow/` (folder module: client + ticket_create + ticket_query mixins) | httpx.AsyncClient with lazy init, basic auth. `create_ticket` posts with `sysparm_input_display_value=true` and includes state/priority/impact/urgency/caller_id/due_date/work_notes + u_* custom fields. `resolve_user_display_name` (admin → "System Administrator") puts tickets in the Self Service view. `resolve_group_name` + `status_to_state`/`state_to_status` helpers. See **ServiceNow Connector** section below for the full payload spec. |
| BedrockConnector | `src/adapters/bedrock.py` | LLM inference (Claude Sonnet 3.5 via Messages API) + embeddings (Titan Embed v2, 1536 dims). Retry with tenacity on ThrottlingException/ServiceUnavailableException. Cost tracking per call. |
| OpenAIConnector | `src/adapters/openai_llm.py` | OpenAI Chat Completions (GPT-4o) + Embeddings (text-embedding-3-small). Retry with tenacity on RateLimitError/APIConnectionError/APITimeoutError. Cost tracking per call. Used as fallback behind LLM Gateway. |
| LLMGateway | `src/adapters/llm_gateway.py` | Unified LLM gateway. Routes `llm_complete()` and `llm_embed()` to Bedrock (primary) or OpenAI (fallback) based on `llm_provider` setting. Four modes: bedrock_only, openai_only, bedrock_with_openai_fallback, openai_with_bedrock_fallback. Pipeline nodes call the gateway, not individual connectors. |

---

## AI Pipeline (Steps 7-9) — LangGraph State Machine

### Overview

File: `src/orchestration/graph.py` -> `build_pipeline_graph()`

The LangGraph orchestrator wires 11 real nodes into a StateGraph. The SQS consumer (`src/orchestration/sqs_consumer.py` -> `PipelineConsumer`) pulls messages from both intake queues and feeds them into the graph.

```
START → context_loading → query_analysis → confidence_check
    ─(processing_path=="C")─→ triage → END (workflow PAUSED, resumed via reviewer API)
    ─(else)─→ routing → kb_search → path_decision
        ─(processing_path=="A")─→ resolution → quality_gate → delivery → END
        ─(processing_path=="B")─→ acknowledgment → quality_gate → delivery → END
```

### Step 7: Context Loading

File: `src/orchestration/nodes/context_loading.py` -> `ContextLoadingNode.execute(state)`

**Input:** PipelineState with unified_payload containing vendor_id
**Output:** `{vendor_context: dict, status: "ANALYZING"}`

1. Extract vendor_id from unified_payload
2. If no vendor_id → set vendor_context=None, return
3. Cache check: `postgres.cache_read("cache.vendor_cache", "vendor_id", vendor_id)`
   - Hit → `_build_vendor_profile(row)` reads top-level columns (`vendor_name`, `vendor_tier`, `vendor_category`) and falls back to the JSONB `cache_data` blob for any missing field.
   - Miss → `salesforce.find_vendor_by_id(vendor_id)` SOQL selects `Id, Name, Vendor_ID__c, Website__c, Vendor_Tier__c, Category__c, City__c`. `_build_vendor_profile_from_salesforce(record, vendor_id)` produces a `VendorProfile` carrying `vendor_category` (the Salesforce `Category__c` value).
   - On a cache miss, `_write_vendor_cache(profile, correlation_id)` does an UPSERT into `cache.vendor_cache` populating `cache_data` (full profile JSONB) plus dedicated `vendor_name`, `vendor_tier`, `vendor_category` columns with a 1-hour TTL. This is non-critical — a write failure is logged but never blocks the pipeline.
   - Both fail → default BRONZE profile ("Unknown Vendor", `vendor_category=None`)
4. Load episodic memory: `postgres.fetch("SELECT ... FROM memory.episodic_memory WHERE vendor_id=$1 LIMIT 5")`
   - Non-critical: failure returns empty list, pipeline continues
5. Build VendorContext (frozen Pydantic model), write to state as dict via `model_dump()`. Downstream nodes read `state["vendor_context"]["vendor_profile"]["vendor_category"]`.

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

File: `src/orchestration/nodes/routing.py` -> `RoutingNode.execute(state)`, `resolve_assignment_group(intent, vendor_category)`

**Team assignment** uses primary → secondary → fallback rules. The LLM's `suggested_category` is trusted only when it matches the canonical taxonomy in `VALID_ASSIGNMENT_GROUPS`; otherwise the deterministic resolver runs.

**Primary routing (intent alone):**
- INVOICE_PAYMENT → `Vendor Finance – AP & Invoicing`
- COMPLIANCE_AUDIT → `Vendor Compliance & Audit`
- GENERAL_INQUIRY → `Vendor Support`

**Secondary routing (vendor_category + eligible intent):**
- IT Services + {TECHNICAL_SUPPORT, SLA_BREACH_REPORT, DELIVERY_SHIPMENT, CONTRACT_QUERY} → `Vendor IT Services`
- Telecom / Security — same eligible intents → `Vendor Telecom Services` / `Vendor Security Services`
- Raw Materials / Manufacturing / Office Supplies + {PURCHASE_ORDER, CONTRACT_QUERY, CATALOG_PRICING, RETURN_REFUND} → `Vendor Procurement – {category}`
- Facilities / Logistics + {DELIVERY_SHIPMENT, QUALITY_ISSUE, SLA_BREACH_REPORT} → `Vendor Facilities Management` / `Vendor Logistics Management`
- Professional Services / Consulting + {CONTRACT_QUERY, SLA_BREACH_REPORT, QUALITY_ISSUE, ONBOARDING} → `Vendor Professional Services` / `Vendor Consulting Services`

**Fallback:** Anything unmatched (including `vendor_category=None`) → `Vendor Support`.

`RoutingDecision.assigned_team` is one of these 13 group names; ServiceNow's `assignment_group` is set to the same string. `routing_reason` records both the intent and the vendor_category that produced the decision.

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

Folder module: `src/adapters/servicenow/` -> `ServiceNowConnector` (mixin composition).

| File | Responsibility |
|------|----------------|
| `client.py` | `ServiceNowClient` base — lazy httpx.AsyncClient with basic auth, URL builder (accepts `SERVICENOW_INSTANCE_URL` full URL or `SERVICENOW_INSTANCE_NAME` short name), per-process caches for `sys_user_group` and `sys_user` lookups, `resolve_group_name(name)`, `resolve_user_display_name(user_name)`, `status_to_state` / `state_to_status` mappings |
| `ticket_create.py` | `TicketCreateMixin.create_ticket(request)` — builds and POSTs the incident payload |
| `ticket_query.py` | `TicketQueryMixin` — `get_ticket`, `get_work_notes`, `update_ticket_status` |

| Method | What it does |
|--------|-------------|
| `create_ticket(request)` | POST /api/now/table/incident with `sysparm_input_display_value=true` → returns TicketInfo with INC number |
| `update_ticket_status(ticket_id, new_status)` | Find sys_id by number, PATCH /api/now/table/incident/{sys_id} |
| `get_ticket(ticket_id)` | Find sys_id by number, GET /api/now/table/incident/{sys_id} |
| `get_work_notes(ticket_id)` | GET /api/now/table/sys_journal_field?element=work_notes&element_id={sys_id} |
| `resolve_user_display_name(user_name)` | GET /api/now/table/sys_user?user_name=... → returns `name` field (e.g. "admin" → "System Administrator"). Cached per process. |
| `resolve_group_name(name)` | GET /api/now/table/sys_user_group?name=... → returns `name` if the group exists, else "". Cached per process. |
| `close()` | Close httpx client |

**Priority mapping** (VQMS → ServiceNow numeric): CRITICAL→1, HIGH→2, MEDIUM→3, LOW→4. ServiceNow also derives Priority from an Impact × Urgency matrix, so the payload includes both:

| VQMS priority | ServiceNow priority | impact | urgency |
|---------------|--------------------|--------|---------|
| CRITICAL | 1 | 1 (High) | 1 (High) |
| HIGH | 2 | 2 (Medium) | 1 (High) |
| MEDIUM | 3 | 2 (Medium) | 2 (Medium) |
| LOW | 4 | 3 (Low) | 2 (Medium) |

**Incident payload built by `create_ticket` (UI-visibility tuned):**

| Field | Source / rule |
|-------|---------------|
| `short_description` | `request.subject` |
| `description` | `request.description` |
| `category` | `request.category` (falls back to ServiceNow default "Inquiry" if not in the choice list) |
| `priority` | `PRIORITY_MAP[request.priority]` |
| `impact`, `urgency` | `IMPACT_URGENCY_MAP[request.priority]` — populates the widgets & SLA filters that read these columns |
| `state` | `"1"` (New) — every VQMS-created ticket starts here |
| `assignment_group` | Raw pass-through of `request.assigned_team`. No fallback — if the VQMS routing group doesn't exist in `sys_user_group`, the reference stays unresolved but the ticket still appears under **Incident → All** |
| `caller_id` | `resolve_user_display_name(settings.servicenow_username)` — resolves "admin" → "System Administrator" so the ticket shows up under the default **Self Service** view (`Caller = <logged-in user>`) |
| `contact_type` | `"email"` |
| `due_date` | `sla_deadline.strftime("%Y-%m-%d %H:%M:%S")` — lets ServiceNow's built-in "Overdue" filter work without configuring a ServiceNow SLA definition |
| `work_notes` | One-line VQMS provenance breadcrumb — `"Created by VQMS\n- query_id: ... \n- correlation_id: ... \n- vendor: ... \n- priority: ... (SLA Xh, deadline ...)\n- routed team: ..."` — visible on the Activity log, invisible to the caller |
| `u_query_id` | `request.query_id` (VQ-YYYY-NNNN) |
| `u_correlation_id` | `request.correlation_id` — cross-references back to VQMS logs |
| `u_vendor_id`, `u_vendor_name` | From VQMS routing |
| `u_sla_hours`, `u_sla_deadline` | SLA target hours + IST deadline timestamp |

`sysparm_input_display_value=true` on the POST means reference fields (`assignment_group`, `caller_id`, `category`) are resolved by their human-readable display name — we don't have to pre-lookup sys_ids for every routing choice VQMS might make.

The `u_*` custom fields are silently dropped by ServiceNow PDIs that don't have those columns on the incident dictionary yet. They appear in the payload so they're ready once the dictionary entries are created via `sys_dictionary` / Studio.

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
| `GET /emails` | Paginated list of email chains. Filters: status (New/Reopened/Resolved), priority (High/Medium/Low), search (ILIKE on subject/sender). Sort by timestamp/status/priority. Uses 4-query pattern: count → thread keys → emails → attachments (no N+1). Each `AttachmentSummary` includes an inline presigned `download_url` (1h) so the admin portal can render direct download links without a second API call. |
| `GET /emails/stats` | Aggregate counts: total, by status category, by priority, today, this week. Single-pass query with `COUNT(*) FILTER`. |
| `GET /emails/{query_id}` | Single email chain. If conversation_id exists, returns full thread. Batch-fetches attachments with inline presigned `download_url` per attachment. |
| `GET /emails/{query_id}/attachments/{attachment_id}/download` | On-demand presigned S3 URL (1-hour expiry) via `S3Connector.generate_presigned_url()`. Kept as a fallback for refreshing a single expired URL. |

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

## Path C — Low-Confidence Human Review (Steps 8C.1 → 8C.3)

When Query Analysis confidence is < 0.85, the pipeline pauses for a human reviewer to correct the AI's interpretation before any ticket is created or email is sent. Path C is **workflow-preserving**: the reviewer's corrections re-enter the standard pipeline, so Path A / Path B decisions happen exactly like they would on a high-confidence query.

### Step 8C.1: Triage Node — persist and pause

File: `src/orchestration/nodes/triage.py` -> `TriageNode.execute(state)`

**Input:** PipelineState with `analysis_result.confidence_score < 0.85`
**Output:** `{triage_package: dict, status: "PAUSED", updated_at}`

| Step | Code | What it does |
|------|------|-------------|
| 1 | `IdGenerator.generate_correlation_id()` | Generate `callback_token` (UUID) — the resume handle |
| 2 | `_build_confidence_breakdown()` | Decompose overall confidence into intent / entity / single-issue heuristics so the reviewer sees where the AI was weak |
| 3 | Build `TriagePackage` dict | Combines original_query + analysis_result + suggested_routing (may be None) + confidence_breakdown + callback_token |
| 4 | `postgres.execute(INSERT ... ON CONFLICT DO NOTHING)` into `workflow.triage_packages` | **Critical** — failure propagates, SQS retries, eventually DLQ |
| 5 | `postgres.execute(UPDATE workflow.case_execution SET status='PAUSED', processing_path='C')` | Mark the case paused |
| 6 | `eventbridge.publish_event("HumanReviewRequired", ...)` | **Non-critical** — logged warning on failure, pipeline continues |
| 7 | Return state update with `status="PAUSED"` | StateGraph terminates at this node for Path C |

### Step 8C.2: Reviewer Queue & Detail (GET endpoints)

File: `src/api/routes/triage.py` -> `list_triage_queue()`, `get_triage_package()`

**Auth:** Bearer JWT. `_require_reviewer(request)` rejects with 403 unless role ∈ {REVIEWER, ADMIN} (extracted from `request.state.role`).

| Endpoint | Handler | Service call | Response |
|----------|---------|--------------|----------|
| `GET /triage/queue?limit=50` | `list_triage_queue` | `triage_service.list_pending(limit)` — reads `workflow.triage_packages WHERE status='PENDING' ORDER BY created_at ASC`, limit clamped to [1, 200] | `{"packages": [TriageQueueItem, ...]}` |
| `GET /triage/{query_id}` | `get_triage_package` | `triage_service.get_package(query_id)` — returns full TriagePackage. `TriagePackageNotFoundError` → 404 | `TriagePackage` JSON |

### Step 8C.3: Reviewer Decision & Workflow Resume

File: `src/api/routes/triage.py` -> `submit_triage_review()` + `src/services/triage.py` -> `TriageService.submit_decision()`

**Auth:** Same reviewer guard. **Security invariant:** `reviewer_id` is always taken from `request.state.username` (JWT sub claim), NEVER from the request body — matches the vendor_id rule.

**Input:** `ReviewerDecisionRequest` — `corrected_intent?`, `corrected_vendor_id?`, `corrected_routing?`, `confidence_override? ∈ [0.0, 1.0]`, `reviewer_notes` (min_length=1)

| Step | Code | What it does |
|------|------|-------------|
| 1 | `postgres.fetchrow("SELECT status FROM workflow.triage_packages WHERE query_id=$1")` | Verify row exists (`TriagePackageNotFoundError` → 404) and status is PENDING (`TriageAlreadyReviewedError` → 409) |
| 2 | `postgres.execute(INSERT INTO workflow.reviewer_decisions ...)` | **Audit trail first** — decision row is always written, even if downstream resume fails |
| 3 | `postgres.execute(UPDATE workflow.triage_packages SET status='REVIEWED', reviewed_at, reviewed_by)` | Flip package state |
| 4 | `_apply_corrections(analysis_result, decision)` | Build a **new** dict from analysis_result (no mutation), apply corrected_intent / corrected_vendor_id, set `confidence_score` to `decision.confidence_override` or `1.0`, stamp `human_validated=True` and `reviewer_id` |
| 5 | `postgres.execute(UPDATE workflow.case_execution SET analysis_result=$1, status='ANALYZED')` | Persist corrected analysis back into the case |
| 6 | `_reenqueue(query_id, corrected_analysis, correlation_id)` | Send SQS message to `sqs_query_intake_queue_url` with `resume_context={"from_triage": True, "reviewer_id": ..., "callback_token": ...}` and `corrected_analysis` payload. Falls back to `resume_method="db_only"` when SQS is None or `send_message` raises |
| 7 | `eventbridge.publish_event("HumanReviewCompleted", ...)` | **Non-critical** |

**Response:** `{status: "REVIEWED", query_id, resume_method: "sqs" | "db_only"}`

**On resume:** The SQS consumer picks up the corrected-analysis message and re-enters `context_loading`. Because `confidence_score` is now 1.0 (or the reviewer's override), `confidence_check` sends the query down the standard routing + kb_search branch, naturally flowing into Path A or Path B based on KB match quality. The reviewer's decision therefore acts exactly like a high-confidence result from the AI — no parallel "reviewed" branch exists in the graph.

**SLA note (Phase 6 will enforce):** The SLA clock starts AFTER review completes, not at query receipt. Review time does not count against SLA.

### Data model (migration 011)

`src/db/migrations/011_create_triage_tables.sql` creates:

- `workflow.triage_packages` — `query_id UNIQUE`, `callback_token UNIQUE`, `package_data JSONB`, `status`, `original_confidence`, `suggested_category`, `created_at`, `reviewed_at`, `reviewed_by`
- `workflow.reviewer_decisions` — `query_id`, `reviewer_id`, `decision_data JSONB`, `corrected_intent`, `corrected_vendor_id`, `confidence_override`, `reviewer_notes`, `decided_at`
- Indexes: `idx_triage_status_created`, `idx_triage_callback_token`, `idx_reviewer_decisions_query`, `idx_reviewer_decisions_reviewer`

---

## Phase 6 — SLA Monitoring, Path B Resolution, Closure

Phase 6 closes the gap on *time* and *closure*. Phase 5 made sure low-confidence queries get a human review before drafting. Phase 6 makes sure every case either resolves on time or gets escalated, and every closed case feeds future queries via episodic memory.

### Step 13: SLA Monitor — background tick loop

File: `src/services/sla_monitor.py` -> `SlaMonitor.tick()`

**What triggers it:** `app/lifespan.py` starts `SlaMonitor` on FastAPI startup. The service runs `tick()` every `settings.sla_monitor_interval_seconds` (default 60s) via an asyncio task loop. Graceful shutdown on `CancelledError`.

**Input:** None — reads `workflow.sla_checkpoints` directly
**Output:** Publishes `SLAWarning70` / `SLAEscalation85` / `SLAEscalation95` events, flips flags in `workflow.sla_checkpoints`

| Step | Code | What it does |
|------|------|-------------|
| 1 | Checkpoint row was INSERTed by `RoutingNode.execute()` at Step 9A — every case with an SLA target writes a `workflow.sla_checkpoints` row with `sla_deadline = ist_now() + sla_target_hours`, `warning_fired=false`, `l1_fired=false`, `l2_fired=false`, `last_status=ACTIVE` | Non-critical in routing — if this write fails, routing continues; SLA monitor will simply not see the case |
| 2 | `postgres.fetch("SELECT * FROM workflow.sla_checkpoints WHERE last_status = 'ACTIVE' AND sla_deadline IS NOT NULL")` | Active cases only. A case becomes INACTIVE when ClosureService marks it CLOSED |
| 3 | For each row: compute `elapsed_pct = (now - sla_started_at) / (sla_deadline - sla_started_at) * 100` | Raw elapsed percentage, capped at 100 |
| 4 | Threshold checks (ordered): `elapsed_pct >= 95 and not l2_fired` → publish `SLAEscalation95`, UPDATE `l2_fired=true`. Same for L1 (85%) and WARNING (70%) | Each threshold is its own event. Publishing is **non-critical** — if EventBridge fails the flag is NOT flipped so the next tick retries |
| 5 | `eventbridge.publish_event(event_type, payload={query_id, sla_deadline, elapsed_pct, ...})` | Event published, downstream consumers (dashboards, escalation routing) react |

**Idempotency:** Column-flag driven — once a flag is TRUE, that threshold will not re-fire for this case. `warning_fired`, `l1_fired`, `l2_fired` are boolean flags that only flip once.

**Analytics projection:** `reporting.sla_metrics` continues to store the wide analytics row. `workflow.sla_checkpoints` is the live scheduler state only.

### Step 15: Path B Resolution from ServiceNow Notes

When the human team finishes investigating a Path B ticket, ServiceNow hits our webhook, we fetch the team's work notes, and the Communication Agent drafts a resolution email from those notes. The key trick: we re-enter the existing LangGraph pipeline at a new branch rather than building a second pipeline.

#### Step 15.1: ServiceNow webhook receiver

File: `src/api/routes/webhooks.py` -> `servicenow_webhook()`

**Auth:** `/webhooks/` in middleware `SKIP_PATHS` — no JWT required (ServiceNow can't send Bearer tokens)
**Input:** `ServiceNowWebhookPayload` — `ticket_id` (required), `status` (required), `correlation_id` (optional)
**Output:** `{status: "enqueued" | "ignored" | "error", query_id?, reason?}`

| Step | Code | What it does |
|------|------|-------------|
| 1 | `status.upper()` → only process `"RESOLVED"` | Any other status returns `{"status": "ignored"}` with reason |
| 2 | `postgres.fetchrow("SELECT query_id FROM workflow.ticket_link WHERE ticket_number = $1")` | Map ServiceNow INC to our query_id. Missing → `{"status": "error", "reason": "ticket_not_found"}` |
| 3 | `postgres.fetchrow("SELECT query_id, correlation_id, execution_id, source, analysis_result, vendor_id FROM workflow.case_execution WHERE query_id = $1")` | Pull the case's stable correlation_id (overrides webhook payload's if present) |
| 4 | Build `resume_message`: `{query_id, vendor_id, correlation_id, execution_id, source, resume_context: {action: "prepare_resolution", from_servicenow: True, ticket_id}, analysis_result}` | Uses the case's original correlation_id for trace continuity |
| 5 | `sqs.send_message(settings.sqs_query_intake_queue_url, resume_message, correlation_id=...)` | Re-enter the pipeline via the intake queue. Missing queue URL → `{"status": "error"}` (no 500) |

#### Step 15.2: Graph entry-switch routes resume-message to resolution-from-notes branch

File: `src/orchestration/graph.py` -> `route_from_entry(state)` + `build_pipeline_graph()`

The graph has a tiny passthrough entry node that reads `state["resume_context"]` and picks the branch:

- `resume_context.action == "prepare_resolution"` → skip intake nodes entirely, jump to `resolution_from_notes`
- else (including missing resume_context, triage resume, or first-time new query) → normal path into `context_loading`

The resolution branch path: `entry → resolution_from_notes → quality_gate → delivery → END`. `kb_search`, `routing`, `resolution`, `acknowledgment`, `triage`, and `context_loading` are all skipped — the analysis_result and vendor_context were already computed on the original pass.

#### Step 15.3: ResolutionFromNotesNode — draft resolution from work notes

File: `src/orchestration/nodes/resolution_from_notes.py` -> `ResolutionFromNotesNode.execute(state)`

**Input:** PipelineState with `ticket_info.ticket_number`, `vendor_context`, `unified_payload`, `analysis_result`, `resume_context.action=prepare_resolution`
**Output:** `{draft_response: DraftResponse, work_notes: str, status: "VALIDATING", updated_at}` on success OR `{draft_response: None, status: "DRAFT_FAILED", error, updated_at}` on failure

| Step | Code | What it does |
|------|------|-------------|
| 1 | Read `ticket_info.ticket_number` — missing → DRAFT_FAILED with "missing_ticket_number" | Early return, no ServiceNow / LLM calls |
| 2 | `servicenow.get_work_notes(ticket_number)` wrapped in try/except | **Non-critical** — on failure, `work_notes = "No investigation notes were provided."` so the LLM still produces a reasonable draft |
| 3 | Build prompt variables: `vendor_name`, `vendor_tier` (drives `SLA_STATEMENTS` → `"Our Gold-tier team has completed the investigation..."` for GOLD), `intent`, `subject`, `ticket_number`, `work_notes` | Tier-aware phrasing (PLATINUM / GOLD / SILVER / BRONZE) |
| 4 | `prompt_manager.render("resolution_from_notes_v1", **vars)` | Jinja2 StrictUndefined — any missing var raises |
| 5 | `llm_gateway.llm_complete(prompt, temperature=0.3)` wrapped in try/except | LLM failure → DRAFT_FAILED; no retry here (LLM Gateway already has retry) |
| 6 | Parse JSON response → `DraftResponse` (subject, body_html, confidence, sources) | JSON parse or Pydantic validation failure → DRAFT_FAILED |
| 7 | Return `{draft_response, work_notes, status: "VALIDATING", updated_at: ist_now()}` | Hand off to Quality Gate |

#### Step 15.4: Quality Gate + Delivery — reuse existing ticket

The Quality Gate runs the same 7 checks (it doesn't care whether we're first-send or resolution-from-notes). Delivery branches on `state.get("resolution_mode")`:

| Condition | What delivery does |
|-----------|---------------------|
| `resolution_mode` truthy (Step 15) | SKIP `_create_ticket()` — reuse `ticket_info.ticket_number` from state; call `servicenow.update_ticket_status(ticket_id, "AWAITING_VENDOR_CONFIRMATION", work_notes=...)`; publish `ResolutionPrepared`; send email to `vendor_context.email_address` (portal-origin queries have no `unified_payload.sender_email`); then call `closure_service.register_resolution_sent(query_id, correlation_id)` to start the 5-business-day auto-close timer |
| First send (Path A or Path B ack) | Unchanged — create ticket, send email, then `register_resolution_sent` |

### Step 16: Closure, Reopen, and Auto-close

File: `src/services/closure.py` -> `ClosureService`

Three ways a case can close:

1. **Vendor confirmation** — vendor replies with "thanks" / "resolved" / "fixed" etc. (`settings.confirmation_keywords`)
2. **Auto-close** — 5 business days pass with no reply
3. **Admin force-close** — direct `close_case()` call

And two ways a closed case can re-open:

1. **Inside `settings.closure_reopen_window_days`** (default 7 days) — flip case back to `AWAITING_RESOLUTION`, re-enqueue to intake with `resume_context.is_reopen=True`, publish `TicketReopened`
2. **Outside the window** — create a new query_id via standard intake; link via `workflow.case_execution.linked_query_id`

#### Step 16.1: register_resolution_sent

Called from `delivery.py` on successful email send. INSERT into `workflow.closure_tracking`:
- `query_id` (PK), `resolution_sent_at = ist_now()`, `auto_close_deadline = DateHelper.add_business_days(ist_now(), 5)` (skips Sat/Sun; no holiday calendar in dev)

#### Step 16.2: detect_confirmation

Called from `src/services/email_intake/service.py` after thread correlation returns `REPLY_TO_CLOSED` or `EXISTING_OPEN`:

| Step | Code | What it does |
|------|------|-------------|
| 1 | Look up `closure_tracking` by original query_id | Skip if no row or already closed |
| 2 | Lowercase email body, search for any keyword from `settings.confirmation_keywords` | `{"thanks", "thank you", "resolved", "fixed", "that worked", "works now", "appreciate it"}` |
| 3 | If matched → `close_case(query_id, reason="VENDOR_CONFIRMED")` | Standard closure flow |
| 4 | If `REPLY_TO_CLOSED` and NOT a confirmation → `handle_reopen(query_id, new_email_payload, correlation_id)` | Reopen logic (inside vs outside window) |
| 5 | If `EXISTING_OPEN` and NOT a confirmation → `handle_followup_info(conversation_id, new_query_id, body_text, attachments_summary, correlation_id)` | Follow-up reply on a still-open case (vendor sends missing PDF / extra detail) — see Step 16.2b below |

Non-critical: closure detection failure must not block email ingestion.

#### Step 16.2b: handle_followup_info (vendor sends missing info on the same thread)

File: `src/services/closure.py` -> `ClosureService.handle_followup_info()`

The vendor sends an initial query, realises they forgot a PDF (or any required detail), then replies in the same email thread with the missing info. Without this method the reply spawns a duplicate query_id, a second ServiceNow ticket, and a duplicate LLM analysis run. This method merges the reply into the prior case instead.

| Step | Code | What it does |
|------|------|-------------|
| 1 | `_find_prior_query_by_conversation(conversation_id)` | Locate the prior `query_id` on the same thread |
| 2 | `_fetch_case_status(prior_query_id)` | Read `workflow.case_execution.status` |
| 3 | If status not in `_MERGEABLE_STATUSES` (i.e. RESOLVED / CLOSED / unknown) → return `"SKIPPED"` | Closed cases go through `handle_reopen` instead |
| 4 | `_append_additional_context(prior_query_id, ...)` | `UPDATE workflow.case_execution SET additional_context = COALESCE(additional_context, '[]'::jsonb) \|\| $1::jsonb` — appends the new body + attachments_summary as a JSON entry on the prior case |
| 5 | `_mark_child_merged(new_query_id, prior_query_id)` | `UPDATE workflow.case_execution SET status='MERGED_INTO_PARENT', parent_query_id=$1 WHERE query_id=$3` so the child case is marked as merged and traceable |
| 6 | `_record_followup_audit(...)` | `INSERT INTO audit.action_log (action='FOLLOWUP_INFO_RECEIVED', details=...)` for compliance |
| 7 | If prior status was `AWAITING_RESOLUTION` (Path B human team) → `_add_servicenow_followup_note(...)` calls `servicenow.add_work_note(ticket_id, note_text)` | Surfaces the new info as a work note on the existing ticket so the team sees it without a second incident |
| 8 | Returns `"MERGED_MID_PIPELINE"` (statuses RECEIVED/ANALYZING/ROUTING/DRAFTING/VALIDATING/DELIVERING/PAUSED/PENDING_APPROVAL) or `"MERGED_PATH_B"` (AWAITING_RESOLUTION) | Test hook + audit signal |

**Mergeable statuses** (`ClosureService._MERGEABLE_STATUSES`):
`RECEIVED`, `ANALYZING`, `ROUTING`, `DRAFTING`, `VALIDATING`, `DELIVERING`, `PAUSED` (Path C reviewer parking), `PENDING_APPROVAL` (Path A admin approval), `AWAITING_RESOLUTION` (Path B human team).

**Pickup on the prior case:** `src/orchestration/nodes/context_loading.py` -> `ContextLoadingNode._load_additional_context()` reads the column on the prior case's next pipeline checkpoint and exposes it as `state["additional_context"]` for Query Analysis to fold into its input corpus. The merged corpus reaches the LLM the next time the prior case re-enters Context Loading.

Non-critical at every step. A failure to merge leaves the new query_id flowing through the standard pipeline as a fallback (the legacy behavior — duplicate ticket — is the worst case, never lost data).

#### Step 16.3: close_case (single write path)

| Step | Code | What it does |
|------|------|-------------|
| 1 | `postgres.execute("UPDATE workflow.case_execution SET status='CLOSED', closed_at=$2 WHERE query_id=$1")` | Flip case state |
| 2 | `postgres.execute("UPDATE workflow.closure_tracking SET closed_at=$2, closed_reason=$3 WHERE query_id=$1")` | Record reason (VENDOR_CONFIRMED / AUTO_CLOSED / REOPENED) |
| 3 | `postgres.execute("UPDATE workflow.sla_checkpoints SET last_status='CLOSED' WHERE query_id=$1")` | SLA monitor will skip this case on its next tick |
| 4 | `servicenow.update_ticket_status(ticket_id, "Closed", work_notes=f"Closed by VQMS: {reason}")` | Update ITSM side |
| 5 | `eventbridge.publish_event("TicketClosed", ...)` | **Non-critical** — logged warning on failure |
| 6 | `episodic_memory_writer.save_closure(query_id, correlation_id)` | See Step 16.5 below |

#### Step 16.4: AutoCloseScheduler — background sweep

File: `src/services/auto_close_scheduler.py` -> `AutoCloseScheduler.tick()`

Same asyncio-loop shape as SlaMonitor. Tick every `settings.auto_close_interval_seconds` (default 3600s = 1 hour):

```sql
SELECT query_id FROM workflow.closure_tracking
WHERE closed_at IS NULL AND auto_close_deadline <= now()
```

For each row: `closure_service.close_case(query_id, reason="AUTO_CLOSED", correlation_id=...)`.

#### Step 16.5: Episodic Memory Writer

File: `src/services/episodic_memory.py` -> `EpisodicMemoryWriter.save_closure()`

**Input:** `query_id`, `correlation_id`
**Output:** One new row in `memory.episodic_memory` (or a logged warning on failure — closure still succeeds)

| Step | Code | What it does |
|------|------|-------------|
| 1 | `postgres.fetchrow("SELECT vendor_id, intent, processing_path, status, created_at FROM workflow.case_execution WHERE query_id = $1")` | Pull the case's final state |
| 2 | Build deterministic `summary = f"{intent} for {vendor_id}: {processing_path} resolution, closed with {reason}"` | Dev-mode stub — future production can call Bedrock for a richer summary |
| 3 | `memory_id = IdGenerator.generate_correlation_id()` | UUID |
| 4 | `postgres.execute("INSERT INTO memory.episodic_memory (memory_id, vendor_id, query_id, intent, resolution_path, outcome, resolved_at, summary) VALUES (...)")` | Row is now visible to `context_loading._load_episodic_memory()` on the next query from this vendor — the system learns from its own history |
| 5 | **Non-critical** — try/except around the whole thing; log `episodic_memory_save_failed` on error | Closure must succeed even if memory write fails |

### Data model (migration 012)

`src/db/migrations/012_create_sla_tracking.sql` creates:

- `workflow.sla_checkpoints` — `query_id` PK, `sla_started_at`, `sla_deadline`, `warning_fired BOOL`, `l1_fired BOOL`, `l2_fired BOOL`, `last_checked_at`, `last_status`. Index `idx_sla_active` on `(last_status, sla_deadline)` for scheduler scan.
- `workflow.closure_tracking` — `query_id` PK, `resolution_sent_at`, `auto_close_deadline`, `closed_at`, `closed_reason` (VENDOR_CONFIRMED / AUTO_CLOSED / REOPENED), `vendor_confirmation_detected_at`
- `workflow.case_execution.linked_query_id` — new nullable column so outside-window reopens can link back to the original closed case

### New settings (config/settings.py)

| Name | Default | Purpose |
|------|---------|---------|
| `sla_monitor_interval_seconds` | 60 | Tick interval for `SlaMonitor` |
| `auto_close_business_days` | 5 | Business days from resolution send → auto-close |
| `closure_reopen_window_days` | 7 | Days after close a reply re-opens vs. creates a linked ticket |
| `auto_close_interval_seconds` | 3600 | Tick interval for `AutoCloseScheduler` |
| `confirmation_keywords` | `["thanks", "thank you", "resolved", "fixed", "that worked", "works now", "appreciate it"]` | Detect vendor confirmation on replies |

### Lifespan wiring (app/lifespan.py)

```python
# Phase 6 services — instantiated after existing services
episodic_writer = EpisodicMemoryWriter(postgres=postgres, bedrock=bedrock, settings=settings)
closure_service = ClosureService(postgres=postgres, graph_api=graph_api, servicenow=servicenow,
                                 eventbridge=eventbridge, episodic_writer=episodic_writer, settings=settings)
sla_monitor = SlaMonitor(postgres=postgres, eventbridge=eventbridge, settings=settings)
auto_close_scheduler = AutoCloseScheduler(postgres=postgres, closure_service=closure_service, settings=settings)

# Background task lifecycle
await sla_monitor.start()
await auto_close_scheduler.start()
# ... attach to application.state.* for visibility / tests ...

# On shutdown
await sla_monitor.stop()
await auto_close_scheduler.stop()
```

---

## Admin Email Send/Reply (Free-form, side-channel)

The AI pipeline drafts and sends most outbound emails (Path A resolution, Path B acknowledgment, Step 15 resolution-from-notes — see "Step 12: Delivery"). Admins can also send or reply to vendor emails directly without going through the pipeline. This is a side-channel — no Quality Gate, no LangGraph, no SLA recompute.

### POST /admin/email/send — fresh email

Trigger: admin posts `multipart/form-data` to `/admin/email/send` with `to`, `subject`, `body_html`, optional `cc`/`bcc`/`vendor_id`/`query_id`/`files[]`. Optional `X-Request-Id` header dedupes replays.

File: `src/api/routes/admin_email.py` -> `send_email()`

1. AuthMiddleware decodes the JWT into `request.state` (CLAUDE.md vendor_id-from-JWT rule applies; ADMIN tokens have vendor_id=None).
2. `_require_admin(request)` raises 403 unless `request.state.role == "ADMIN"`.
3. `_split_csv` turns `to`/`cc`/`bcc` form fields into `list[str]`.
4. Hand off to `AdminEmailService.send(...)`:
   - `AttachmentValidator.validate(files)` enforces count <= 10, per-file <= 25 MB, total <= 50 MB, no .exe/.bat/.cmd/.ps1/.sh/.js extensions. Failure raises `AttachmentRejectedError` -> 422.
   - When `query_id` is supplied, `SELECT 1 FROM workflow.case_execution WHERE query_id = $1` -> raises `AdminEmailQueryNotFoundError` -> 404 if missing.
   - `_payload_hash` SHA-256s the canonical request body (sorted recipients, subject, body, file metadata).
   - When `client_request_id` is present, `_check_idempotent_replay`:
     - Same hash + status SENT -> returns the prior `AdminSendResult` with `idempotent_replay=True`, response header `X-Idempotent-Replay: true`. **Vendor receives one email even on double-click.**
     - Different hash -> `AdminEmailError("...different content")` -> 409.
     - Status FAILED -> caller proceeds (treats as retry).
   - `_generate_outbound_id` mints `AOE-2026-NNNN`.
   - `AttachmentStager.stage(outbound_id, files)` uploads each file to `s3://vqms-data-store/outbound-emails/{outbound_id}/{att_id}_{filename}` and returns `OutboundAttachment` records (bytes still in memory for Graph).
   - `_insert_outbound_row` opens a single Postgres transaction and inserts:
     - `intake.admin_outbound_emails` row with `status='QUEUED'` and `payload_hash`.
     - `intake.admin_outbound_attachments` rows with `upload_status='STAGED'`.
   - `graph_api.send_email(to=[...], subject, body_html, cc=, bcc=, attachments=[...])`. The adapter picks the inline path (`/sendMail`) when total attachment bytes <= 3 MB, or the upload-session path (`POST /messages` -> `createUploadSession` -> chunked PUT -> `POST /messages/{id}/send`) for larger payloads.
   - On `GraphAPIError`: `_mark_failed` flips row to `status='FAILED'`, attachments to `upload_status='FAILED'`, captures `last_error`. Audit row written. Re-raises as `AdminEmailError` -> 502.
   - On success: `_mark_sent` flips to `SENT` + `sent_at`, attachments to `SENT`. `audit.action_log` row inserted with `actor=<admin email>`, `action=admin_email_send`, `details.quality_gate=skipped_admin_actor`.
5. Route returns 200 with `outbound_id`, recipients, `thread_mode='fresh'`, attachments list, and `idempotent_replay=false`.

### POST /admin/email/queries/{query_id}/reply — threaded reply

Trigger: admin posts `multipart/form-data` to `/admin/email/queries/{query_id}/reply` with `body_html`, optional `cc`/`bcc`/`to_override`/`reply_to_message_id`/`files[]`.

File: `src/api/routes/admin_email.py` -> `reply_to_query()`

1. Auth + admin check + multipart parse (same as `/send`).
2. `AdminEmailService.reply_to_query(query_id, ...)`:
   - `_resolve_reply_anchor` runs `SELECT message_id, sender_email, subject, conversation_id, query_id FROM intake.email_messages WHERE query_id = $1 OR conversation_id = (SELECT conversation_id ... LIMIT 1) ORDER BY received_at DESC LIMIT 1`.
     - No row + case_execution exists -> `reason='no_trail'` -> 422 ("use /admin/email/send instead").
     - No row + no case_execution -> `reason='not_found'` -> 404.
     - When `reply_to_message_id_override` is provided, the override row's `conversation_id` (or `query_id` when conv is NULL) must match the latest anchor's, otherwise -> `reason='override_message_in_different_conversation'` -> 422.
   - `to` defaults to `anchor.sender_email` unless `to_override` provided. `subject` is taken from the anchor (Graph rewrites it with `RE:` on the reply path anyway — we still log it).
   - Same payload-hash + idempotency + transaction + Graph send flow as `/send`, but `graph_api.send_email(..., reply_to_message_id=anchor.message_id)`. The adapter then calls `POST /messages/{message_id}/reply` (no attachments) or `POST /messages/{message_id}/createReply` -> upload sessions -> `/send` (with attachments). Graph copies the original `conversationId` and sets `In-Reply-To` / `References` headers — vendor's Outlook/Gmail/Apple Mail groups the reply under the same trail.
   - Audit `action=admin_email_reply` with `reply_to_message_id`, `conversation_id` in details.
3. Route returns 200 with `outbound_id`, recipients, `thread_mode='reply'`, `reply_to_message_id`, `conversation_id`, attachments, `idempotent_replay`.

### Data model (migration 019)

- `intake.admin_outbound_emails` — outbound_id (PK, AOE-YYYY-NNNN), request_id (idempotency), correlation_id, query_id (nullable), actor, to/cc/bcc JSONB, subject, body_html, thread_mode (`fresh`/`reply`), reply_to_message_id, graph_message_id, payload_hash, status (QUEUED/SENT/FAILED), last_error, sent_at, failed_at, created_at. Unique partial index on `(actor, request_id) WHERE request_id IS NOT NULL` enforces idempotency.
- `intake.admin_outbound_attachments` — attachment_id (PK), outbound_id (FK, ON DELETE CASCADE), filename, content_type, size_bytes, s3_key, upload_status (STAGED/SENT/FAILED), created_at.

### Why this is a side-channel

Admin sends bypass the Quality Gate (PII / restricted terms / length / source citations) on purpose — admin is a trusted actor and the gate is calibrated for AI-generated drafts. The skip is recorded in `audit.action_log.details.quality_gate=skipped_admin_actor` so compliance review can see it. SLA timers are unaffected: admin replies do NOT call `closure_service.register_resolution_sent` and therefore do not start the auto-close window. To formally resolve a case, use `/admin/drafts/{query_id}/approve` or `/admin/drafts/{query_id}/edit-approve` instead.

---

## What is not built yet

- Triage reviewer portal UI (Angular) — API is done, reviewer pages still use the vendor portal shell (Phase 7)
- Admin dashboard with path distribution / cost metrics (Phase 7)
- PII detection via Amazon Comprehend (Quality Gate stub exists, Phase 8)
- Integration testing and hardening (Phase 8)
- LLM-based summarization in EpisodicMemoryWriter (deterministic stub in dev mode; Bedrock summary is planned for production)
- Holiday calendar for `DateHelper.add_business_days` (dev mode skips only Sat/Sun)
