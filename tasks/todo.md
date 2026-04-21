# VQMS Task Tracker

## Phase 1: Foundation and Data Layer — COMPLETE

### Step 1: Project Skeleton
- [x] Create full 5-layer folder structure with __init__.py files
- [x] Update pyproject.toml with all dependencies (164 packages installed)
- [x] Create .gitignore, .ruff.toml, .env.copy
- [x] Create tasks/todo.md, tasks/lessons.md, Flow.md
- [x] Update main.py (FastAPI stub with /health) and README.md
- [x] Run uv sync and verify imports

### Step 2: Configuration
- [x] Build config/settings.py with pydantic-settings (20 field groups, Bedrock + OpenAI)

### Step 3: Utilities
- [x] Build utils/helpers.py (ist_now, generate_query_id, generate_correlation_id)
- [x] Build utils/logging_setup.py (structlog JSON config, LogContext)
- [x] Build utils/exceptions.py (7 domain exceptions)
- [x] Build utils/decorators.py (4 logging decorators)

### Step 4: Pydantic Models
- [x] Create all 11 model files in models/ (22 models total)
- [x] Create models/pipeline_state.py (TypedDict for LangGraph)
- [x] Write tests/test_models.py (44 tests, all passing)

### Step 5: Database + Connector
- [x] Create 9 SQL migration files in db/migrations/ (including 000_reset)
- [x] Build connectors/postgres.py (SSH tunnel + asyncpg pool + psycopg2 migrations)
- [x] Run migrations against RDS (14 tables across 6 schemas)
- [x] Test idempotency check (first=True, second=False)

### Step 6: Gate Check
- [x] All models validate — 44 pytest tests pass
- [x] Migrations ran — 14 tables exist across 6 schemas
- [x] pgvector extension installed with HNSW index
- [x] PostgreSQL connector works via SSH tunnel
- [x] Idempotency works (INSERT ON CONFLICT DO NOTHING)
- [x] ruff check passes (0 errors)
- [x] pytest passes (44/44)
- [x] Flow.md and README.md updated

## Phase 2: Intake Services (Email + Portal) — COMPLETE

### Step 1: Shared Fixtures + S3 Connector
- [x] Update tests/conftest.py with shared fixtures (mock_settings, aws mocks, sample data)
- [x] Build src/connectors/s3.py (upload_file, download_file, generate_presigned_url)
- [x] Write S3 tests in tests/test_connectors.py (5 tests)

### Step 2: SQS Connector
- [x] Build src/connectors/sqs.py (send_message, receive_messages, delete_message)
- [x] Write SQS tests in tests/test_connectors.py (5 tests)

### Step 3: EventBridge Connector
- [x] Build src/connectors/eventbridge.py (publish_event, 20 valid event types)
- [x] Write EventBridge tests in tests/test_connectors.py (5 tests)

### Step 4: Graph API Connector
- [x] Build src/connectors/graph_api.py (MSAL auth, fetch/send email, list unread, webhook)
- [x] Lazy MSAL init to avoid OIDC discovery in tests
- [x] Retry with tenacity on 429/500/502/503
- [x] Write tests/test_graph_api.py (11 tests)

### Step 5: Salesforce Connector
- [x] Build src/connectors/salesforce.py (3-step identify_vendor, find_by_email, fuzzy_name)
- [x] Write tests/test_salesforce.py (11 tests)

### Step 6: Email Intake Service
- [x] Build src/intake/email_intake.py (10-step process_email pipeline)
- [x] Critical vs non-critical step classification
- [x] Attachment processing with safety guardrails
- [x] Thread correlation (NEW / EXISTING_OPEN / REPLY_TO_CLOSED)
- [x] Write tests/test_email_intake.py (15 tests)

### Step 7: Portal Intake Service
- [x] Build src/intake/portal_intake.py (submit_query with SHA-256 idempotency)
- [x] Write tests/test_portal_intake.py (11 tests)

### Step 8: FastAPI Routes + main.py Update
- [x] Build src/intake/routes.py (POST /queries, GET /queries/{id}, POST /webhooks/ms-graph)
- [x] Update src/main.py with lifespan (connector init/shutdown), include router
- [x] Update src/config/settings.py with SQS queue URL fields
- [x] Write tests/test_routes.py (10 tests)

### Step 9: Reconciliation Poller
- [x] Build src/intake/polling.py (poll_once, start_polling_loop, stop)
- [x] Write tests/test_polling.py (6 tests)

### Step 10: Gate Check
- [x] uv run ruff check . — 0 errors
- [x] uv run pytest — 123/123 tests pass
- [x] Email path: process_email → idempotency → parsed → S3 → vendor → thread → DB → SQS → EB
- [x] Portal path: POST /queries → query_id returned → DB → SQS → EB
- [x] Idempotency: same email twice → second returns None. Same portal query twice → 409
- [x] Attachments: blocked extensions skipped, oversized skipped, text extraction
- [x] Vendor: known email → VendorMatch. Unknown → None, pipeline continues
- [x] Thread: conversationId → EXISTING_OPEN / REPLY_TO_CLOSED / NEW
- [x] Webhook: validation token echoed, notification processes email
- [x] Polling: list_unread → process each → duplicates skipped → errors don't block
- [x] Flow.md updated with email and portal paths
- [x] README.md updated with Phase 2 status

## Phase 3: AI Pipeline Core — COMPLETE

### Step 1: Bedrock Connector
- [x] Build src/connectors/bedrock.py (llm_complete, llm_embed, retry with tenacity, cost tracking)
- [x] Write tests/test_bedrock.py (19 tests — retry predicate, LLM complete, embed, cost calc)

### Step 2: Prompt Templates
- [x] Create src/pipeline/prompts/prompt_manager.py (Jinja2, StrictUndefined, template caching)
- [x] Create query_analysis_v1.j2, resolution_v1.j2, acknowledgment_v1.j2, resolution_from_notes_v1.j2
- [x] Write tests/test_prompts.py (12 tests — render, metadata, missing vars)

### Step 3: Context Loading Node
- [x] Build src/pipeline/nodes/context_loading.py (cache → Salesforce → default BRONZE, episodic memory)
- [x] Write tests/test_context_loading.py (6 tests — cache hit/miss, no vendor_id, default, memory)

### Step 4: Query Analysis Node
- [x] Build src/pipeline/nodes/query_analysis.py (8-layer defense: input validation → prompt → LLM → parse → validate → self-correct → fallback → audit)
- [x] Write tests/test_query_analysis.py (8 tests — happy path, JSON fences, preamble, self-correction, fallback, timeout, empty body)

### Step 5: Confidence Check Node
- [x] Build src/pipeline/nodes/confidence_check.py (>= 0.85 continue, < 0.85 Path C)
- [x] Write tests/test_confidence_check.py (6 tests — above/at/below threshold, path_c)

### Step 6: Routing Node
- [x] Build src/pipeline/nodes/routing.py (team assignment by category, SLA by tier×urgency)
- [x] Write tests/test_routing_node.py (17 tests — all teams, all SLA combos, defaults)

### Step 7: KB Search Node
- [x] Build src/pipeline/nodes/kb_search.py (embed → pgvector cosine similarity → threshold 0.80)
- [x] Write tests/test_kb_search.py (6 tests — high match, multiple, no match, below threshold, embed timeout, DB error)

### Step 8: Path Decision Node
- [x] Build src/pipeline/nodes/path_decision.py (sufficient+content→A, else→B with human_investigation flag)
- [x] Write tests/test_path_decision.py (6 tests — path A, path B variants, empty KB)

### Step 9: LangGraph Orchestrator
- [x] Build src/pipeline/graph.py (StateGraph with conditional edges, placeholder nodes for Phase 4)
- [x] Write tests/test_graph.py (4 tests — Path A/B/C flow, graph compiles)

### Step 10: SQS Consumer
- [x] Build src/pipeline/consumer.py (process_message, start_consumer, consume_both_queues)
- [x] Write tests/test_consumer.py (5 tests — success/failure, initial state, stop)

### Step 11: Dependency Injection + main.py
- [x] Build src/pipeline/dependencies.py (create_pipeline wiring)
- [x] Update main.py with BedrockConnector, pipeline init, version 0.3.0, phase 3

### Step 12: Gate Check
- [x] uv run ruff check . — clean (1 pre-existing issue in scripts/)
- [x] uv run pytest — 219/219 tests pass (96 new tests added)
- [x] Flow.md updated with Steps 7-9, graph, consumer, prompts, connectors
- [x] README.md updated with Phase 3 status
- [x] tasks/todo.md updated

### OpenAI Fallback + LLM Gateway (Post Phase 3)
- [x] Build src/connectors/openai_llm.py (OpenAIConnector: Chat Completions + Embeddings, tenacity retry, cost tracking)
- [x] Add LLMProviderError to src/utils/exceptions.py
- [x] Build src/connectors/llm_gateway.py (LLMGateway: 4 provider modes, fallback routing)
- [x] Write tests/test_openai_llm.py (9 tests — init, complete, embed, cost)
- [x] Write tests/test_llm_gateway.py (11 tests — bedrock_only, openai_only, fallback, reverse fallback)
- [x] Update pipeline nodes (query_analysis.py, kb_search.py) to use LLMGateway
- [x] Update pipeline/dependencies.py to accept LLMGateway
- [x] Update main.py to create LLMGateway and pass to create_pipeline()
- [x] uv run ruff check . — clean
- [x] uv run pytest — 239/239 tests pass (20 new tests added)
- [x] Flow.md updated with OpenAI connector, LLM Gateway, updated startup
- [x] README.md updated with OpenAI/Gateway info, 239 test count

## Auth + Vendor CRUD Merge (local_vqm → VQMS) — COMPLETE

- [x] Step 1: Add werkzeug dependency
- [x] Step 2: Add JWT settings to config/settings.py
- [x] Step 3: Update .env.copy with JWT section
- [x] Step 4: Create src/cache/pg_cache.py (auth token blacklist helpers)
- [x] Step 5: Create src/models/auth.py (UserRecord, LoginRequest, LoginResponse, TokenPayload)
- [x] Step 6: Create migration 009_auth_tables_documentation.sql (auth tables + cache.kv_store)
- [x] Step 7: Create src/services/auth.py (authenticate_user, create/validate/blacklist JWT)
- [x] Step 8: Create src/api/middleware/auth_middleware.py (JWT validation middleware)
- [x] Step 9: Create src/api/routes/auth.py (POST /auth/login, POST /auth/logout)
- [x] Step 10: Append vendor CRUD models to src/models/vendor.py
- [x] Step 11: Add get_all_active_vendors + update_vendor_account to salesforce.py
- [x] Step 12: Create src/api/routes/vendors.py (GET /vendors, PUT /vendors/{vendor_id})
- [x] Step 13: Wire AuthMiddleware + auth_router + vendors_router in main.py
- [x] Step 14: Write unit tests (34 new tests — auth models, auth service, middleware, vendor routes)
- [x] Step 15: Update documentation (CLAUDE.md, Flow.md, README.md, tasks/todo.md)
- [x] Verification: 273 tests pass, ruff clean

## Phase 4: Response Generation and Delivery (Steps 10-12) — COMPLETE

### Step 1: ServiceNow Connector (httpx)
- [x] Build src/adapters/servicenow.py (create_ticket, update_status, get_ticket, get_work_notes)
- [x] Write tests/test_servicenow.py (21 tests — create, update, get, work notes, helpers, lazy init)

### Step 2: Resolution Node — Path A
- [x] Build src/orchestration/nodes/resolution.py (LLM Call #2 — full answer from KB)
- [x] Write tests/test_resolution.py (14 tests — draft, LLM failure, JSON parsing, edge cases)

### Step 3: Acknowledgment Node — Path B
- [x] Build src/orchestration/nodes/acknowledgment.py (acknowledgment-only email)
- [x] Write tests/test_acknowledgment.py (12 tests — draft, LLM failure, edge cases)

### Step 4: Quality Gate Node
- [x] Build src/orchestration/nodes/quality_gate.py (7 checks)
- [x] Write tests/test_quality_gate.py (18 tests — all 7 checks individually, pass/fail scenarios)

### Step 5: Delivery Node
- [x] Build src/orchestration/nodes/delivery.py (ServiceNow ticket + Graph API email)
- [x] Write tests/test_delivery.py (11 tests — success, ticket failure, email failure, edge cases)

### Step 6: Wire Phase 4 into Graph
- [x] Update graph.py to replace 4 placeholders with real nodes (kept triage for Phase 5)
- [x] Update dependencies.py to inject ServiceNow + Graph API + Phase 4 nodes
- [x] Update main.py with ServiceNow + Graph API connector init/shutdown
- [x] Update tests/test_graph.py (4 tests updated with new mock node params)

### Step 7: Gate Check
- [x] uv run ruff check . — clean
- [x] uv run pytest — 358 pass (76 new), 3 pre-existing failures
- [x] Update Flow.md with Steps 10A, 10B, 11, 12, ServiceNow connector
- [x] Update README.md with Phase 4 status
- [x] Update tasks/todo.md

---

## Phase 5: Human Review and Path C (Steps 8C.1-8C.3) — COMPLETE

Gate criteria met:
- Workflow pauses when confidence < 0.85 (status=PAUSED, processing_path=C)
- TriagePackage persisted with all required fields (callback_token, original_query, analysis_result, suggested_routing, confidence_breakdown, created_at)
- Reviewer corrections re-enqueue the query to the intake SQS with `resume_context.from_triage=True`, so context_loading re-runs with high confidence and flows into Path A or B naturally
- Graceful degradation: SQS unavailable → audit trail still persisted, `resume_method="db_only"` returned
- Security: `reviewer_id` always taken from JWT sub, never from request body

### Step 1: Data Model
- [x] Add `callback_token: str` to TriagePackage; make `suggested_routing` optional
- [x] Add frozen TriageQueueItem model for queue listings
- [x] Add migration `011_create_triage_tables.sql` (workflow.triage_packages, workflow.reviewer_decisions + indexes)

### Step 2: Triage Node (Path C pause)
- [x] Build `src/orchestration/nodes/triage.py` — TriageNode.execute(state)
- [x] Persist package (INSERT ON CONFLICT DO NOTHING) — critical
- [x] Update case_execution to PAUSED — critical
- [x] Publish HumanReviewRequired event — non-critical (graceful degradation)
- [x] Heuristic `_build_confidence_breakdown()` for reviewer context
- [x] Write tests/test_triage_node.py (6 tests — happy, no-EB, EB failure, postgres failure, breakdown)

### Step 3: Triage Service (Queue + Decision)
- [x] Build `src/services/triage.py` — TriageService
- [x] `list_pending(limit)` — clamp limit to [1, 200], oldest first
- [x] `get_package(query_id)` — raise TriagePackageNotFoundError on miss
- [x] `submit_decision(query_id, decision)` — verify PENDING, insert audit row, flip package, apply corrections, update case_execution, re-enqueue SQS, publish HumanReviewCompleted
- [x] `_apply_corrections()` — immutable dict copy, confidence override or 1.0, stamp human_validated=True
- [x] `_reenqueue()` — SQS send with resume_context, fallback to "db_only" on failure
- [x] Write tests/test_triage_service.py (13 tests — list + clamp params + get + submit happy/missing/reviewed + sqs fallbacks + corrections)

### Step 4: Triage Routes (Reviewer API)
- [x] Build `src/api/routes/triage.py` — APIRouter with prefix=/triage
- [x] `_require_reviewer(request)` — 403 unless role in {REVIEWER, ADMIN}
- [x] ReviewerDecisionRequest with `confidence_override ∈ [0.0, 1.0]` and `reviewer_notes` min_length=1
- [x] GET /triage/queue, GET /triage/{query_id}, POST /triage/{query_id}/review
- [x] `reviewer_id` sourced from `request.state.username` (JWT sub), never from body
- [x] Write tests/test_triage_routes.py (17 tests — auth guards × 6, list × 2, detail × 2, review × 7 including JWT-over-body security test)

### Step 5: Wire Phase 5 into Graph
- [x] Remove triage_placeholder from graph.py
- [x] Register real TriageNode via dependencies.py (with eventbridge injection)
- [x] Update app/lifespan.py to instantiate TriageService on state
- [x] Update app/routes.py to register triage_router
- [x] Update tests/test_graph.py Path A/B/C to assert triage invocation only on Path C

### Step 6: Gate Check
- [x] uv run ruff check . — clean
- [x] uv run pytest tests/test_graph.py tests/test_triage_node.py tests/test_triage_service.py tests/test_triage_routes.py — all 43 green
- [x] uv run pytest — 408 pass (50 new Phase 5 tests), 3 pre-existing failures unrelated to Phase 5
- [x] Update Flow.md with Path C section (8C.1, 8C.2, 8C.3 + resume-via-SQS)
- [x] Update README.md (Phase 5 complete, triage endpoints in API table)
- [x] Update tasks/todo.md (this entry)

---

## Phase 6: SLA Monitoring and Closure (Steps 13-16) — COMPLETE

Gate criteria met:
- SLA escalation fires at correct thresholds (70% / 85% / 95%) and is idempotent via per-threshold boolean flags
- Path B end-to-end works: ServiceNow webhook → SQS re-enqueue → graph entry-switch → resolution_from_notes → quality_gate → delivery → ResolutionPrepared event + email sent + closure_tracking row
- Closure works in all three ways: confirmation keyword match on reply, AutoCloseScheduler sweep at business-day deadline, force-close
- Reopen inside `closure_reopen_window_days` flips case to AWAITING_RESOLUTION and re-enqueues; outside window creates a new linked query_id via `case_execution.linked_query_id`
- Episodic memory row persisted on every closure (vendor_id, query_id, intent, resolution_path, outcome, resolved_at, summary) — visible to `context_loading._load_episodic_memory()` on next query

### Workstream A: SLA Monitor
- [x] Migration `012_create_sla_tracking.sql` — `workflow.sla_checkpoints` + `workflow.closure_tracking` + `case_execution.linked_query_id` + `idx_sla_active`
- [x] `src/models/sla.py` — `SlaCheckpoint` frozen Pydantic + `SlaThresholdCrossed` enum
- [x] `src/services/sla_monitor.py` — `SlaMonitor` asyncio task loop with start/stop/tick; flag-driven idempotency
- [x] Wire into `src/orchestration/nodes/routing.py` — non-critical INSERT to `sla_checkpoints` after computing SLATarget
- [x] Wire into `app/lifespan.py` — instantiate + start/stop on application state
- [x] Tests: `tests/test_sla_monitor.py`

### Workstream B: Path B Resolution Flow (Step 15)
- [x] `src/orchestration/nodes/resolution_from_notes.py` — `ResolutionFromNotesNode.execute()` with tier-aware SLA statements
- [x] Update `src/orchestration/nodes/delivery.py` — `resolution_mode` branch (skip ticket creation, reuse INC, update ServiceNow to AWAITING_VENDOR_CONFIRMATION, use vendor_context.email_address)
- [x] Update `src/models/workflow.py` — add `resolution_mode` and `work_notes` to `PipelineState` TypedDict
- [x] Add `POST /webhooks/servicenow` handler in `src/api/routes/webhooks.py` with `ServiceNowWebhookPayload`
- [x] Update `src/orchestration/sqs_consumer.py` — carry `resume_context.action` into initial state
- [x] Update `src/orchestration/graph.py` — entry passthrough + `route_from_entry` conditional edge for `resume_context.action == "prepare_resolution"`
- [x] Update `src/orchestration/dependencies.py` — instantiate + inject `ResolutionFromNotesNode`
- [x] Tests: `tests/test_resolution_from_notes_node.py` (16 tests), `tests/test_servicenow_webhook.py` (12 tests), `tests/test_graph.py` (2 new tests for Step 15 branch)

### Workstream C: Closure Logic
- [x] `src/services/closure.py` — `ClosureService` with `register_resolution_sent`, `detect_confirmation`, `close_case`, `handle_reopen`
- [x] `src/services/auto_close_scheduler.py` — `AutoCloseScheduler` asyncio task loop (same shape as SlaMonitor)
- [x] Hook into `src/services/email_intake/service.py` — call `detect_confirmation` / `handle_reopen` after thread correlation
- [x] `src/utils/helpers.py` — `DateHelper.add_business_days` (skips Sat/Sun)
- [x] `config/settings.py` — `auto_close_business_days=5`, `closure_reopen_window_days=7`, `sla_monitor_interval_seconds=60`, `auto_close_interval_seconds=3600`, `confirmation_keywords=[...]`
- [x] Wire into `app/lifespan.py` — instantiate `ClosureService`, start/stop `AutoCloseScheduler`
- [x] Tests: `tests/test_closure_service.py`, `tests/test_auto_close_scheduler.py`

### Workstream D: Episodic Memory Writer
- [x] `src/services/episodic_memory.py` — `EpisodicMemoryWriter.save_closure()` with deterministic dev-mode summary
- [x] Integration: `ClosureService.close_case` calls `save_closure` after ServiceNow update + TicketClosed event
- [x] Non-critical: try/except around memory write, closure succeeds even on memory failure
- [x] Tests: `tests/test_episodic_memory.py`

### Gate Check
- [x] uv run ruff check . — clean (zero warnings)
- [x] uv run pytest tests/test_sla_monitor.py tests/test_closure_service.py tests/test_auto_close_scheduler.py tests/test_episodic_memory.py tests/test_resolution_from_notes_node.py tests/test_servicenow_webhook.py tests/test_graph.py -v — all green
- [x] uv run pytest — 492 pass, 3 pre-existing failures unrelated to Phase 6 (portal_intake db_write, 2 X-Vendor-ID tests)
- [x] Update Flow.md with Step 13 (SLA Monitor), Step 15 (resolution-from-notes), Step 16 (closure + auto-close + reopen), episodic memory write-back
- [x] Update README.md — Phase 6 complete, Phase 6 capabilities block, `/webhooks/servicenow` in API table
- [x] Update tasks/todo.md (this entry)

---

## Current Phase: 7 — Frontend Portal (Angular)
