# VQMS Low-Level Design — Pipeline in ASCII Boxes

> Every stage of the pipeline as a box: **what goes in**, **what happens
> inside**, **what comes out**. Read top to bottom and you'll know which
> file, class, and method run at every step.

Audience: a developer who has never seen this codebase before.

---

## 1. The 10-Second Summary

```
┌────────────────────────────────────────────────────────────────────────────┐
│  VQMS in one picture                                                       │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│   Vendor Email ─┐                                                          │
│                 │                                                          │
│                 ├──▶ [Intake] ──▶ [SQS] ──▶ [LangGraph Pipeline] ──▶ Email │
│                 │                                  │                       │
│   Portal Form ──┘                                  ▼                       │
│                                          ┌─────────────────┐               │
│                                          │  Path A / B / C │               │
│                                          └─────────────────┘               │
│                                                                            │
│   Path A = AI has the answer (resolve immediately)                         │
│   Path B = KB can't answer, human team investigates, AI drafts later       │
│   Path C = AI unsure, workflow pauses until a human reviewer corrects it   │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Application Startup

```
┌────────────────────────────────────────────────────────────────────────┐
│  STARTUP WIRING  (uvicorn main:app)                                    │
├────────────────────────────────────────────────────────────────────────┤
│  FILES : main.py → app/factory.py → app/lifespan.py                    │
│                                                                        │
│  INPUT :  .env settings loaded by config/settings.py                   │
│                                                                        │
│  DOES  :  1. LoggingSetup.configure()    (structlog, IST timestamps)   │
│           2. create_app()                 (FastAPI instance)           │
│           3. Register middleware + routers + OpenAPI Bearer schema     │
│           4. lifespan() on startup:                                    │
│              ┌─ connect PostgresConnector (SSH tunnel → RDS)           │
│              ├─ create SalesforceConnector, S3, SQS, EventBridge       │
│              ├─ create LLMGateway, GraphAPIConnector, ServiceNow       │
│              ├─ build PortalIntakeService, EmailDashboardService,      │
│              │    TriageService, EpisodicMemoryWriter, ClosureService │
│              └─ asyncio.create_task( SlaMonitor.start_monitor_loop )  │
│                 asyncio.create_task( AutoCloseScheduler.start_loop )  │
│                                                                        │
│  OUTPUT:  app.state.<connector|service>  reachable from every route   │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Entry Point 1 — Email Path

### 3.1 Trigger

```
┌──────────────────────────┐         ┌──────────────────────────────┐
│ Microsoft Graph Webhook  │         │ Reconciliation Poller        │
│  POST /webhooks/ms-graph │         │  services/polling.py         │
│  (real-time, ~5 s)       │         │  every 5 min → unread msgs   │
└────────────┬─────────────┘         └──────────────┬───────────────┘
             │                                      │
             └──────────────┬───────────────────────┘
                            ▼
              EmailIntakeService.process_email(message_id)
```

### 3.2 Inside `EmailIntakeService.process_email()`

File: [src/services/email_intake/service.py](../src/services/email_intake/service.py)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  EmailIntakeService.process_email(message_id)                            │
├──────────────────────────────────────────────────────────────────────────┤
│  INPUT : message_id (Exchange Online ID), optional correlation_id        │
│                                                                          │
│  DOES  (10 steps, CRIT = failure → SQS retry, NON = log & continue):     │
│                                                                          │
│    ┌─ E2.1  CRIT  check_idempotency()    ──▶ skip if duplicate           │
│    │                                                                     │
│    ▼                                                                     │
│    ┌─ E1    CRIT  GraphAPI.fetch_email()          ─▶ raw email dict      │
│    │                                                                     │
│    ▼                                                                     │
│    ┌─ E2.2  CRIT  EmailParser.parse_email_fields()                       │
│    │              ─▶ subject / body / sender / conversation_id / refs    │
│    │                                                                     │
│    ▼                                                                     │
│    ┌─ E2.5  NON   VendorIdentifier.identify_vendor()                     │
│    │              3-step fallback: email → body extract → fuzzy name     │
│    │                                                                     │
│    ▼                                                                     │
│    ┌─ E2.1b CRIT  EmailRelevanceFilter.evaluate()                        │
│    │              drops auto-replies / hello-only / unknown senders      │
│    │                                                                     │
│    ▼                                                                     │
│    ┌─ E2.7  CRIT  IdGenerator.generate_query_id()   → VQ-YYYY-NNNN       │
│    │              IdGenerator.generate_execution_id()                    │
│    │                                                                     │
│    ▼                                                                     │
│    ┌─ E2.3  NON   EmailStorage.store_raw_email() → S3 inbound-emails/    │
│    │                                                                     │
│    ▼                                                                     │
│    ┌─ E2.4  NON   AttachmentProcessor.process_attachments()              │
│    │              PDF/XLSX/DOCX → extracted_text + S3 upload             │
│    │                                                                     │
│    ▼                                                                     │
│    ┌─ E2.6  NON   ThreadCorrelator.determine_thread_status()             │
│    │              ▸ NEW / EXISTING_OPEN / REPLY_TO_CLOSED                │
│    │                                                                     │
│    ▼                                                                     │
│    ┌─ E2.8  CRIT  EmailStorage.store_email_metadata()                    │
│    │              + store_attachment_metadata() + create_case_execution()│
│    │                                                                     │
│    ▼                                                                     │
│    ┌─ E2.9a NON   EventBridge.publish_event("EmailParsed")               │
│    │                                                                     │
│    ▼                                                                     │
│    └─ E2.9b CRIT  SQS.send_message(email-intake-queue, UnifiedPayload)   │
│                                                                          │
│    If thread_status ∈ {EXISTING_OPEN, REPLY_TO_CLOSED}:                  │
│        → ClosureService.detect_confirmation() / handle_reopen() (§10)    │
│                                                                          │
│  OUTPUT: ParsedEmailPayload (or None for duplicates / rejected)          │
│          + message sitting on vqms-email-intake-queue                    │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Entry Point 2 — Portal Path

```
┌──────────────────────────────────────────────────────────────────────────┐
│  POST /queries  →  PortalIntakeService.submit_query()                    │
├──────────────────────────────────────────────────────────────────────────┤
│  FILE : src/services/portal_submission.py                                │
│                                                                          │
│  INPUT : QuerySubmission { query_type, subject, description, priority,   │
│                            reference_number }                            │
│          vendor_id  (from JWT header — NEVER from body)                  │
│                                                                          │
│  DOES  :                                                                 │
│    1. idempotency_key = SHA-256(vendor_id:subject:description)           │
│    2. check_idempotency()   → raise DuplicateQueryError on clash         │
│    3. Generate query_id (VQ-YYYY-NNNN), execution_id, sla_deadline       │
│    4. INSERT workflow.case_execution   (status = RECEIVED)               │
│    5. INSERT intake.portal_queries     (submission details)              │
│    6. EventBridge.publish_event("QueryReceived")         [non-critical]  │
│    7. SQS.send_message(query-intake-queue, UnifiedPayload) [best effort] │
│                                                                          │
│  OUTPUT: UnifiedQueryPayload  → route returns {query_id, status, ts}     │
│          + message on vqms-query-intake-queue                            │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 5. The Bridge — SQS Consumer

```
┌──────────────────────────────────────────────────────────────────────────┐
│  PipelineConsumer.process_message()                                      │
├──────────────────────────────────────────────────────────────────────────┤
│  FILE : src/orchestration/sqs_consumer.py                                │
│                                                                          │
│  INPUT : SQS message { body = UnifiedQueryPayload | resume_message }     │
│                                                                          │
│  DOES  :                                                                 │
│    1. Build initial PipelineState dict:                                  │
│         { query_id, correlation_id, execution_id, source,                │
│           unified_payload, status = "RECEIVED", created_at, updated_at } │
│    2. If body has resume_context → copy into state                       │
│       (lets the graph re-enter for Step 15 or triage resume)             │
│    3. compiled_graph.ainvoke(initial_state)                              │
│    4. On success: sqs.delete_message() ; on failure: leave in queue      │
│       (3 retries → DLQ by SQS config)                                    │
│                                                                          │
│  OUTPUT: final PipelineState after the graph runs                        │
└──────────────────────────────────────────────────────────────────────────┘

     Two long-polling loops running concurrently:
     ┌──────────────────────────┐      ┌──────────────────────────┐
     │ vqms-email-intake-queue  │      │ vqms-query-intake-queue  │
     └──────────────────────────┘      └──────────────────────────┘
                    │                              │
                    └──────────────┬───────────────┘
                                   ▼
                     PipelineConsumer (asyncio.gather)
```

---

## 6. LangGraph Full Pipeline Diagram

File: [src/orchestration/graph.py](../src/orchestration/graph.py)

```
                               ┌───────────┐
                               │   START   │
                               └─────┬─────┘
                                     ▼
                               ┌───────────┐
                               │  [entry]  │  (no-op passthrough)
                               └─────┬─────┘
                                     │
                  resume_context.action == "prepare_resolution" ?
                                     │
                ┌────────────── NO ──┴── YES ──────────────┐
                ▼                                          ▼
       ┌──────────────────┐                    ┌─────────────────────────┐
       │ context_loading  │                    │ resolution_from_notes   │
       │   (Step 7)       │                    │   (Step 15 / Path B)    │
       └────────┬─────────┘                    └────────────┬────────────┘
                ▼                                           │
       ┌──────────────────┐                                 │
       │  query_analysis  │                                 │
       │   (Step 8 LLM#1) │                                 │
       └────────┬─────────┘                                 │
                ▼                                           │
       ┌──────────────────┐                                 │
       │ confidence_check │                                 │
       │   (Gate 0.85)    │                                 │
       └────────┬─────────┘                                 │
                │                                           │
       path = "C"?                                          │
        │                                                   │
        ├── YES ──▶┌──────────┐ ──▶ END  (workflow paused) │
        │         │  triage  │                              │
        │         └──────────┘                              │
        NO                                                   │
        ▼                                                    │
       ┌──────────────────┐                                 │
       │     routing      │                                 │
       │   (Step 9A)      │                                 │
       └────────┬─────────┘                                 │
                ▼                                           │
       ┌──────────────────┐                                 │
       │    kb_search     │                                 │
       │  (Step 9B pgvec) │                                 │
       └────────┬─────────┘                                 │
                ▼                                           │
       ┌──────────────────┐                                 │
       │  path_decision   │                                 │
       │   (KB ≥ 0.80 ?)  │                                 │
       └────────┬─────────┘                                 │
                │                                           │
       path = "A" or "B" ?                                  │
                │                                           │
     ┌── "A" ──┼── "B" ──┐                                  │
     ▼                   ▼                                  │
┌──────────┐     ┌──────────────────┐                       │
│resolution│     │  acknowledgment  │                       │
│(Step 10A)│     │   (Step 10B)     │                       │
└────┬─────┘     └────────┬─────────┘                       │
     │                    │                                 │
     └─────────┬──────────┘                                 │
               ▼                                            │
      ┌──────────────────┐  ◀────────────────────────────────┘
      │   quality_gate   │
      │   (Step 11 ×7)   │
      └────────┬─────────┘
               ▼
      ┌──────────────────┐
      │     delivery     │
      │   (Step 12)      │
      └────────┬─────────┘
               ▼
            ┌──────┐
            │ END  │
            └──────┘
```

---

## 7. Every Node — Input / Does / Output

Every node has one method: `async def execute(state: PipelineState) -> PipelineState`.
LangGraph **merges** the returned partial state into the running state.

### 7.1 ContextLoadingNode (Step 7)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  ContextLoadingNode                                                      │
│  FILE: src/orchestration/nodes/context_loading.py                        │
├──────────────────────────────────────────────────────────────────────────┤
│  INPUT  (reads from state):                                              │
│     • unified_payload.vendor_id                                          │
│                                                                          │
│  DOES:                                                                   │
│     1. _load_vendor_profile(vendor_id)                                   │
│        ├─ postgres.cache_read("cache.vendor_cache", vendor_id)  (1 h)   │
│        ├─ miss → SalesforceConnector.find_vendor_by_id()                 │
│        └─ both fail → default BRONZE profile                             │
│     2. _load_episodic_memory(vendor_id)                                  │
│        └─ SELECT 5 most recent from memory.episodic_memory               │
│     3. Build VendorContext { vendor_profile, recent_interactions }       │
│                                                                          │
│  OUTPUT (writes to state):                                               │
│     • vendor_context: dict                                               │
│     • status = "ANALYZING"                                               │
└──────────────────────────────────────────────────────────────────────────┘
```

### 7.2 QueryAnalysisNode (Step 8 — THE critical node)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  QueryAnalysisNode    (8-layer defense, NEVER crashes)                   │
│  FILE: src/orchestration/nodes/query_analysis.py                         │
├──────────────────────────────────────────────────────────────────────────┤
│  INPUT  (reads from state):                                              │
│     • unified_payload.{subject, body, attachments}                       │
│     • vendor_context.{vendor_profile, recent_interactions}               │
│                                                                          │
│  DOES:                                                                   │
│     L1  Input Validation ─▶ empty body+subject → safe fallback           │
│     L2  Prompt Engineering                                               │
│         └─ PromptManager.render("query_analysis_v1.j2", ...)             │
│     L3  LLM Call                                                         │
│         └─ LLMGateway.llm_complete(prompt, temp=0.1)                     │
│     L4  Output Parsing (raw JSON → fence → first {...})                  │
│     L5  Pydantic Validation → build AnalysisResult(...)                  │
│     L6  Self-Correction (1 retry: send error + raw back to LLM)          │
│     L7  Safe Fallback (confidence=0.3 → forces Path C)                   │
│     L8  Audit logging at every layer                                     │
│                                                                          │
│  OUTPUT (writes to state):                                               │
│     • analysis_result: {                                                 │
│         intent_classification, extracted_entities,                       │
│         urgency_level, sentiment, confidence_score (0.0-1.0),            │
│         multi_issue_detected, suggested_category,                        │
│         analysis_duration_ms, model_id, tokens_in, tokens_out            │
│       }                                                                  │
└──────────────────────────────────────────────────────────────────────────┘
```

### 7.3 ConfidenceCheckNode (Decision Point 1)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  ConfidenceCheckNode                                                     │
│  FILE: src/orchestration/nodes/confidence_check.py                       │
├──────────────────────────────────────────────────────────────────────────┤
│  INPUT : analysis_result.confidence_score                                │
│                                                                          │
│  DOES  : compare vs settings.agent_confidence_threshold (0.85)           │
│                                                                          │
│  OUTPUT:                                                                 │
│     • confidence ≥ 0.85 → no change (continues to routing)               │
│     • confidence < 0.85 → processing_path = "C", status = "PAUSED"       │
│                                                                          │
│     route_after_confidence_check() in graph.py:                          │
│        path=="C" → triage node   ; else → routing node                   │
└──────────────────────────────────────────────────────────────────────────┘
```

### 7.4 RoutingNode (Step 9A — deterministic rules, no LLM)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  RoutingNode                                                             │
│  FILE: src/orchestration/nodes/routing.py                                │
├──────────────────────────────────────────────────────────────────────────┤
│  INPUT : analysis_result.{suggested_category, urgency_level}             │
│          vendor_context.vendor_profile.tier.tier_name                    │
│                                                                          │
│  DOES  :                                                                 │
│     1. Team pick:                                                        │
│        QUERY_TYPE_TEAM_MAP[category]  or                                 │
│        CATEGORY_TEAM_MAP[lower(category)]  or  "general-support"         │
│     2. SLA hours = TIER_SLA[tier] × URGENCY_MULT[urgency]  (min 1 h)     │
│          PLAT=4  GOLD=8  SILVER=16  BRONZE=24                            │
│          CRIT=0.25  HIGH=0.5  MED=1.0  LOW=1.5                           │
│     3. Build RoutingDecision (team, SLATarget, category, priority)       │
│     4. INSERT workflow.sla_checkpoints (so SlaMonitor tracks it)         │
│                                                                          │
│  OUTPUT:                                                                 │
│     • routing_decision: dict                                             │
│     • status = "ROUTING"                                                 │
└──────────────────────────────────────────────────────────────────────────┘
```

### 7.5 KBSearchNode (Step 9B — pgvector similarity)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  KBSearchNode                                                            │
│  FILE: src/orchestration/nodes/kb_search.py                              │
├──────────────────────────────────────────────────────────────────────────┤
│  INPUT : unified_payload.{subject, body}                                 │
│                                                                          │
│  DOES  :                                                                 │
│     1. search_text = (subject + body)[:2000]                             │
│     2. embedding = LLMGateway.llm_embed(search_text)   (1536-dim)        │
│     3. SQL cosine similarity on pgvector:                                │
│          SELECT article_id, title, content_text, category,               │
│                 1 - (embedding <=> $1::vector) AS similarity_score       │
│          FROM memory.embedding_index                                     │
│          ORDER BY embedding <=> $1::vector  LIMIT $2                     │
│     4. has_sufficient_match = any score ≥ 0.80                           │
│                                                                          │
│  OUTPUT:                                                                 │
│     • kb_search_result: {                                                │
│         matches: [KBArticleMatch × N],                                   │
│         best_match_score, has_sufficient_match,                          │
│         search_duration_ms, query_embedding_model                        │
│       }                                                                  │
└──────────────────────────────────────────────────────────────────────────┘
```

### 7.6 PathDecisionNode (Decision Point 2)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  PathDecisionNode                                                        │
│  FILE: src/orchestration/nodes/path_decision.py                          │
├──────────────────────────────────────────────────────────────────────────┤
│  INPUT : kb_search_result                                                │
│                                                                          │
│  DOES  : has_sufficient_match  AND  top match content ≥ 100 chars ?      │
│                                                                          │
│  OUTPUT:                                                                 │
│     • YES → processing_path = "A" , status = "DRAFTING"                  │
│     • NO  → processing_path = "B" , status = "DRAFTING",                 │
│             routing_decision.requires_human_investigation = True         │
└──────────────────────────────────────────────────────────────────────────┘
```

### 7.7 ResolutionNode (Step 10A — Path A only, LLM Call #2)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  ResolutionNode — drafts the FULL answer email                           │
│  FILE: src/orchestration/nodes/resolution.py                             │
├──────────────────────────────────────────────────────────────────────────┤
│  INPUT : vendor_context, analysis_result, kb_search_result,              │
│          unified_payload, routing_decision                               │
│                                                                          │
│  DOES  :                                                                 │
│     1. Build kb_articles list from kb_search_result.matches              │
│     2. PromptManager.render("resolution_v1.j2", vendor, intent,          │
│                             entities, kb_articles, ticket="PENDING",     │
│                             sla_statement_by_tier)                       │
│     3. LLMGateway.llm_complete(prompt, temp=0.3)                         │
│     4. Parse JSON (raw → fence → braces)                                 │
│     5. Build DraftResponse (draft_type="RESOLUTION")                     │
│                                                                          │
│  OUTPUT:                                                                 │
│     • draft_response: {                                                  │
│         draft_type:"RESOLUTION", subject, body,                          │
│         confidence, sources:[...], model_id, tokens_in, tokens_out       │
│       }                                                                  │
│     • status = "VALIDATING"                                              │
└──────────────────────────────────────────────────────────────────────────┘
```

### 7.8 AcknowledgmentNode (Step 10B — Path B only)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  AcknowledgmentNode — drafts an ack-ONLY email (no answer!)              │
│  FILE: src/orchestration/nodes/acknowledgment.py                         │
├──────────────────────────────────────────────────────────────────────────┤
│  INPUT : vendor_context, analysis_result, routing_decision,              │
│          unified_payload                                                 │
│                                                                          │
│  DOES  :                                                                 │
│     1. PromptManager.render("acknowledgment_v1.j2", vendor, intent,      │
│                             ticket="PENDING", sla_statement,             │
│                             assigned_team)                               │
│     2. LLMGateway.llm_complete(prompt, temp=0.3)                         │
│     3. Parse JSON → build DraftResponse (sources ALWAYS empty)           │
│                                                                          │
│  OUTPUT:                                                                 │
│     • draft_response: {draft_type:"ACKNOWLEDGMENT", ...sources:[]}       │
│     • status = "VALIDATING"                                              │
└──────────────────────────────────────────────────────────────────────────┘
```

### 7.9 QualityGateNode (Step 11 — 7 deterministic checks)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  QualityGateNode — validates every outbound draft                        │
│  FILE: src/orchestration/nodes/quality_gate.py                           │
├──────────────────────────────────────────────────────────────────────────┤
│  INPUT : draft_response, processing_path                                 │
│                                                                          │
│  DOES  : Run 7 checks on draft.body                                      │
│     [1] Ticket #     : contains "PENDING" OR /INC-?\d{7,}/               │
│     [2] SLA wording  : priority / service agreement / reviewing / ...    │
│     [3] Sections     : greeting + next-steps + closing                   │
│     [4] Restricted   : blocks "jira" "slack channel" "TODO" ...          │
│     [5] Length       : 50 ≤ word_count ≤ 500                             │
│     [6] Citations    : Path A + RESOLUTION → sources must be non-empty   │
│     [7] PII scan     : SSN / 16-digit card regex (Phase 8 → Comprehend)  │
│                                                                          │
│  OUTPUT:                                                                 │
│     • quality_gate_result: {                                             │
│         passed (bool), checks_run=7, checks_passed,                      │
│         failed_checks: [..labels..], redraft_count, max_redrafts=2       │
│       }                                                                  │
│     • status = "DELIVERING"   on pass                                    │
│       status = "DRAFT_REJECTED" on fail                                  │
└──────────────────────────────────────────────────────────────────────────┘
```

### 7.10 DeliveryNode (Step 12 — two modes)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  DeliveryNode — ServiceNow ticket + Graph email                          │
│  FILE: src/orchestration/nodes/delivery.py                               │
├──────────────────────────────────────────────────────────────────────────┤
│  INPUT : draft_response, routing_decision, vendor_context,               │
│          unified_payload, (ticket_info + resolution_mode for Step 15)    │
│                                                                          │
│  DOES  (normal mode, A or B first delivery):                             │
│     1. _create_ticket() → ServiceNow.create_ticket()  → INC0010042       │
│     2. Replace "PENDING" in subject + body with real ticket number       │
│     3. _send_email() → GraphAPI.send_email(to, subject, html, reply_to)  │
│     4. Path A: ClosureService.register_resolution_sent()                 │
│                (starts 5-business-day auto-close timer)                  │
│     5. Status = "RESOLVED" (Path A) or "AWAITING_RESOLUTION" (Path B)    │
│                                                                          │
│  DOES  (resolution_mode=True, Step 15 re-entry):                         │
│     1. Reuse existing ticket_info.ticket_number (no new ticket)          │
│     2. Replace "PENDING" and send email                                  │
│     3. ServiceNow.update_ticket_status("AWAITING_VENDOR_CONFIRMATION")   │
│     4. EventBridge.publish_event("ResolutionPrepared")                   │
│     5. ClosureService.register_resolution_sent()                         │
│     6. Status = "RESOLVED"                                               │
│                                                                          │
│  OUTPUT:                                                                 │
│     • ticket_info: dict (ticket_id, query_id, status, sla_deadline...)   │
│     • status (see above)                                                 │
└──────────────────────────────────────────────────────────────────────────┘
```

### 7.11 TriageNode (Path C entry — workflow pauses)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  TriageNode — builds the human-review package                            │
│  FILE: src/orchestration/nodes/triage.py                                 │
├──────────────────────────────────────────────────────────────────────────┤
│  INPUT : analysis_result, unified_payload                                │
│                                                                          │
│  DOES  :                                                                 │
│     1. Generate callback_token (uuid4)                                   │
│     2. Build package dict: { original_query, analysis_result,            │
│        confidence_breakdown, suggested_routing, suggested_draft, ... }   │
│     3. INSERT workflow.triage_packages (status=PENDING)                  │
│     4. UPDATE workflow.case_execution SET status='PAUSED', path='C'      │
│     5. EventBridge.publish_event("HumanReviewRequired") [non-critical]   │
│                                                                          │
│  OUTPUT:                                                                 │
│     • triage_package: dict                                               │
│     • status = "PAUSED"                                                  │
│     • Graph reaches END — workflow sleeps until reviewer acts            │
└──────────────────────────────────────────────────────────────────────────┘
```

### 7.12 ResolutionFromNotesNode (Step 15 — Path B second LLM call)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  ResolutionFromNotesNode — drafts resolution from human notes            │
│  FILE: src/orchestration/nodes/resolution_from_notes.py                  │
├──────────────────────────────────────────────────────────────────────────┤
│  INPUT : ticket_info.ticket_number, vendor_context, analysis_result,     │
│          unified_payload                                                 │
│                                                                          │
│  DOES  :                                                                 │
│     1. ServiceNow.get_work_notes(ticket_number) → human investigation    │
│     2. PromptManager.render("resolution_from_notes_v1.j2", vendor,       │
│        intent, ticket, sla_statement, work_notes)                        │
│     3. LLMGateway.llm_complete(prompt, temp=0.3)   [LLM Call #3 Path B]  │
│     4. Parse JSON → build DraftResponse (draft_type="RESOLUTION")        │
│                                                                          │
│  OUTPUT:                                                                 │
│     • draft_response: RESOLUTION draft                                   │
│     • work_notes: string (for audit)                                     │
│     • status = "VALIDATING"                                              │
│     • Graph continues to quality_gate → delivery (resolution_mode=True)  │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 8. Adapter Layer — External-System Connectors

Every node and service calls **adapters**, never boto3/httpx/msal directly.

```
┌─────────────────────┬──────────────────────────────────────────────────┐
│  Adapter            │  What it does                                    │
├─────────────────────┼──────────────────────────────────────────────────┤
│  LLMGateway         │  Routes llm_complete / llm_embed to Bedrock      │
│                     │  (primary) with OpenAI fallback                  │
│  BedrockConnector   │  Claude 3.5 Messages API + Titan Embed v2        │
│                     │  Retries on Throttling / ServiceUnavailable      │
│  OpenAIConnector    │  Optional fallback (only if OPENAI_API_KEY set)  │
│  GraphAPIConnector  │  MSAL auth + email fetch/send + webhooks         │
│                     │  (client + 3 mixins in adapters/graph_api/)      │
│  SalesforceConnector│  Vendor lookup (email→body→fuzzy) + account CRUD │
│  ServiceNowConnector│  create_ticket, get_ticket, get_work_notes,      │
│                     │  update_ticket_status                            │
│  S3Connector        │  upload / download / exists / list               │
│                     │  single bucket vqms-data-store, prefix-organized │
│  SQSConnector       │  send / receive (long-poll) / delete             │
│  EventBridge        │  publish_event (20 event types)                  │
│  PostgresConnector  │  SSH tunnel + asyncpg pool                       │
│                     │  check_idempotency, cache_read/write, fetch...   │
└─────────────────────┴──────────────────────────────────────────────────┘
```

---

## 9. Path A — End-to-End Happy Path

```
  Vendor Email (invoice question)
         │
         ▼
┌─────────────────────────┐
│ EmailIntakeService      │  10-step intake
│ → SQS email-intake      │
└────────────┬────────────┘
             ▼
┌─────────────────────────┐
│ PipelineConsumer        │  builds initial PipelineState
└────────────┬────────────┘
             ▼
┌─────────────────────────┐
│ context_loading         │  vendor profile + last 5 memories
└────────────┬────────────┘
             ▼
┌─────────────────────────┐
│ query_analysis (LLM #1) │  confidence = 0.93   (>= 0.85)
└────────────┬────────────┘
             ▼
┌─────────────────────────┐
│ confidence_check        │  PASS → continue
└────────────┬────────────┘
             ▼
┌─────────────────────────┐
│ routing                 │  team=finance-ops, SLA=8h (GOLD×MEDIUM)
└────────────┬────────────┘
             ▼
┌─────────────────────────┐
│ kb_search               │  top match 0.91 on KB-INV-001
└────────────┬────────────┘
             ▼
┌─────────────────────────┐
│ path_decision           │  Path A (KB good, 100+ char content)
└────────────┬────────────┘
             ▼
┌─────────────────────────┐
│ resolution (LLM #2)     │  full answer email, ticket="PENDING"
└────────────┬────────────┘
             ▼
┌─────────────────────────┐
│ quality_gate            │  7/7 pass
└────────────┬────────────┘
             ▼
┌─────────────────────────┐
│ delivery                │  ServiceNow INC0010042, email sent,
│                         │  register_resolution_sent (5-day timer)
│                         │  status = RESOLVED
└────────────┬────────────┘
             ▼
          ┌──────┐
          │ END  │
          └──────┘
```

---

## 10. Path B — End-to-End (Two Round Trips)

```
  Vendor Email / Portal submission
              │
              ▼
   ───── FIRST PASS THROUGH THE GRAPH ─────
              │
              ▼
┌─────────────────────────────────────────┐
│ context_loading → query_analysis        │
│   confidence = 0.90  (high)             │
└─────────────┬───────────────────────────┘
              ▼
┌─────────────────────────────────────────┐
│ confidence_check PASS → routing         │
└─────────────┬───────────────────────────┘
              ▼
┌─────────────────────────────────────────┐
│ kb_search  (best score 0.52)            │
│ path_decision → Path B  (KB too weak)   │
└─────────────┬───────────────────────────┘
              ▼
┌─────────────────────────────────────────┐
│ acknowledgment  (LLM Call #2)           │
│   "Hi vendor, we received your query,   │
│    ticket PENDING, team reviewing."     │
└─────────────┬───────────────────────────┘
              ▼
┌─────────────────────────────────────────┐
│ quality_gate → delivery                 │
│   ServiceNow INC0010099, email sent     │
│   status = AWAITING_RESOLUTION          │
└─────────────┬───────────────────────────┘
              ▼
           ┌──────┐     (SLA monitor now watches the deadline)
           │ END  │
           └──────┘

       ... human team investigates in ServiceNow ...
       ... writes work_notes, marks RESOLVED ...

  POST /webhooks/servicenow {ticket_id, status=RESOLVED}
              │
              ▼
┌─────────────────────────────────────────┐
│ servicenow_webhook():                   │
│   lookup query_id from ticket_link      │
│   build resume_message with             │
│   resume_context.action="prepare_..."   │
│   SQS.send → query-intake-queue         │
└─────────────┬───────────────────────────┘
              ▼
   ───── SECOND PASS THROUGH THE GRAPH ─────
              │
              ▼
┌─────────────────────────────────────────┐
│ entry switch sees "prepare_resolution"  │
│   → routes straight to Step 15          │
└─────────────┬───────────────────────────┘
              ▼
┌─────────────────────────────────────────┐
│ resolution_from_notes (LLM Call #3)     │
│   fetch ServiceNow work_notes           │
│   draft resolution email                │
└─────────────┬───────────────────────────┘
              ▼
┌─────────────────────────────────────────┐
│ quality_gate → delivery (resolution_    │
│   mode=True): reuse ticket, send email, │
│   flip SN to AWAITING_VENDOR_CONFIRM,   │
│   publish ResolutionPrepared, start     │
│   auto-close timer. status = RESOLVED   │
└─────────────┬───────────────────────────┘
              ▼
           ┌──────┐
           │ END  │
           └──────┘
```

---

## 11. Path C — Paused → Human Reviewer → Resume

```
  Query arrives (low-confidence)
             │
             ▼
┌─────────────────────────────────────┐
│ query_analysis → confidence = 0.61  │
└───────────────┬─────────────────────┘
                ▼
┌─────────────────────────────────────┐
│ confidence_check → path = "C"       │
│                    status = PAUSED  │
└───────────────┬─────────────────────┘
                ▼
┌─────────────────────────────────────┐
│ TriageNode                          │
│   INSERT workflow.triage_packages   │
│   UPDATE case_execution → PAUSED    │
│   publish HumanReviewRequired       │
└───────────────┬─────────────────────┘
                ▼
             ┌──────┐    ... workflow sleeps ...
             │ END  │
             └──────┘

       HTTP calls by the reviewer portal:
       ┌────────────────────────────────────────────┐
       │ GET  /triage/queue          (list pending) │
       │ GET  /triage/{query_id}     (full package) │
       │ POST /triage/{query_id}/review             │
       └───────────────────┬────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────┐
│ TriageService.submit_decision(query_id, decision)   │
│   1. INSERT workflow.reviewer_decisions              │
│   2. UPDATE triage_packages → REVIEWED               │
│   3. Merge corrections into analysis_result          │
│      → confidence_score = 1.0  (human validated)    │
│   4. UPDATE case_execution with corrected analysis   │
│   5. SQS.send_message(query-intake-queue,            │
│        resume_message { resume_context.from_triage })│
│   6. publish HumanReviewCompleted                    │
└─────────────────────────┬───────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────┐
│ PipelineConsumer processes resume message           │
│ Graph runs again; confidence now = 1.0              │
│ → confidence_check PASS → routing → ...             │
│ → finishes as Path A or Path B like a normal query  │
└─────────────────────────────────────────────────────┘
```

---

## 12. Background Loops (Always Running)

### 12.1 SlaMonitor

```
┌──────────────────────────────────────────────────────────────────────────┐
│  SlaMonitor.start_monitor_loop()   (every sla_monitor_interval_seconds)  │
│  FILE: src/services/sla_monitor.py                                       │
├──────────────────────────────────────────────────────────────────────────┤
│  INPUT : workflow.sla_checkpoints (rows with last_status='ACTIVE')       │
│                                                                          │
│  DOES per row:                                                           │
│     elapsed_pct = (now - started) / (deadline - started)                 │
│     Pick HIGHEST uncrossed threshold:                                    │
│        ≥ 95 %  &  !l2_fired      → SLAEscalation95                       │
│        ≥ 85 %  &  !l1_fired      → SLAEscalation85                       │
│        ≥ 70 %  &  !warning_fired → SLAWarning70                          │
│     EventBridge.publish_event(event_type, {...})                         │
│     IF publish succeeded: UPDATE <flag_column> = TRUE                    │
│                                                                          │
│  OUTPUT: EventBridge events + flipped _fired flags                       │
└──────────────────────────────────────────────────────────────────────────┘
```

### 12.2 ClosureService

```
┌──────────────────────────────────────────────────────────────────────────┐
│  ClosureService (no loop — called by others)                             │
│  FILE: src/services/closure.py                                           │
├──────────────────────────────────────────────────────────────────────────┤
│  register_resolution_sent(query_id)                                      │
│     • called by DeliveryNode after a resolution email ships              │
│     • INSERT closure_tracking, auto_close_deadline = +5 business days    │
│                                                                          │
│  detect_confirmation(conversation_id, body_text)                         │
│     • called by EmailIntakeService on EXISTING_OPEN / REPLY_TO_CLOSED    │
│     • lowercase substring match vs settings.confirmation_keywords        │
│     • on hit → close_case("VENDOR_CONFIRMED")                            │
│                                                                          │
│  handle_reopen(conversation_id, new_query_id)                            │
│     • for non-confirmation replies on closed threads                     │
│     • inside closure_reopen_window_days → flip prior to AWAITING_RES     │
│     • outside window → link new_query_id ← prior_query_id                │
│                                                                          │
│  close_case(query_id, reason)                                            │
│     [CRIT] UPDATE case_execution.status='CLOSED'                         │
│     [CRIT] UPDATE closure_tracking (closed_at, reason)                   │
│     [NON ] ServiceNow.update_ticket_status("Closed")                     │
│     [NON ] EventBridge.publish_event("TicketClosed")                     │
│     [NON ] EpisodicMemoryWriter.save_closure()                           │
└──────────────────────────────────────────────────────────────────────────┘
```

### 12.3 AutoCloseScheduler

```
┌──────────────────────────────────────────────────────────────────────────┐
│  AutoCloseScheduler.start_loop() (hourly by default)                     │
│  FILE: src/services/auto_close_scheduler.py                              │
├──────────────────────────────────────────────────────────────────────────┤
│  INPUT : SELECT from workflow.closure_tracking                           │
│          WHERE closed_at IS NULL  AND  auto_close_deadline <= now        │
│                                                                          │
│  DOES  : for each row → ClosureService.close_case(AUTO_CLOSED)           │
│                                                                          │
│  OUTPUT: number of cases auto-closed this tick                           │
└──────────────────────────────────────────────────────────────────────────┘
```

### 12.4 EpisodicMemoryWriter

```
┌──────────────────────────────────────────────────────────────────────────┐
│  EpisodicMemoryWriter.save_closure()                                     │
│  FILE: src/services/episodic_memory.py                                   │
├──────────────────────────────────────────────────────────────────────────┤
│  INPUT : query_id, reason (VENDOR_CONFIRMED/AUTO_CLOSED/...)             │
│                                                                          │
│  DOES  :                                                                 │
│     1. SELECT vendor_id, processing_path, analysis_result                │
│        FROM workflow.case_execution WHERE query_id=$1                    │
│     2. Build one-line summary: "<intent> for <vendor>: <path> - <reason>"│
│     3. INSERT memory.episodic_memory                                     │
│                                                                          │
│  OUTPUT: memory_id                                                       │
│                                                                          │
│  READ-SIDE: ContextLoadingNode._load_episodic_memory reads top 5 of     │
│             these for every new query from the same vendor              │
│             → closes the long-term memory loop                          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 13. HTTP Request Authentication

```
┌──────────────────────────────────────────────────────────────────────────┐
│  AuthMiddleware  (pure ASGI middleware)                                  │
│  FILE: src/api/middleware/auth_middleware.py                             │
├──────────────────────────────────────────────────────────────────────────┤
│  SKIP : /health  /auth/login  /docs  /openapi.json  /redoc  /webhooks/   │
│                                                                          │
│  ON every other request:                                                 │
│     1. Read Authorization: Bearer <JWT>                                  │
│     2. services.auth.validate_token()                                    │
│        ├─ decode JWT (HS256, JWT_SECRET_KEY)                             │
│        ├─ check blacklist in cache.kv_store                              │
│        └─ raise on expired / invalid                                     │
│     3. Attach username / role / tenant to scope["state"]                 │
│     4. services.auth.refresh_token_if_expiring()                         │
│        → on near-expiry, add X-New-Token response header                 │
│                                                                          │
│  LOGIN  path:                                                            │
│     POST /auth/login → authenticate_user()                               │
│        SELECT from tbl_users → werkzeug.check_password_hash              │
│        → issue JWT { username, role, tenant, exp }                       │
│                                                                          │
│  LOGOUT path:                                                            │
│     POST /auth/logout → blacklist_token() stores jti in kv_store with TTL│
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 14. PipelineState — The Shared Dictionary

Every node reads from and writes to this single dict.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  PipelineState  (TypedDict, total=False)                                 │
│  FILE: src/models/workflow.py                                            │
├──────────────────────────────────────────────────────────────────────────┤
│  Set at entry  ┌ query_id, correlation_id, execution_id, source          │
│  (sqs_consumer)│ unified_payload, status, created_at, updated_at         │
│                └ resume_context?,  resolution_mode?,  ticket_info?       │
│                                                                          │
│  context_loading   ──▶  vendor_context                                   │
│  query_analysis    ──▶  analysis_result                                  │
│  confidence_check  ──▶  processing_path="C" ? status="PAUSED"            │
│  routing           ──▶  routing_decision, status="ROUTING"               │
│  kb_search         ──▶  kb_search_result                                 │
│  path_decision     ──▶  processing_path = "A" | "B"                      │
│  resolution        ──▶  draft_response (RESOLUTION)                      │
│  acknowledgment    ──▶  draft_response (ACKNOWLEDGMENT)                  │
│  quality_gate      ──▶  quality_gate_result, status                      │
│  delivery          ──▶  ticket_info, status = RESOLVED / AWAITING_...    │
│  triage            ──▶  triage_package, status = "PAUSED"                │
│  resolution_from_notes ──▶  draft_response, work_notes                   │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 15. How Imports, Classes and `def`s Work (Beginner's Guide)

This section explains the Python mechanics the codebase uses, with real
examples lifted from the files themselves.

### 15.1 How Imports Work

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Why we can write  `from models.email import ParsedEmailPayload`         │
│  instead of  `from src.models.email import ParsedEmailPayload`           │
├──────────────────────────────────────────────────────────────────────────┤
│  In main.py — BEFORE any project import:                                 │
│                                                                          │
│      sys.path.insert(0, ".")        # so "config.settings" works         │
│      sys.path.insert(0, "src")      # so "models.email" works            │
│                                                                          │
│  pyproject.toml also sets:                                               │
│      [tool.pytest.ini_options] pythonpath = ["src"]                      │
│                                                                          │
│  Result: Python treats `src/` as a root. Every subdirectory with an      │
│  __init__.py becomes an importable package.                              │
│                                                                          │
│      src/                                                                │
│      ├── models/              → import models.email                      │
│      ├── services/            → import services.portal_submission        │
│      ├── adapters/            → import adapters.bedrock                  │
│      ├── orchestration/       → import orchestration.graph               │
│      └── ...                                                             │
└──────────────────────────────────────────────────────────────────────────┘
```

### 15.2 Three Styles of Import You'll See

```
┌──────────────────────────────────────────────────────────────────────────┐
│  A)  from __future__ import annotations                                  │
│      └─ first line in almost every file. Lets us write `list[str]`,      │
│         `dict | None`, etc. on Python 3.12 without runtime cost.         │
│                                                                          │
│  B)  from <package> import <Class>                                       │
│      from adapters.bedrock import BedrockConnector                       │
│      from models.workflow import PipelineState                           │
│      └─ the normal case                                                  │
│                                                                          │
│  C)  Lazy import (inside a function/method body)                         │
│      def connect(self):                                                  │
│          from db.connection import PostgresConnector   # imported here  │
│      └─ used when we want to delay loading an optional dependency        │
│         (e.g. OpenAIConnector only if OPENAI_API_KEY is set)             │
└──────────────────────────────────────────────────────────────────────────┘
```

### 15.3 Folder Modules (Package with Mixins)

A "folder module" is a directory with an `__init__.py` that combines several
small files into one public class. Used for adapters that got too big.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Example: src/adapters/graph_api/                                        │
├──────────────────────────────────────────────────────────────────────────┤
│   adapters/graph_api/                                                    │
│   ├── client.py          class GraphAPIClient       (MSAL auth)          │
│   ├── email_fetch.py     class EmailFetchMixin      (fetch_email)        │
│   ├── email_send.py      class EmailSendMixin       (send_email)         │
│   ├── webhook.py         class WebhookMixin         (subscribe_webhook)  │
│   └── __init__.py        class GraphAPIConnector (combines all mixins)   │
│                                                                          │
│   __init__.py contains:                                                  │
│     from adapters.graph_api.client      import GraphAPIClient            │
│     from adapters.graph_api.email_fetch import EmailFetchMixin           │
│     from adapters.graph_api.email_send  import EmailSendMixin            │
│     from adapters.graph_api.webhook     import WebhookMixin              │
│                                                                          │
│     class GraphAPIConnector(GraphAPIClient, EmailFetchMixin,             │
│                             EmailSendMixin, WebhookMixin):               │
│         def __init__(self, settings): super().__init__(settings)         │
│                                                                          │
│   The rest of the codebase just does:                                    │
│     from adapters.graph_api import GraphAPIConnector                     │
│   and never needs to know the class is split across 4 files.             │
└──────────────────────────────────────────────────────────────────────────┘
```

### 15.4 How Classes Are Built — The Repeating Recipe

Every service, node and adapter follows the same 4-line recipe.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  class SomeThing:                                                        │
│      """One-line summary. What this class is responsible for."""         │
│                                                                          │
│      def __init__(self, dep_a, dep_b, settings):                         │
│          self._dep_a    = dep_a                                          │
│          self._dep_b    = dep_b                                          │
│          self._settings = settings                                       │
│                                                                          │
│      async def do_the_work(self, *args, correlation_id: str = ""):       │
│          ... uses self._dep_a, self._dep_b ...                           │
│          return result                                                   │
└──────────────────────────────────────────────────────────────────────────┘

 • __init__ only stores dependencies. No I/O, no heavy lifting.
 • Dependencies are INJECTED (passed in), never imported-and-instantiated
   inside the class. This is what makes every class unit-testable with
   simple mocks.
 • Private attributes start with a single underscore: self._postgres
 • Public methods get a short docstring explaining args + returns.
```

### 15.5 Where the Dependencies Come From

The "injection" part happens in exactly one place: `app/lifespan.py`.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  app/lifespan.py  ─── the ONE file that knows how to build everything    │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  settings = get_settings()                     ← reads .env              │
│                                                                          │
│  postgres   = PostgresConnector(settings); await postgres.connect()      │
│  salesforce = SalesforceConnector(settings)                              │
│  sqs        = SQSConnector(settings)                                     │
│  eventbridge= EventBridgeConnector(settings)                             │
│  llm        = LLMGateway(settings)                                       │
│  graph_api  = GraphAPIConnector(settings)                                │
│  servicenow = ServiceNowConnector(settings)                              │
│                                                                          │
│  # services receive the connectors they need                             │
│  portal_intake = PortalIntakeService(                                    │
│      postgres=postgres, sqs=sqs, eventbridge=eventbridge,                │
│      settings=settings,                                                  │
│  )                                                                       │
│                                                                          │
│  # attach everything to app.state so request handlers can reach it       │
│  application.state.postgres       = postgres                             │
│  application.state.portal_intake  = portal_intake                        │
│  ...                                                                     │
│                                                                          │
│  Route handlers later do:                                                │
│      postgres = request.app.state.postgres                               │
│      portal_intake = request.app.state.portal_intake                     │
└──────────────────────────────────────────────────────────────────────────┘
```

### 15.6 How `def` and `async def` Differ

```
┌──────────────────────────────────────────────────────────────────────────┐
│  def            — a normal Python function. Runs synchronously.          │
│                   Use for pure logic: parsing, validation, formatting.   │
│                                                                          │
│  async def      — a coroutine. Must be awaited. Use for anything that    │
│                   waits on I/O (DB, HTTP, AWS, LLM, SQS, file).          │
│                                                                          │
│  Rule of thumb in this project:                                          │
│     If the function talks to an adapter, it is `async def` and every     │
│     caller up the stack is also `async def` and uses `await`.            │
│                                                                          │
│  Example chain (all async):                                              │
│                                                                          │
│     POST /queries         (async def submit_query)                       │
│       └─ await portal_intake.submit_query(...)       (async def)         │
│            └─ await self._postgres.execute(...)      (async def)         │
│            └─ await self._sqs.send_message(...)      (async def)         │
└──────────────────────────────────────────────────────────────────────────┘
```

### 15.7 Every Pipeline Node Looks the Same

LangGraph nodes are just Python classes with one `execute()` method.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  class SomeNode:                                                         │
│      def __init__(self, ...deps, settings):                              │
│          self._dep = ...                                                 │
│                                                                          │
│      async def execute(self, state: PipelineState) -> PipelineState:     │
│          # 1. READ   values from state                                   │
│          vendor_id = state.get("unified_payload", {}).get("vendor_id")   │
│                                                                          │
│          # 2. WORK   (call LLM / DB / rules / ...)                       │
│          result = await self._dep.do_something(vendor_id)                │
│                                                                          │
│          # 3. RETURN partial state update                                │
│          return {                                                        │
│              "some_key": result,                                         │
│              "status": "SOMETHING",                                      │
│              "updated_at": TimeHelper.ist_now().isoformat(),             │
│          }                                                               │
│                                                                          │
│  LangGraph takes the dict you returned and MERGES it into the running    │
│  PipelineState. You never mutate state in-place.                         │
└──────────────────────────────────────────────────────────────────────────┘
```

### 15.8 Decorators You Will See

```
┌──────────────────────────────────────────────────────────────────────────┐
│  @log_api_call           wraps a FastAPI route handler; extracts         │
│                          correlation_id from headers, logs entry/exit    │
│                                                                          │
│  @log_service_call       wraps a method on a service/adapter/node;       │
│                          logs args (redacted), duration, errors          │
│                                                                          │
│  @log_llm_call           wraps an LLM factory call; enriches the log     │
│                          with token counts, cost_usd, model_id           │
│                                                                          │
│  @log_policy_decision    wraps a decision function (confidence check,    │
│                          routing) and logs the chosen branch             │
│                                                                          │
│  @retry (tenacity)       used in BedrockConnector to auto-retry on       │
│        wait_exponential, stop_after_attempt(3),                          │
│        retry_if_exception(_is_retryable_bedrock_error)                   │
│                                                                          │
│  @router.get("/queries") @router.post("/auth/login") etc.                │
│                          standard FastAPI route decorators               │
│                                                                          │
│  FILE: src/utils/decorators/  (folder module with api/service/llm/policy)│
└──────────────────────────────────────────────────────────────────────────┘
```

### 15.9 Pydantic Models vs TypedDict — Which to Use When

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Pydantic BaseModel    used at system boundaries where we need           │
│                        validation: request bodies, LLM outputs, DB row   │
│                        shapes. Example: AnalysisResult, DraftResponse.   │
│                                                                          │
│                        class AnalysisResult(BaseModel):                  │
│                            model_config = ConfigDict(frozen=True)        │
│                            confidence_score: float = Field(ge=0.0, le=1) │
│                            ...                                           │
│                                                                          │
│  TypedDict             used for PipelineState because LangGraph's        │
│                        StateGraph requires a TypedDict (not a Pydantic   │
│                        model). Every field is optional (total=False) so  │
│                        nodes can add fields incrementally.               │
│                                                                          │
│                        class PipelineState(TypedDict, total=False):      │
│                            query_id: str                                 │
│                            analysis_result: dict | None                  │
│                            ...                                           │
│                                                                          │
│  Rule of thumb:                                                          │
│     • Inside the graph, work with dicts (state["key"]).                  │
│     • At the edges (intake APIs, LLM parsing), validate with Pydantic.   │
│     • To move a Pydantic model into state, call .model_dump() first.    │
└──────────────────────────────────────────────────────────────────────────┘
```

### 15.10 Putting It All Together — One Concrete Walk

```
┌──────────────────────────────────────────────────────────────────────────┐
│  A vendor clicks "Submit" on the portal. How every piece fits:           │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  1. FastAPI route file:  src/api/routes/queries.py                       │
│                                                                          │
│        @router.post("/queries", status_code=201)                         │
│        @log_api_call                                                     │
│        async def submit_query(request, submission, x_vendor_id):         │
│            portal_intake = request.app.state.portal_intake               │
│            payload = await portal_intake.submit_query(                   │
│                submission, x_vendor_id,                                  │
│            )                                                             │
│            return {"query_id": payload.query_id, ...}                    │
│                                                                          │
│     Imports used:                                                        │
│        from fastapi import APIRouter, Header, HTTPException, Request     │
│        from models.query import QuerySubmission                          │
│        from utils.decorators import log_api_call                         │
│                                                                          │
│  2. The service (already built at startup by lifespan.py):               │
│                                                                          │
│        class PortalIntakeService:                                        │
│            def __init__(self, postgres, sqs, eventbridge, settings):     │
│                self._postgres    = postgres                              │
│                self._sqs         = sqs                                   │
│                self._eventbridge = eventbridge                           │
│                self._settings    = settings                              │
│                                                                          │
│            @log_service_call                                             │
│            async def submit_query(self, submission, vendor_id, ...):     │
│                is_new = await self._postgres.check_idempotency(...)      │
│                ...                                                       │
│                await self._sqs.send_message(...)                         │
│                return payload                                            │
│                                                                          │
│  3. Behind the SQS queue, PipelineConsumer (started elsewhere) pulls     │
│     the message and calls compiled_graph.ainvoke(initial_state).         │
│     The graph then calls each node's .execute(state) in turn.            │
│                                                                          │
│  Three lessons:                                                          │
│     • Route handlers are thin: pull dep from app.state, await it, return │
│     • Services own business logic and compose adapters                   │
│     • Adapters own the boto3/httpx/msal details; nobody else touches'em  │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 16. Quick File Map — "Where Do I Open for…"

```
┌─────────────────────────────────────┬───────────────────────────────────┐
│  I want to understand / change …    │  Open …                           │
├─────────────────────────────────────┼───────────────────────────────────┤
│  How the app starts                 │  main.py, app/factory.py,         │
│                                     │  app/lifespan.py                  │
│  Email 10-step intake               │  src/services/email_intake/       │
│                                     │    service.py                     │
│  Portal intake                      │  src/services/portal_submission.py│
│  State-machine topology             │  src/orchestration/graph.py       │
│  Node wiring / DI                   │  src/orchestration/dependencies.py│
│  SQS → pipeline bridge              │  src/orchestration/sqs_consumer.py│
│  A specific node                    │  src/orchestration/nodes/<x>.py   │
│  LLM / embedding calls              │  src/adapters/llm_gateway.py      │
│                                     │  src/adapters/bedrock.py          │
│  Email fetch / send / webhook       │  src/adapters/graph_api/          │
│  Vendor lookup                      │  src/adapters/salesforce/         │
│  Tickets / work notes               │  src/adapters/servicenow/         │
│  Pgvector, idempotency, cache       │  src/db/connection/queries.py     │
│  S3 / SQS / EventBridge             │  src/storage/s3_client.py         │
│                                     │  src/queues/sqs.py                │
│                                     │  src/events/eventbridge.py        │
│  JWT auth                           │  src/api/middleware/auth_middlew… │
│                                     │  src/services/auth.py             │
│  SLA monitor background             │  src/services/sla_monitor.py      │
│  Closure / reopen / auto-close      │  src/services/closure.py          │
│                                     │  src/services/auto_close_schedu…  │
│  Long-term memory                   │  src/services/episodic_memory.py  │
│  Path C reviewer workflow           │  src/services/triage.py           │
│                                     │  src/api/routes/triage.py         │
│  Path B re-entry from ServiceNow    │  src/api/routes/webhooks.py       │
└─────────────────────────────────────┴───────────────────────────────────┘
```

---

## 17. Rules of the Road (Invariants)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  1.  Every node returns a PARTIAL PipelineState update. LangGraph        │
│      merges it into the running state.                                   │
│                                                                          │
│  2.  All external I/O goes through an adapter — no boto3 / httpx /       │
│      msal / jwt imports inside nodes or services.                        │
│                                                                          │
│  3.  correlation_id travels with every call, bound to structlog          │
│      contextvars at the entry point.                                     │
│                                                                          │
│  4.  Idempotency is ALWAYS INSERT ... ON CONFLICT DO NOTHING.            │
│      Never "SELECT then INSERT".                                         │
│                                                                          │
│  5.  "PENDING" is the ticket-number placeholder in every draft;          │
│      DeliveryNode substitutes the real INCxxxxxxx.                       │
│                                                                          │
│  6.  Critical step fails → propagate → SQS retries → DLQ (3 attempts).   │
│      Non-critical step fails → log warning → continue with safe default. │
│                                                                          │
│  7.  0.85 is the Path-C gate (confidence).                               │
│      0.80 + 100 chars is the Path-A gate (KB).                           │
│                                                                          │
│  8.  The system NEVER creates AWS resources from code.                   │
│      Everything is pre-provisioned; we only read/write.                  │
└──────────────────────────────────────────────────────────────────────────┘
```
