# VQMS System Flow Guide — Technical Walkthrough

A step-by-step guide to how the VQMS (Vendor Query Management System)
works under the hood. Written in simple language with ASCII diagrams.

Last updated: 2026-04-16

---

## What Does VQMS Do? (One Paragraph)

A vendor sends an email asking "Where is my invoice payment?"
VQMS automatically picks up that email, figures out who the vendor is,
understands what they are asking, searches a knowledge base for answers,
and either replies with a resolution OR creates a support ticket for the
human team. No human touches it unless the AI is unsure.

---

## The Big Picture

```
  VENDOR                           VQMS SYSTEM                         EXTERNAL SERVICES
 --------                    ----------------------                   ------------------

                     +------------------------------------------+
  Email  ---------->|  EMAIL INTAKE (10 steps)                  |----> Microsoft Graph API
  (Outlook)         |  Fetch, parse, identify vendor, store     |----> Salesforce CRM
                     +------------------+-----------------------+----> AWS S3 (storage)
                                        |                       |----> PostgreSQL (database)
                                        | SQS Message           |----> AWS EventBridge (events)
                                        v
                     +------------------------------------------+
                     |  AI PIPELINE (LangGraph State Machine)   |
                     |                                          |
                     |  Step 7:  Load vendor context             |----> Salesforce + PostgreSQL
                     |  Step 8:  Analyze query (LLM Call #1)    |----> Bedrock Claude / OpenAI
                     |  Step 9A: Route to team + set SLA        |      (pure logic)
                     |  Step 9B: Search knowledge base          |----> pgvector (PostgreSQL)
                     |  Step 10: Draft response (LLM Call #2)   |----> Bedrock Claude / OpenAI
                     |  Step 11: Quality checks                 |      (pure logic)
                     |  Step 12: Send reply + create ticket     |----> ServiceNow + Graph API
                     +------------------------------------------+
                                        |
                                        v
  Vendor  <-------  Reply email with answer or acknowledgment
```

---

## Part 1: External Services — Why We Use Each One

Before diving into the flow, here is what each external service does
and why we need it.

```
+---------------------+--------------------------------------------------+
| SERVICE             | WHY WE USE IT                                    |
+---------------------+--------------------------------------------------+
| Microsoft Graph API | Read emails from the shared mailbox              |
|                     | Send reply emails back to vendors                |
|                     | (It is Microsoft's API for Outlook/Exchange)     |
+---------------------+--------------------------------------------------+
| PostgreSQL (RDS)    | Store everything: email metadata, vendor cache,  |
|                     | pipeline state, idempotency keys, KB embeddings  |
|                     | (It is our single database — no Redis needed)    |
+---------------------+--------------------------------------------------+
| pgvector extension  | Vector similarity search inside PostgreSQL       |
|                     | (Finds KB articles that match the vendor's       |
|                     |  question using math, not keyword matching)      |
+---------------------+--------------------------------------------------+
| AWS S3              | Store raw email JSON and attachment files         |
|                     | (Cheap, durable file storage — like a hard       |
|                     |  drive in the cloud)                             |
+---------------------+--------------------------------------------------+
| AWS SQS             | Queue messages between intake and AI pipeline     |
|                     | (Decouples the two so they can run at different  |
|                     |  speeds — like a to-do list between two teams)   |
+---------------------+--------------------------------------------------+
| AWS EventBridge     | Broadcast events like "EmailParsed" or           |
|                     | "AnalysisCompleted" for audit and monitoring     |
|                     | (Like a news ticker — other systems can listen)  |
+---------------------+--------------------------------------------------+
| Amazon Bedrock      | Run Claude AI model for understanding queries    |
|                     | and drafting responses (LLM = Large Language     |
|                     | Model, the brain of the system)                  |
+---------------------+--------------------------------------------------+
| OpenAI (GPT-4o)     | Backup if Bedrock is down or unavailable         |
|                     | (Fallback brain — same job, different company)   |
+---------------------+--------------------------------------------------+
| Salesforce CRM      | Look up vendor details: who is this sender?      |
|                     | What tier are they? (Customer database)          |
+---------------------+--------------------------------------------------+
| ServiceNow          | Create support tickets for the human team        |
|                     | (IT ticketing system — like Jira for IT ops)     |
+---------------------+--------------------------------------------------+
| SSH Tunnel (Bastion)| Secure path from our laptop to the RDS database  |
|                     | (RDS is locked inside AWS VPC — we tunnel in     |
|                     |  through a bastion server using a PEM key)       |
+---------------------+--------------------------------------------------+
```

---

## Part 2: Project File Structure — Where Code Lives

```
vqm_ps/                              <-- Project root
|
+-- config/                           <-- Settings and constants
|   +-- settings.py                       Loads .env into Python (65+ config fields)
|   +-- s3_paths.py                       S3 bucket path builder (no hardcoded paths)
|
+-- src/
|   +-- models/                       <-- Data shapes (Pydantic models)
|   |   +-- email.py                      ParsedEmailPayload, EmailAttachment
|   |   +-- query.py                      QuerySubmission (portal), UnifiedQueryPayload
|   |   +-- workflow.py                   AnalysisResult, PipelineState (LangGraph state)
|   |   +-- vendor.py                     VendorMatch, VendorProfile
|   |   +-- ticket.py                     TicketCreateRequest, RoutingDecision
|   |   +-- memory.py                     KBArticleMatch, KBSearchResult, EpisodicMemoryEntry
|   |   +-- communication.py             DraftResponse, QualityGateResult
|   |   +-- triage.py                    TriagePackage, ReviewerDecision (Path C)
|   |   +-- auth.py                      LoginRequest, LoginResponse, TokenPayload
|   |   +-- email_dashboard.py           Dashboard API response models
|   |
|   +-- services/                     <-- Business logic
|   |   +-- email_intake/                 [FOLDER MODULE] 10-step email ingestion pipeline
|   |   |   +-- __init__.py                  Exports: EmailIntakeService
|   |   |   +-- service.py                   Main orchestrator class
|   |   |   +-- parser.py                    MIME parsing, header extraction, body cleanup
|   |   |   +-- attachment_processor.py      Attachment validation, text extraction
|   |   |   +-- vendor_identifier.py         Vendor identification from sender
|   |   |   +-- thread_correlator.py         Thread correlation: In-Reply-To, References
|   |   |   +-- storage.py                   S3 raw email storage + PostgreSQL metadata
|   |   +-- email_dashboard/              [FOLDER MODULE] Dashboard query service
|   |   |   +-- __init__.py                  Exports: EmailDashboardService
|   |   |   +-- service.py                   Main facade class
|   |   |   +-- mappings.py                  Status/category mapping constants
|   |   |   +-- queries.py                   Database query builders
|   |   |   +-- formatters.py                Response formatting and serialization
|   |   +-- portal_submission.py          Portal query submission
|   |   +-- auth.py                       JWT login, logout, token validation
|   |   +-- attachment_manifest.py        Attachment metadata builder
|   |   +-- polling.py                    Reconciliation polling (missed emails)
|   |
|   +-- adapters/                     <-- External service adapters
|   |   +-- bedrock.py                    Amazon Bedrock (Claude AI + embeddings)
|   |   +-- openai_llm.py                OpenAI (GPT-4o fallback)
|   |   +-- llm_gateway.py               Routes LLM calls: Bedrock first, OpenAI fallback
|   |   +-- graph_api/                    [FOLDER MODULE] Microsoft Graph API
|   |   |   +-- __init__.py                  Exports: GraphAPIConnector
|   |   |   +-- client.py                    MSAL auth, token management
|   |   |   +-- email_fetch.py               Fetch emails: GET /messages
|   |   |   +-- email_send.py                Send emails: POST /sendMail
|   |   |   +-- webhook.py                   Webhook subscription + large attachments
|   |   +-- salesforce/                   [FOLDER MODULE] Salesforce CRM
|   |   |   +-- __init__.py                  Exports: SalesforceAdapter
|   |   |   +-- client.py                    Auth, session, helpers
|   |   |   +-- vendor_lookup.py             Vendor search by ID/email/name
|   |   |   +-- account_operations.py        Account CRUD
|   |   +-- servicenow/                   [FOLDER MODULE] ServiceNow ITSM
|   |       +-- __init__.py                  Exports: ServiceNowConnector
|   |       +-- client.py                    Lazy httpx client, shared helpers
|   |       +-- ticket_create.py             Create ticket (POST /api/now/table/incident)
|   |       +-- ticket_query.py              Get ticket, work notes, update status
|   |
|   +-- orchestration/               <-- AI pipeline (LangGraph)
|   |   +-- graph.py                      Wires all nodes into a state machine
|   |   +-- sqs_consumer.py              Pulls messages from SQS, feeds the pipeline
|   |   +-- dependencies.py              Creates adapters, injects into nodes
|   |   +-- studio.py                     LangGraph Studio integration
|   |   +-- nodes/
|   |   |   +-- context_loading.py        Step 7:  Load vendor profile + history
|   |   |   +-- query_analysis.py         Step 8:  LLM Call #1 (intent, urgency, confidence)
|   |   |   +-- confidence_check.py       Gate:    >= 0.85 continue, < 0.85 Path C
|   |   |   +-- routing.py               Step 9A: Assign team + SLA (deterministic rules)
|   |   |   +-- kb_search.py             Step 9B: Vector search in knowledge base
|   |   |   +-- path_decision.py         Gate:    KB match >= 0.80? Path A or Path B
|   |   |   +-- resolution.py            Step 10A: Path A — draft resolution from KB (LLM #2)
|   |   |   +-- acknowledgment.py        Step 10B: Path B — draft acknowledgment only (LLM #2)
|   |   |   +-- quality_gate.py          Step 11:  7-check validation on every draft
|   |   |   +-- delivery.py              Step 12:  ServiceNow ticket + Graph API email send
|   |   +-- prompts/
|   |       +-- prompt_manager.py         Prompt loading and versioning
|   |       +-- query_analysis_v1.j2      Jinja2 prompt template for Step 8
|   |       +-- resolution_v1.j2          Jinja2 prompt template for Step 10A
|   |       +-- acknowledgment_v1.j2      Jinja2 prompt template for Step 10B
|   |
|   +-- db/                           <-- Database
|   |   +-- connection/                   [FOLDER MODULE] PostgreSQL connector
|   |   |   +-- __init__.py                  Exports: PostgresConnector
|   |   |   +-- client.py                    SSH tunnel, asyncpg pool, connect/disconnect
|   |   |   +-- queries.py                   Execute, fetch, idempotency, cache read/write
|   |   |   +-- health.py                    Health check, run migrations
|   |   +-- migrations/                   11 SQL files (schemas, tables, indexes)
|   |
|   +-- queues/sqs.py                 <-- SQS message queue adapter
|   +-- storage/s3_client.py          <-- S3 file storage adapter
|   +-- events/eventbridge.py        <-- EventBridge event publisher
|   +-- cache/cache_client.py        <-- PostgreSQL-backed key-value cache
|   +-- api/routes/                   <-- REST API endpoints
|   +-- utils/                        <-- Helpers, exceptions, logging
|   |   +-- helpers.py                    ist_now(), IdGenerator, generate_correlation_id()
|   |   +-- logger.py                     Structured logging (structlog + JSON)
|   |   +-- exceptions.py                Domain exceptions
|   |   +-- decorators/                   [FOLDER MODULE] Logging decorators
|   |       +-- __init__.py                  Exports: log_api_call, log_service_call, etc.
|   |       +-- api.py                       @log_api_call — FastAPI route handlers
|   |       +-- service.py                   @log_service_call — service/adapter methods
|   |       +-- llm.py                       @log_llm_call — LLM factory functions
|   |       +-- policy.py                    @log_policy_decision — routing decisions
|
+-- tests/                           <-- 178+ passing tests
+-- scripts/                         <-- Utility & testing scripts
+-- docs/                            <-- Documentation (this file lives here)
```

---

## Part 3: Email Intake Pipeline (10 Steps)

This is what happens when a vendor sends an email. Every step is inside
`src/services/email_intake/` (folder module) -> `EmailIntakeService.process_email()`.

```
  Vendor sends email to vendorsupport@company.com
                        |
                        v
  +-----------------------------------------------+
  |  STEP 1: IDEMPOTENCY CHECK                    |
  |  "Have we already processed this email?"       |
  |                                                |
  |  How: INSERT into cache.idempotency_keys       |
  |       with ON CONFLICT DO NOTHING              |
  |  Why: Prevents processing the same email       |
  |       twice (webhook + polling can both         |
  |       detect it)                                |
  |                                                |
  |  If duplicate -> return None (skip)            |
  |  If new       -> continue to Step 2            |
  |  File: db/connection/ -> check_idempotency()   |
  +--------------------+------- ------------------+
                       |
                       v
  +-----------------------------------------------+
  |  STEP 2: FETCH EMAIL FROM GRAPH API            |
  |  "Go get the actual email content"             |
  |                                                |
  |  How: GET /users/{mailbox}/messages/{id}       |
  |       using MSAL OAuth2 token                  |
  |  Why: Graph API is how Microsoft lets us       |
  |       read Outlook emails programmatically     |
  |                                                |
  |  Returns: subject, body, sender, date,         |
  |           attachments, conversationId          |
  |  File: adapters/graph_api/ -> fetch_email()    |
  +--------------------+--------------------------+
                       |
                       v
  +-----------------------------------------------+
  |  STEP 3: PARSE EMAIL FIELDS                    |
  |  "Extract the useful parts"                    |
  |                                                |
  |  How: Read sender name/email, subject, body,   |
  |       received datetime, conversation ID       |
  |  Why: Raw Graph API response has nested JSON.  |
  |       We flatten it into clean fields.         |
  |                                                |
  |  Output: sender_email, sender_name, subject,   |
  |          body_text, received_at, etc.           |
  +--------------------+--------------------------+
                       |
                       v
  +-----------------------------------------------+
  |  STEP 4: GENERATE IDs                          |
  |  "Give this query a tracking number"           |
  |                                                |
  |  query_id:       VQ-2026-0042                  |
  |     (human-readable, sequential)               |
  |  correlation_id: 550e8400-e29b-41d4-a716-...   |
  |     (UUID for tracing across all services)     |
  |  execution_id:   a3f5c8d2-...                  |
  |     (UUID for this specific pipeline run)      |
  |                                                |
  |  File: utils/helpers.py -> IdGenerator         |
  +--------------------+--------------------------+
                       |
                       v
  +-----------------------------------------------+
  |  STEP 5: STORE RAW EMAIL IN S3      [non-crit]|
  |  "Save the original email as a backup"         |
  |                                                |
  |  How: Upload full email JSON to S3             |
  |  Key:  inbound-emails/VQ-2026-0042/            |
  |        raw_email.json                          |
  |  Why: Compliance + debugging. If anything      |
  |       goes wrong, we have the original.        |
  |                                                |
  |  Non-critical: if S3 fails, log warning        |
  |  and continue (email is still in Outlook)      |
  |  File: storage/s3_client.py -> upload_json()   |
  +--------------------+--------------------------+
                       |
                       v
  +-----------------------------------------------+
  |  STEP 6: PROCESS ATTACHMENTS        [non-crit]|
  |  "Extract text from PDFs, Excel, Word files"   |
  |                                                |
  |  How: For each attachment:                     |
  |    1. Check safety (no .exe, max 10MB)         |
  |    2. Decode Base64 content                    |
  |    3. Upload binary to S3                      |
  |    4. Extract text:                            |
  |       - PDF  -> pdfplumber                     |
  |       - Excel -> openpyxl                      |
  |       - Word -> python-docx                    |
  |       - CSV/TXT -> direct read                 |
  |    5. Truncate to 5000 chars max               |
  |    6. Save metadata to DB                      |
  |                                                |
  |  Why: Vendor queries often have invoices or    |
  |       POs attached. The AI needs that text     |
  |       to understand the question.              |
  |                                                |
  |  Safety limits:                                |
  |    - Max 10 attachments per email              |
  |    - Max 10 MB per file                        |
  |    - Max 50 MB total                           |
  |    - Blocked: .exe .bat .cmd .ps1 .sh .js      |
  |  File: services/email_intake/                  |
  +--------------------+--------------------------+
                       |
                       v
  +-----------------------------------------------+
  |  STEP 7: IDENTIFY VENDOR            [non-crit]|
  |  "Who sent this email?"                        |
  |                                                |
  |  How: 3-step fallback in Salesforce:           |
  |    1. Exact email match (john@acme.com)        |
  |    2. Body extraction (find company names      |
  |       in the email body text)                  |
  |    3. Fuzzy name match (partial match)         |
  |                                                |
  |  Why: We need the vendor_id to load their      |
  |       tier, history, and route correctly.      |
  |                                                |
  |  If all 3 fail: vendor_id = None              |
  |  (pipeline continues without vendor context)   |
  |  File: adapters/salesforce/ ->                 |
  |         identify_vendor()                      |
  +--------------------+--------------------------+
                       |
                       v
  +-----------------------------------------------+
  |  STEP 8: THREAD CORRELATION          [non-crit]|
  |  "Is this a new question or a reply?"          |
  |                                                |
  |  How: Check conversationId from Graph API      |
  |       against existing case_execution rows     |
  |  Result: NEW | EXISTING_OPEN | REPLY_TO_CLOSED |
  |                                                |
  |  Why: If the vendor is replying to an open     |
  |       ticket, we should link it — not create   |
  |       a brand new case.                        |
  +--------------------+--------------------------+
                       |
                       v
  +-----------------------------------------------+
  |  STEP 9: WRITE METADATA TO DATABASE  [critical]|
  |  "Save everything to PostgreSQL"               |
  |                                                |
  |  Tables written:                               |
  |    intake.email_messages  (email metadata)     |
  |    workflow.case_execution (case tracking)     |
  |    intake.email_attachments (if any)           |
  |                                                |
  |  Why: This is the permanent record. If the     |
  |       SQS message is lost, we can rebuild      |
  |       from this data.                          |
  |                                                |
  |  Critical: if DB write fails, the whole        |
  |  process fails (SQS will retry).               |
  +--------------------+--------------------------+
                       |
                       v
  +-----------------------------------------------+
  |  STEP 10: PUBLISH EVENT + ENQUEUE    [mixed]   |
  |  "Tell the world + queue for AI pipeline"      |
  |                                                |
  |  a) EventBridge: publish "EmailParsed" event   |
  |     (non-critical — just for monitoring)       |
  |                                                |
  |  b) SQS: send UnifiedQueryPayload to           |
  |     vqms-email-intake-queue                    |
  |     (critical — this triggers the AI pipeline) |
  |                                                |
  |  Why: SQS decouples intake from pipeline.      |
  |       Intake can process 100 emails/sec        |
  |       while pipeline runs at its own pace.     |
  +-----------------------------------------------+
                       |
                       v
           ParsedEmailPayload returned
           (query_id, vendor_id, subject,
            body, attachments, thread_status)
```

### Critical vs Non-Critical Steps

```
  CRITICAL (if it fails, SQS retries the whole email):
    Step 1: Idempotency check
    Step 2: Fetch from Graph API
    Step 4: Generate IDs
    Step 9: Write to database
    Step 10b: Enqueue to SQS

  NON-CRITICAL (if it fails, log warning and continue):
    Step 5: S3 raw email storage
    Step 6: Attachment processing
    Step 7: Vendor identification (continue with vendor_id=None)
    Step 8: Thread correlation (default to NEW)
    Step 10a: EventBridge event publish
```

---

## Part 4: AI Pipeline (LangGraph State Machine)

After the email is ingested and queued in SQS, the AI pipeline picks
it up. This is a state machine built with LangGraph. Each "node" is
a Python function that reads the shared state, does its work, and
writes results back to the state.

### Full Pipeline Flow

```
  SQS Message arrives (UnifiedQueryPayload)
          |
          v
  +-----------------------------------------------+
  |  STEP 7: CONTEXT LOADING                      |
  |  "Load everything we know about this vendor"   |
  |                                                |
  |  What it does:                                 |
  |    1. Look up vendor profile in PostgreSQL     |
  |       cache (1-hour TTL)                       |
  |    2. If cache miss -> fetch from Salesforce   |
  |    3. Load last 5 interactions from            |
  |       memory.episodic_memory table             |
  |    4. Set status = ANALYZING                   |
  |                                                |
  |  Why: The AI needs context to understand       |
  |       the query. A GOLD tier vendor gets        |
  |       different treatment than BRONZE.         |
  |                                                |
  |  Output: vendor_context dict in pipeline state |
  |  File: orchestration/nodes/context_loading.py  |
  +--------------------+--------------------------+
                       |
                       v
  +-----------------------------------------------+
  |  STEP 8: QUERY ANALYSIS (LLM CALL #1)         |
  |  "What is the vendor asking about?"            |
  |                                                |
  |  What it does:                                 |
  |    1. Load Jinja2 prompt template              |
  |       (query_analysis_v1.j2)                   |
  |    2. Fill template with vendor context,       |
  |       subject, body, attachment text            |
  |    3. Send to LLM (Bedrock Claude or OpenAI)   |
  |    4. Parse JSON response                      |
  |    5. Validate with Pydantic (AnalysisResult)  |
  |    6. If parsing fails -> self-correction      |
  |       (ask LLM to fix its own output)          |
  |    7. If all fails -> safe fallback            |
  |       (confidence=0, routes to human review)   |
  |                                                |
  |  Output fields:                                |
  |    intent_classification: "invoice_inquiry"    |
  |    urgency_level: LOW | MEDIUM | HIGH | CRIT   |
  |    sentiment: POSITIVE | NEUTRAL | NEGATIVE    |
  |    confidence_score: 0.0 to 1.0                |
  |    extracted_entities: {invoice_numbers: [...]} |
  |    suggested_category: "billing"               |
  |    multi_issue_detected: true/false            |
  |                                                |
  |  8 INTENT TYPES (from prompt template):        |
  |    1. invoice_inquiry                          |
  |    2. delivery_status                          |
  |    3. payment_issue                            |
  |    4. contract_question                        |
  |    5. technical_support                        |
  |    6. onboarding                               |
  |    7. compliance                               |
  |    8. general_inquiry                          |
  |                                                |
  |  LLM GATEWAY FALLBACK:                        |
  |    Primary:  Amazon Bedrock (Claude Sonnet)    |
  |    Fallback: OpenAI (GPT-4o)                   |
  |    If Bedrock fails -> clean warning log ->    |
  |    automatic switch to OpenAI (no traceback)   |
  |                                                |
  |  8-LAYER DEFENSE STRATEGY:                     |
  |    L1: Input validation (reject empty/bad)     |
  |    L2: Prompt engineering (structured output)  |
  |    L3: LLM call with retry (transient errors)  |
  |    L4: Output parsing (extract JSON)           |
  |    L5: Pydantic validation (enforce schema)    |
  |    L6: Self-correction (LLM fixes itself)      |
  |    L7: Safe fallback (low confidence default)  |
  |    L8: Audit logging (log everything)          |
  |                                                |
  |  File: orchestration/nodes/query_analysis.py   |
  +--------------------+--------------------------+
                       |
                       v
  +-----------------------------------------------+
  |  DECISION POINT 1: CONFIDENCE CHECK            |
  |  "Is the AI confident enough?"                 |
  |                                                |
  |    confidence >= 0.85  -->  CONTINUE            |
  |    confidence <  0.85  -->  PATH C (human)     |
  |                                                |
  |  THRESHOLD: 0.85                               |
  |    Configurable in .env as                     |
  |    AGENT_CONFIDENCE_THRESHOLD=0.85             |
  |    Loaded via config/settings.py               |
  |                                                |
  |  HOW CONFIDENCE IS CALCULATED:                 |
  |    The Query Analysis Agent (Step 8) asks      |
  |    the LLM to self-assess its own analysis.    |
  |    The LLM returns a float between 0.0 and     |
  |    1.0. It considers:                          |
  |    - Clarity of the query (clear question?)    |
  |    - Entity extraction success (found invoice  |
  |      numbers, PO numbers, dates?)              |
  |    - Intent match (maps to one of the 12       |
  |      VQMS query types?)                        |
  |    - Ambiguity (multiple interpretations?)     |
  |                                                |
  |    This is NOT a probability — it is the       |
  |    model's self-reported certainty about       |
  |    the structured output it produced.          |
  |                                                |
  |  EXAMPLES:                                     |
  |    "Invoice INV-2024-0891 payment is 15 days   |
  |     overdue" -> 0.92 (clear, specific) -> OK   |
  |    "We need to discuss several things about    |
  |     our account" -> 0.68 (vague) -> PATH C     |
  |    "Where is my shipment PO-7823?" -> 0.91     |
  |     (clear, specific) -> OK                    |
  |    "Something is wrong" -> 0.45 -> PATH C      |
  |                                                |
  |  HOW THE CHECK WORKS (simple):                 |
  |    1. Read confidence_score from               |
  |       analysis_result in pipeline state        |
  |    2. Compare against threshold (0.85)         |
  |    3. If >= 0.85: leave processing_path as-is  |
  |       (it continues to routing + KB search)    |
  |    4. If < 0.85: set processing_path = "C"     |
  |       and set status = "PAUSED"                |
  |                                                |
  |  Why: If the AI is unsure about what the       |
  |       vendor is asking, a human should review  |
  |       before the system acts.                  |
  |                                                |
  |  File: orchestration/nodes/confidence_check.py |
  |  Class: ConfidenceCheckNode                    |
  |  Method: execute(state) -> PipelineState       |
  +----------+------------------+-----------------+
             |                  |
    confidence >= 0.85    confidence < 0.85
             |                  |
             v                  v
         CONTINUE          +----------------------------+
             |             | PATH C: TRIAGE             |
             |             | Create TriagePackage       |
             |             | Push to human-review queue |
             |             | Workflow PAUSES            |
             |             | (nothing happens until     |
             |             |  human reviewer acts)      |
             |             |                            |
             |             | SLA NOTE: The SLA timer    |
             |             | does NOT start until the   |
             |             | reviewer completes review. |
             |             | Review time is excluded.   |
             |             |                            |
             |             | File: orchestration/       |
             |             |   graph.py ->              |
             |             |   triage_placeholder()     |
             |             | [Full impl in Phase 5]     |
             |             +----------------------------+
             |
             v
  +-----------------------------------------------+
  |  STEP 9A: ROUTING (deterministic rules)        |
  |  "Which team should handle this?"              |
  |                                                |
  |  What it does:                                 |
  |    1. Map category -> team (two-level lookup): |
  |                                                |
  |       LEVEL 1 — Official Query Type:           |
  |       (exact match on the 12 VQMS types)       |
  |       INVOICE_PAYMENT   -> finance-ops         |
  |       RETURN_REFUND     -> finance-ops         |
  |       DELIVERY_SHIPMENT -> supply-chain        |
  |       CONTRACT_QUERY    -> legal-compliance    |
  |       COMPLIANCE_AUDIT  -> legal-compliance    |
  |       TECHNICAL_SUPPORT -> tech-support        |
  |       CATALOG_PRICING   -> procurement         |
  |       PURCHASE_ORDER    -> procurement         |
  |       ONBOARDING        -> vendor-management   |
  |       QUALITY_ISSUE     -> quality-assurance   |
  |       SLA_BREACH_REPORT -> sla-compliance      |
  |       GENERAL_INQUIRY   -> general-support     |
  |                                                |
  |       LEVEL 2 — Keyword Fallback:              |
  |       (if AI returns free-text category)        |
  |       billing/invoice/payment -> finance-ops   |
  |       delivery/shipping       -> supply-chain  |
  |       contract/legal          -> legal-compli. |
  |       technical/api           -> tech-support  |
  |       catalog/pricing         -> procurement   |
  |       onboarding              -> vendor-mgmt   |
  |       quality/defect          -> quality-assur.|
  |       (no match)              -> general-supp. |
  |                                                |
  |       Type map defined in:                     |
  |         models/query.py -> QUERY_TYPE_TEAM_MAP |
  |       Keyword map defined in:                  |
  |         orchestration/nodes/routing.py         |
  |           -> CATEGORY_TEAM_MAP                 |
  |                                                |
  |    2. Calculate SLA based on vendor tier +     |
  |       urgency (formula below):                 |
  |                                                |
  |       FORMULA:                                 |
  |       SLA Hours = max(1, floor(               |
  |         Base Hours × Urgency Multiplier       |
  |       ))                                       |
  |                                                |
  |       BASE HOURS BY VENDOR TIER:               |
  |       +----------+-----------+                 |
  |       | PLATINUM | 4 hours   |                 |
  |       | GOLD     | 8 hours   |                 |
  |       | SILVER   | 16 hours  |                 |
  |       | BRONZE   | 24 hours  |                 |
  |       +----------+-----------+                 |
  |       (defined in routing.py ->                |
  |        TIER_SLA_HOURS dict)                    |
  |                                                |
  |       URGENCY MULTIPLIER:                      |
  |       +----------+------------+                |
  |       | CRITICAL | × 0.25     |                |
  |       | HIGH     | × 0.50     |                |
  |       | MEDIUM   | × 1.00     |                |
  |       | LOW      | × 1.50     |                |
  |       +----------+------------+                |
  |       (defined in routing.py ->                |
  |        URGENCY_MULTIPLIER dict)                |
  |                                                |
  |       FULL SLA MATRIX (Tier × Urgency):        |
  |       +----------+------+------+------+------+ |
  |       |          |CRIT  |HIGH  |MED   |LOW   | |
  |       +----------+------+------+------+------+ |
  |       |PLATINUM  | 1h   | 2h   | 4h   | 6h  | |
  |       |GOLD      | 2h   | 4h   | 8h   | 12h | |
  |       |SILVER    | 4h   | 8h   | 16h  | 24h | |
  |       |BRONZE    | 6h   | 12h  | 24h  | 36h | |
  |       +----------+------+------+------+------+ |
  |                                                |
  |       EXAMPLE:                                 |
  |       SteelCraft Industries (GOLD tier)        |
  |       Query urgency = HIGH                     |
  |       SLA = 8h × 0.50 = 4 hours               |
  |                                                |
  |    3. SLA ESCALATION THRESHOLDS:               |
  |       Once the SLA is set, the system          |
  |       monitors at three checkpoints:           |
  |                                                |
  |       70%  -> WARNING to assigned team         |
  |       85%  -> L1 ESCALATION to team manager    |
  |       95%  -> L2 ESCALATION to director        |
  |       100% -> SLA BREACHED, incident logged    |
  |                                                |
  |       (configurable in .env:                   |
  |        SLA_WARNING_THRESHOLD_PERCENT=70        |
  |        SLA_L1_ESCALATION_THRESHOLD_PERCENT=85  |
  |        SLA_L2_ESCALATION_THRESHOLD_PERCENT=95) |
  |                                                |
  |       Example (4-hour SLA):                    |
  |       Warning at 2h 48m (70%)                  |
  |       L1 at     3h 24m (85%)                   |
  |       L2 at     3h 48m (95%)                   |
  |       Breach at 4h 0m  (100%)                  |
  |                                                |
  |  Why: This is pure business logic, no AI.      |
  |       Rules are deterministic and auditable.   |
  |                                                |
  |  Output: RoutingDecision with team, SLA,       |
  |          priority, requires_human flag         |
  |  File: orchestration/nodes/routing.py          |
  |  Class: RoutingNode                            |
  |  Method: execute(state) -> PipelineState       |
  +--------------------+--------------------------+
                       |
                       v
  +-----------------------------------------------+
  |  STEP 9B: KB SEARCH (vector similarity)        |
  |  "Do we already have an answer in our KB?"     |
  |                                                |
  |  What it does:                                 |
  |    1. Take the vendor's question text          |
  |    2. Convert to a vector (list of 1024        |
  |       numbers) using embedding model:          |
  |       Primary: Bedrock Titan Embed v2          |
  |       Fallback: OpenAI text-embedding-3-small  |
  |    3. Search memory.embedding_index table      |
  |       using pgvector cosine similarity         |
  |       SQL: SELECT ... ORDER BY                 |
  |         embedding <=> $query_vector            |
  |       (<=> is cosine distance operator)        |
  |    4. Filter by category (billing, delivery..) |
  |    5. Return top 5 matches with scores         |
  |                                                |
  |  WHAT IS A VECTOR?                             |
  |    Text converted to a list of numbers.        |
  |    Similar questions produce similar numbers.  |
  |    "Where is my invoice?" and "Invoice status" |
  |    will have vectors close to each other.      |
  |    We compare using cosine similarity (0-1).   |
  |    1.0 = identical, 0.0 = completely unrelated.|
  |                                                |
  |  WHERE ARE VECTORS STORED?                     |
  |    PostgreSQL table: memory.embedding_index    |
  |    Columns: article_id, title, content_text,   |
  |      category, source_url,                     |
  |      embedding vector(1024), metadata JSONB    |
  |    Index: HNSW (m=16, ef_construction=64)      |
  |      for fast approximate nearest neighbor     |
  |    Defined in: db/migrations/                  |
  |      006_create_memory_tables.sql              |
  |    Seeded by: scripts/seed_knowledge_base.py   |
  |                                                |
  |  Why: If the KB has an article that answers    |
  |       the question (score >= 0.80), the AI     |
  |       can draft a full response without        |
  |       human help.                              |
  |                                                |
  |  Config:                                       |
  |    KB_MATCH_THRESHOLD=0.80 (in .env)           |
  |    KB_MAX_RESULTS=5 (in .env)                  |
  |                                                |
  |  Output: KBSearchResult with articles + scores |
  |  File: orchestration/nodes/kb_search.py        |
  |  Class: KBSearchNode                           |
  |  Method: execute(state) -> PipelineState       |
  +--------------------+--------------------------+
                       |
                       v
  +-----------------------------------------------+
  |  DECISION POINT 2: PATH DECISION              |
  |  "Can the AI answer this, or does a human     |
  |   need to investigate?"                        |
  |                                                |
  |  TWO CONDITIONS must BOTH be true for Path A: |
  |                                                |
  |  Condition 1:                                  |
  |    Best KB match score >= 0.80                 |
  |    (has_sufficient_match = True in KB result)  |
  |    Meaning: The KB article is at least 80%     |
  |    semantically similar to the query.          |
  |                                                |
  |  Condition 2:                                  |
  |    Top KB article content >= 100 characters    |
  |    (MIN_CONTENT_LENGTH constant = 100)         |
  |    Meaning: The article has substantial        |
  |    content, not just a title or one-liner.     |
  |    Short snippets are generic boilerplate,     |
  |    not actionable info for a resolution.       |
  |                                                |
  |  BOTH TRUE  -> PATH A (AI drafts resolution)  |
  |  EITHER FALSE -> PATH B (human investigates)  |
  |                                                |
  |  EXAMPLES:                                     |
  |    "Return policy for defective items?"        |
  |    -> KB score 0.89, content 450 chars         |
  |    -> BOTH conditions met -> PATH A            |
  |                                                |
  |    "Invoice INV-2024-0891 is overdue,          |
  |     where is my payment?"                      |
  |    -> KB score 0.72, content 300 chars         |
  |    -> Score too low (<0.80) -> PATH B          |
  |    (KB has general invoice info but can't      |
  |     answer about a specific payment)           |
  |                                                |
  |    "What is your return policy?"               |
  |    -> KB score 0.91, content 50 chars          |
  |    -> Content too short (<100) -> PATH B       |
  |                                                |
  |  For Path B, the routing_decision is updated   |
  |  with requires_human_investigation = True      |
  |                                                |
  |  File: orchestration/nodes/path_decision.py    |
  |  Class: PathDecisionNode                       |
  |  Method: execute(state) -> PipelineState       |
  +----------+------------------+-----------------+
             |                  |
          PATH A             PATH B
             |                  |
             v                  v
  +==================================================+
  | STEP 10A: RESOLUTION           (Path A Only)     |
  | "Draft a full answer email using KB articles"     |
  |                                                   |
  | What it does:                                     |
  |   1. Extract vendor context, KB articles,         |
  |      analysis result from pipeline state          |
  |   2. Pick SLA statement based on vendor tier:     |
  |      PLATINUM: "Our Platinum team is              |
  |                 prioritizing your request."        |
  |      GOLD:     "Your request is being handled     |
  |                 with Gold-tier priority."          |
  |      SILVER:   "We are handling your request      |
  |                 within our standard service        |
  |                 agreement."                        |
  |      BRONZE:   "We have received your request     |
  |                 and it is being processed."        |
  |   3. Render prompt template (resolution_v1.j2)    |
  |      with vendor name, tier, query, intent,       |
  |      entities, KB articles, ticket="PENDING"      |
  |   4. Call LLM (temperature=0.3, Bedrock/OpenAI)   |
  |   5. Parse JSON response (3 strategies:           |
  |      direct parse -> markdown fences -> brace     |
  |      extraction)                                  |
  |   6. Build DraftResponse dict:                    |
  |      draft_type = "RESOLUTION"                    |
  |      subject, body, confidence, sources,          |
  |      model_id, tokens_in/out, duration_ms         |
  |                                                   |
  | The body contains the ACTUAL ANSWER with          |
  | specific facts from KB articles. Uses "PENDING"   |
  | as ticket number placeholder — Delivery node      |
  | (Step 12) replaces it with real INC-XXXXXXX.      |
  |                                                   |
  | If LLM fails: status = "DRAFT_FAILED"             |
  |   (Quality gate catches this and routes           |
  |    to human review)                               |
  |                                                   |
  | File: orchestration/nodes/resolution.py           |
  | Class: ResolutionNode                             |
  | Method: execute(state) -> PipelineState           |
  | Prompt: orchestration/prompts/resolution_v1.j2    |
  +==================================================+

  +==================================================+
  | STEP 10B: ACKNOWLEDGMENT       (Path B Only)     |
  | "Draft a 'we received it' email — NO answer"     |
  |                                                   |
  | What it does:                                     |
  |   1. Extract vendor context, analysis result,     |
  |      routing decision from pipeline state         |
  |   2. Pick SLA statement (same tier-based logic    |
  |      as Resolution node)                          |
  |   3. Render prompt template                       |
  |      (acknowledgment_v1.j2)                       |
  |      with vendor name, tier, query, intent,       |
  |      ticket="PENDING", SLA statement,             |
  |      assigned team                                |
  |   4. Call LLM (temperature=0.3, Bedrock/OpenAI)   |
  |   5. Parse JSON response (same 3 strategies)      |
  |   6. Build DraftResponse dict:                    |
  |      draft_type = "ACKNOWLEDGMENT"                |
  |      sources = [] (always empty — no KB used)     |
  |                                                   |
  | IMPORTANT: This node NEVER attempts to answer     |
  | the vendor's question. It only confirms receipt,  |
  | gives the ticket number, states the SLA, and      |
  | tells the vendor a human team is investigating.   |
  |                                                   |
  | Example output:                                   |
  |   "Thank you for your query. We have created      |
  |    ticket PENDING. Our finance team is reviewing   |
  |    your request and will respond within 8 hours."  |
  |                                                   |
  | File: orchestration/nodes/acknowledgment.py       |
  | Class: AcknowledgmentNode                         |
  | Method: execute(state) -> PipelineState           |
  | Prompt: orchestration/prompts/acknowledgment_v1.j2|
  +==================================================+

            |                      |
            +----------+-----------+
                       |
                       v
  +-----------------------------------------------+
  |  STEP 11: QUALITY GATE                         |
  |  "Is this email safe to send?"                 |
  |                                                |
  |  Every outbound email (Path A resolution OR    |
  |  Path B acknowledgment) must pass ALL 7        |
  |  checks before being sent to the vendor.       |
  |                                                |
  |  7 CHECKS — DETAILED:                          |
  |                                                |
  |  CHECK 1: TICKET NUMBER                        |
  |    Look for "PENDING" or INC-XXXXXXX pattern   |
  |    in the email body.                          |
  |    Why: Every vendor email must reference      |
  |    a ticket number for tracking.               |
  |    Method: _check_ticket_number(body)          |
  |                                                |
  |  CHECK 2: SLA WORDING                          |
  |    Look for SLA keywords: "prioritizing",      |
  |    "priority", "expect", "being processed",    |
  |    "being handled", "reviewing", "actively"    |
  |    Why: Vendor needs to know their request     |
  |    is being handled per their tier.            |
  |    Method: _check_sla_wording(body)            |
  |                                                |
  |  CHECK 3: REQUIRED SECTIONS                    |
  |    Must have ALL three:                        |
  |    - Greeting: "Dear", "Hello", "Hi"           |
  |    - Next steps: "please", "if you",           |
  |      "next step"                               |
  |    - Closing: "Regards", "Thank you", "Best"   |
  |    Why: Professional email structure.           |
  |    Method: _check_required_sections(body)      |
  |                                                |
  |  CHECK 4: RESTRICTED TERMS                     |
  |    Scan for 13 banned words that should        |
  |    NEVER appear in vendor-facing emails:       |
  |    "internal only", "do not share",            |
  |    "confidential", "jira", "slack channel",    |
  |    "standup", "sprint", "backlog",             |
  |    "tech debt", "workaround", "hack",          |
  |    "TODO", "FIXME", "competitor"               |
  |    Why: Internal jargon leaking to vendors     |
  |    is unprofessional and a security risk.      |
  |    Method: _check_restricted_terms(body)       |
  |                                                |
  |  CHECK 5: WORD COUNT                           |
  |    Must be between 50 and 500 words.           |
  |    Too short = not enough info for vendor.     |
  |    Too long = vendor won't read it all.        |
  |    Method: len(body.split())                   |
  |    Constants: MIN_WORD_COUNT=50,               |
  |              MAX_WORD_COUNT=500                 |
  |                                                |
  |  CHECK 6: SOURCE CITATIONS (Path A only)       |
  |    If processing_path == "A" and               |
  |    draft_type == "RESOLUTION":                 |
  |    The draft must include KB article IDs       |
  |    in the sources list.                        |
  |    Why: Resolution emails must be traceable    |
  |    back to the KB articles they came from.     |
  |    Path B is exempt (no KB articles used).     |
  |                                                |
  |  CHECK 7: PII SCAN                             |
  |    Detect personal data patterns:              |
  |    - SSN format: XXX-XX-XXXX                   |
  |    - Credit card: 16 consecutive digits        |
  |      or groups of 4                            |
  |    Why: Never send PII in vendor emails.       |
  |    [Phase 8: Amazon Comprehend integration     |
  |     for full PII detection]                    |
  |    Method: _check_pii_stub(body)               |
  |                                                |
  |  RESULT:                                       |
  |    ALL 7 pass -> status = "DELIVERING"         |
  |      (proceed to Step 12)                      |
  |    ANY fail  -> status = "DRAFT_REJECTED"      |
  |      (re-draft up to 2 times, then             |
  |       route to human review)                   |
  |                                                |
  |  Output: quality_gate_result dict with:        |
  |    passed (bool), checks_run (7),              |
  |    checks_passed (0-7), failed_checks (list),  |
  |    redraft_count, max_redrafts (2)             |
  |                                                |
  |  File: orchestration/nodes/quality_gate.py     |
  |  Class: QualityGateNode                        |
  |  Method: execute(state) -> PipelineState       |
  +--------------------+--------------------------+
                       |
                       v
  +-----------------------------------------------+
  |  STEP 12: DELIVERY                             |
  |  "Create ticket + send the email"              |
  |                                                |
  |  Execution order:                              |
  |                                                |
  |  Phase 1 — Create ServiceNow ticket:           |
  |    POST /api/now/table/incident                |
  |    with query_id, subject, description,        |
  |    priority, assigned_team, vendor info,        |
  |    category, sla_hours                         |
  |    Returns: INC-XXXXXXX ticket number          |
  |                                                |
  |    If ticket creation fails:                   |
  |    -> status = "DELIVERY_FAILED"               |
  |    -> error = "ServiceNow ticket creation      |
  |       failed"                                  |
  |    -> Pipeline stops (can't send email         |
  |       without a ticket number)                 |
  |                                                |
  |  Phase 2 — Replace PENDING placeholder:        |
  |    Find "PENDING" in subject and body,         |
  |    replace with real INC-XXXXXXX number        |
  |                                                |
  |  Phase 3 — Send email via Graph API:           |
  |    POST /users/{mailbox}/sendMail              |
  |    with to=vendor email, subject, body_html,   |
  |    reply_to_message_id (for threading)         |
  |                                                |
  |    If vendor has no email (portal queries):    |
  |    -> Skip email send, return True             |
  |    -> Ticket was still created                 |
  |                                                |
  |    If email send fails:                        |
  |    -> status = "DELIVERY_FAILED"               |
  |    -> error = "Graph API email send failed"    |
  |    -> Ticket exists but email not sent         |
  |                                                |
  |  Phase 4 — Set final status:                   |
  |    Path A -> status = "RESOLVED"               |
  |      (AI handled it, team just monitors)       |
  |    Path B -> status = "AWAITING_RESOLUTION"    |
  |      (human team must investigate and          |
  |       resolve the ticket)                      |
  |                                                |
  |  PATH B LATER (Step 15 — not yet built):       |
  |    When team resolves the ticket in            |
  |    ServiceNow, a webhook fires.                |
  |    Communication Agent drafts a resolution     |
  |    email from the team's work notes            |
  |    (LLM Call #3). Quality gate runs again.     |
  |    Resolution email sent to vendor.            |
  |                                                |
  |  File: orchestration/nodes/delivery.py         |
  |  Class: DeliveryNode                           |
  |  Method: execute(state) -> PipelineState       |
  |  Depends on:                                   |
  |    adapters/servicenow/ -> ServiceNowConnector  |
  |    adapters/graph_api/ -> GraphAPIConnector     |
  +-----------------------------------------------+
```

---

## Part 5: The Three Processing Paths

```
                    VENDOR QUERY ARRIVES
                           |
                    Query Analysis (LLM #1)
                           |
                    Confidence Score = ?
                           |
              +------------+------------+
              |                         |
         >= 0.85                    < 0.85
              |                         |
       Routing + KB Search         PATH C
              |                    Human Review
         KB Match = ?              (workflow pauses)
              |
     +--------+--------+
     |                  |
  >= 0.80           < 0.80
     |                  |
  PATH A             PATH B
  AI Resolves        Human Investigates


  +------------------------------------------------------------------+
  | PATH A: AI-RESOLVED (happy path)                                 |
  |                                                                  |
  |   The KB has the answer. AI drafts a full resolution email       |
  |   with specific facts from KB articles. Human team only          |
  |   monitors the ticket (no investigation needed).                 |
  |                                                                  |
  |   Example: "Your invoice INV-2024-0567 was paid on March 5th    |
  |   via wire transfer. Reference number: WT-889034."              |
  |                                                                  |
  |   LLM calls: 2 (analysis + resolution)                          |
  |   Human involvement: None                                       |
  |   Typical time: ~11 seconds                                     |
  |   Typical cost: ~$0.03                                          |
  +------------------------------------------------------------------+

  +------------------------------------------------------------------+
  | PATH B: HUMAN-TEAM-RESOLVED                                     |
  |                                                                  |
  |   The KB does NOT have the answer. AI drafts an acknowledgment   |
  |   email ("we received your query, ticket is INC-XXXXX, our      |
  |   team is reviewing it"). Human team MUST investigate.           |
  |                                                                  |
  |   Later: team finds answer, marks ticket resolved, AI drafts    |
  |   a resolution email from the team's notes.                     |
  |                                                                  |
  |   Example: "Thank you for your query. We have created ticket    |
  |   INC-0042567. Our finance team is reviewing your request       |
  |   and will respond within 16 hours."                            |
  |                                                                  |
  |   LLM calls: 2-3 (analysis + ack + later resolution)            |
  |   Human involvement: Investigation team                         |
  |   Typical time: ~10 sec for ack, hours for resolution           |
  |   Typical cost: ~$0.05                                          |
  +------------------------------------------------------------------+

  +------------------------------------------------------------------+
  | PATH C: LOW-CONFIDENCE HUMAN REVIEW                              |
  |                                                                  |
  |   The AI is not confident enough (< 0.85) in its analysis.      |
  |   Workflow PAUSES entirely. A TriagePackage is created with      |
  |   the AI's best guess + confidence breakdown. A human reviewer   |
  |   corrects the classification, then the workflow RESUMES.        |
  |                                                                  |
  |   SLA clock starts AFTER review, not before.                    |
  |   No email is sent during the pause.                            |
  |                                                                  |
  |   LLM calls: same as Path A or B after review                   |
  |   Human involvement: Reviewer first, then maybe team            |
  |   Typical time: minutes to hours (reviewer availability)        |
  +------------------------------------------------------------------+
```

---

## Part 6: LangGraph State Machine (How Nodes Connect)

LangGraph is a library that runs a series of steps (nodes) in order,
with conditional branching. Think of it as a flowchart that Python
executes automatically.

```
  LANGGRAPH STATE MACHINE
  =======================

  Every node reads from and writes to a shared "PipelineState" dict.
  Each node only updates the fields it owns — it does not touch
  fields belonging to other nodes.

  PipelineState = {
      query_id:          "VQ-2026-0042"
      correlation_id:    "550e8400-..."
      execution_id:      "a3f5c8d2-..."
      source:            "email"
      unified_payload:   { ... full email data ... }
      vendor_context:    { ... from Step 7 ... }       <-- context_loading writes this
      analysis_result:   { ... from Step 8 ... }       <-- query_analysis writes this
      routing_decision:  { ... from Step 9A ... }      <-- routing writes this
      kb_search_result:  { ... from Step 9B ... }      <-- kb_search writes this
      processing_path:   "A" | "B" | "C"               <-- confidence_check / path_decision
      draft_response:    { ... from Step 10 ... }      <-- resolution / acknowledgment writes this
      quality_gate_result: { ... }                     <-- quality_gate writes this
      ticket_info:       { ... }                       <-- delivery writes this
      status:            "ANALYZING"                   <-- updated by each node
      error:             null | "reason..."            <-- set when something fails
  }


  NODE WIRING (src/orchestration/graph.py):
  (Function: build_pipeline_graph() — takes 10 node params)

  START
    |
    v
  [context_loading] ----> [query_analysis] ----> [confidence_check]
      Step 7                  Step 8             Decision Point 1
      Load vendor             LLM Call #1        confidence >= 0.85?
      profile + history       intent, urgency,
                              confidence
                                                       |
                                          +------------+------------+
                                          |                         |
                                     path != "C"              path == "C"
                                          |                         |
                                     [routing]                 [triage] --> END
                                      Step 9A                  (paused)
                                      team + SLA               Phase 5
                                          |
                                     [kb_search]
                                      Step 9B
                                      vector search
                                          |
                                    [path_decision]
                                     Decision Point 2
                                     score>=0.80 AND
                                     content>=100?
                                          |
                                 +--------+--------+
                                 |                  |
                            path == "A"        path == "B"
                                 |                  |
                           [resolution]      [acknowledgment]
                            Step 10A           Step 10B
                            Full answer        "We got it"
                            from KB            email only
                                 |                  |
                                 +--------+---------+
                                          |
                                   [quality_gate]
                                    Step 11
                                    7 checks
                                          |
                                     [delivery]
                                      Step 12
                                      ServiceNow +
                                      Graph API
                                          |
                                         END

  CONDITIONAL EDGES (the "decision functions"):
    route_after_confidence_check(state) -> "routing" or "triage"
    route_after_path_decision(state)    -> "resolution" or "acknowledgment"
    Both defined in: orchestration/graph.py
```

---

## Part 7: LLM Gateway — How Provider Fallback Works

```
  Pipeline node calls:  gateway.llm_complete("What is this about?")
                              |
                              v
                     +------------------+
                     |   LLM GATEWAY    |
                     |  (llm_gateway.py)|
                     +--------+---------+
                              |
                  Config: bedrock_with_openai_fallback
                              |
               +--------------+--------------+
               |                             |
        TRY PRIMARY                   IF PRIMARY FAILS
        (Bedrock Claude)              (catch BedrockTimeoutError)
               |                             |
               v                             v
    +-------------------+          +-------------------+
    | BEDROCK CONNECTOR |          | OPENAI CONNECTOR  |
    | (bedrock.py)      |          | (openai_llm.py)   |
    |                   |          |                   |
    | Model: Claude     |          | Model: GPT-4o     |
    | Sonnet 3.5        |          | API Key from .env |
    |                   |          |                   |
    | Retry: 3 attempts |          | Retry: 3 attempts |
    | Backoff: 1-10 sec |          | Backoff: 1-10 sec |
    +-------------------+          +-------------------+
               |                             |
               v                             v
         Return result                 Return result
    (same dict format from both providers)

  WHAT GETS LOGGED WHEN BEDROCK FAILS:

    BEFORE (old behavior):
      [error] LLM call failed
      Traceback (most recent call last):
        File "adapters/bedrock.py", line 138...
        File "adapters/bedrock.py", line 229...
        ... 30 more lines of traceback ...
      botocore.exceptions.ClientError: ResourceNotFoundException

    AFTER (current behavior):
      [warning] LLM call failed (known provider error)
                error_type=BedrockTimeoutError
                error=Bedrock model ... timed out
      [warning] Primary provider failed -- falling back to openai
```

---

## Part 8: Database Schema — Where Data Lives

```
  POSTGRESQL SCHEMAS (6 namespaces)
  =================================

  +-- intake --------------------------------+
  |                                          |
  |  email_messages                          |
  |    query_id, message_id, sender_email,   |
  |    subject, body_text, received_at,      |
  |    conversation_id, s3_raw_key           |
  |                                          |
  |  email_attachments                       |
  |    attachment_id, query_id, filename,     |
  |    content_type, size_bytes, s3_key,      |
  |    extracted_text, extraction_status      |
  +------------------------------------------+

  +-- workflow -------------------------------+
  |                                          |
  |  case_execution (central state table)    |
  |    query_id, status, source, vendor_id,  |
  |    analysis_result, routing_decision,    |
  |    processing_path, created_at           |
  +------------------------------------------+

  +-- memory ---------------------------------+
  |                                          |
  |  episodic_memory                         |
  |    vendor_id, query_id, intent,          |
  |    outcome, resolution_path              |
  |                                          |
  |  embedding_index (pgvector)              |
  |    article_id, category, title,          |
  |    content, embedding vector(1024)       |
  +------------------------------------------+

  +-- cache ----------------------------------+
  |                                          |
  |  idempotency_keys                        |
  |    key (message_id), source, created_at  |
  |    UNIQUE constraint prevents duplicates |
  |    Background cleanup: 7-day TTL         |
  |                                          |
  |  vendor_cache (1-hour TTL)               |
  |  kv_store (general cache with TTL)       |
  +------------------------------------------+

  +-- audit ----------------------------------+
  |  action_log                              |
  |    correlation_id, timestamp, actor,     |
  |    action, details                       |
  +------------------------------------------+

  +-- reporting ------------------------------+
  |  sla_metrics                             |
  |    query_id, sla_hours, elapsed,         |
  |    breached, path                        |
  +------------------------------------------+
```

---

## Part 9: S3 Bucket Structure — Where Files Live

```
  vqms-data-store/  (single bucket, prefix-organized)
  |
  +-- inbound-emails/
  |   +-- VQ-2026-0042/
  |       +-- raw_email.json             <-- Full email from Graph API
  |
  +-- attachments/
  |   +-- VQ-2026-0042/
  |       +-- att001_invoice.pdf         <-- Original file
  |       +-- att002_po_sheet.xlsx       <-- Original file
  |       +-- _manifest.json            <-- List of all attachments
  |
  +-- processed/                         <-- [Phase 4+]
  |   +-- VQ-2026-0042/
  |       +-- email_analysis.json        <-- AnalysisResult
  |       +-- response_draft.json        <-- DraftResponse
  |       +-- ticket_payload.json        <-- ServiceNow request
  |       +-- resolution_summary.json    <-- Final outcome
  |
  +-- templates/                         <-- [Phase 4+]
  |   +-- response_templates/
  |       +-- billing.json
  |       +-- delivery.json
  |
  +-- archive/                           <-- [Phase 6+]
      +-- VQ-2026-0042/
          +-- _archive_bundle.json

  All S3 keys are built by:
    config/s3_paths.py -> build_s3_key(prefix, query_id, filename)
  No hardcoded S3 paths anywhere else in the codebase.
```

---

## Part 10: What Is Built vs What Is Planned

```
  +-----------------------------------+----------+-------------------+
  | COMPONENT                         | STATUS   | PHASE             |
  +-----------------------------------+----------+-------------------+
  | Pydantic models (all 12 files)    | DONE     | Phase 1           |
  | PostgreSQL connector + SSH tunnel | DONE     | Phase 1           |
  | Database migrations (10 files)    | DONE     | Phase 1           |
  | Config/settings (65+ fields)      | DONE     | Phase 1           |
  | Utility helpers, decorators, logs | DONE     | Phase 1           |
  | Domain exceptions                 | DONE     | Phase 1           |
  +-----------------------------------+----------+-------------------+
  | Email intake (10 steps)           | DONE     | Phase 2           |
  | Portal submission                 | DONE     | Phase 2           |
  | Graph API connector               | DONE     | Phase 2           |
  | Salesforce connector              | DONE     | Phase 2           |
  | S3 connector                      | DONE     | Phase 2           |
  | SQS connector                     | DONE     | Phase 2           |
  | EventBridge connector             | DONE     | Phase 2           |
  | Attachment processing             | DONE     | Phase 2           |
  +-----------------------------------+----------+-------------------+
  | Context Loading node              | DONE     | Phase 3           |
  | Query Analysis node (8-layer)     | DONE     | Phase 3           |
  | Confidence Check node             | DONE     | Phase 3           |
  | Routing node                      | DONE     | Phase 3           |
  | KB Search node                    | DONE     | Phase 3           |
  | Path Decision node                | DONE     | Phase 3           |
  | LangGraph state machine wiring    | DONE     | Phase 3           |
  | Bedrock connector                 | DONE     | Phase 3           |
  | OpenAI connector + LLM Gateway    | DONE     | Phase 3           |
  +-----------------------------------+----------+-------------------+
  | Resolution node (Path A draft)    | DONE     | Phase 4           |
  | Acknowledgment node (Path B)      | DONE     | Phase 4           |
  | Quality Gate (7 checks)           | DONE     | Phase 4           |
  | Delivery (ServiceNow + send)      | DONE     | Phase 4           |
  | ServiceNow connector              | DONE     | Phase 4           |
  +-----------------------------------+----------+-------------------+
  | Path C triage + human review API  | STUB     | Phase 5           |
  +-----------------------------------+----------+-------------------+
  | SLA monitoring + closure          | PLANNED  | Phase 6           |
  +-----------------------------------+----------+-------------------+
  | Angular frontend portal           | PLANNED  | Phase 7           |
  +-----------------------------------+----------+-------------------+
  | E2E tests + hardening             | PLANNED  | Phase 8           |
  +-----------------------------------+----------+-------------------+
```

---

## Part 11: How to Run It

```bash
# 1. Install dependencies
uv sync

# 2. Configure environment
cp .env.copy .env
# Fill in real credentials in .env

# 3. Run database migrations
uv run python scripts/run_migrations.py

# 4. Seed the Knowledge Base (required for KB search)
uv run python scripts/seed_knowledge_base.py --clear

# 5. Test email ingestion only (real services, no AI pipeline)
uv run python scripts/test_email_ingestion.py

# 6. Test portal -> pipeline (Steps 7-11, hardcoded input, no email)
uv run python scripts/run_pipeline_to_quality_gate.py

# 7. Test full email pipeline (Email -> S3 -> SQS -> Pipeline -> Quality Gate)
uv run python scripts/run_email_to_quality_gate.py

# 8. Test portal submission from browser
uv run python scripts/test_portal_submission.py

# 9. Run unit tests
uv run pytest tests/ -q

# 10. Lint code
uv run ruff check .
```

### Script Summary

```
  +-------------------------------------------+----------------------------+
  | SCRIPT                                    | WHAT IT TESTS              |
  +-------------------------------------------+----------------------------+
  | scripts/test_email_ingestion.py           | Email intake only (10      |
  |                                           | steps, no AI pipeline)     |
  +-------------------------------------------+----------------------------+
  | scripts/run_pipeline_to_quality_gate.py   | Portal-style: hardcoded    |
  |                                           | input -> Steps 7-11        |
  |                                           | (no real email, no SQS)    |
  +-------------------------------------------+----------------------------+
  | scripts/run_email_to_quality_gate.py      | Full email pipeline:       |
  |                                           | Graph API -> Parse -> S3   |
  |                                           | -> SQS -> Steps 7-11       |
  |                                           | (real cloud services)      |
  +-------------------------------------------+----------------------------+
  | scripts/run_email_to_analysis.py          | Email -> intake -> Steps   |
  |                                           | 7-9 only (stops at path    |
  |                                           | decision, no drafting)     |
  +-------------------------------------------+----------------------------+
  | scripts/seed_knowledge_base.py            | Seeds 12 KB articles into  |
  |                                           | memory.embedding_index     |
  |                                           | with vector embeddings     |
  +-------------------------------------------+----------------------------+
  | scripts/test_portal_submission.py         | Tests POST /queries from   |
  |                                           | the Angular frontend       |
  +-------------------------------------------+----------------------------+
```

---

## Part 12: Connection Flow — How We Reach Each Service

```
  YOUR LAPTOP
      |
      |--- SSH TUNNEL (PEM key) ---> BASTION HOST ---> PostgreSQL RDS
      |                              (EC2 in VPC)     (private subnet)
      |
      |--- HTTPS (MSAL OAuth2) ---> Microsoft Graph API (Outlook emails)
      |
      |--- HTTPS (boto3 + IAM) ---> AWS S3        (file storage)
      |                         ---> AWS SQS       (message queues)
      |                         ---> AWS EventBridge (events)
      |                         ---> AWS Bedrock    (Claude AI)
      |
      |--- HTTPS (simple-salesforce) ---> Salesforce CRM (vendor data)
      |
      |--- HTTPS (openai SDK) ---> OpenAI API (GPT-4o fallback)
      |
      |--- HTTPS (httpx) ---> ServiceNow (ticket create/update)
```

---

## Part 13: Decision Paths — Complete Summary

This section brings together everything about the three processing paths
in one place with simple explanations and code references.

### How to Think About the Three Paths

```
  Think of VQMS like a hospital triage system:

  PATH A = Doctor knows the answer immediately
           (AI finds it in the knowledge base)
           "You have a cold. Take paracetamol."

  PATH B = Doctor needs to run tests first
           (AI can't find the answer, human team investigates)
           "We need to do some blood work. We'll call you."

  PATH C = Doctor isn't even sure what's wrong
           (AI is not confident in its own analysis)
           "Let me get a senior doctor to look at this."
```

### The Two Decision Points — Why Two, Not One?

The pipeline makes two separate decisions because they check different things:

```
  +-----------------------------------------------------+
  | DECISION POINT 1: "Do I understand the question?"   |
  |   Checks: AI confidence in its own analysis          |
  |   Threshold: 0.85                                    |
  |   If NO -> Path C (human reviewer corrects AI)       |
  |   If YES -> continue to Decision Point 2             |
  +-----------------------------------------------------+
                         |
                         v
  +-----------------------------------------------------+
  | DECISION POINT 2: "Do I have the answer?"           |
  |   Checks: KB article similarity + content quality    |
  |   Threshold: 0.80 score AND 100+ chars content       |
  |   If YES -> Path A (AI drafts full answer)           |
  |   If NO  -> Path B (AI says "we're on it",           |
  |             human team finds the answer)              |
  +-----------------------------------------------------+
```

**Why not combine them?** Because understanding the question and having
the answer are independent. The AI might perfectly understand "Where is
my specific payment INV-2024-0891?" (high confidence = 0.92) but the
KB doesn't have that specific invoice's payment status (low KB match).
That's Path B — not Path C.

### Code Trigger Map — Which File Does What

```
  +-------------------------------------------+-------------------------------+
  | DECISION / STEP                           | FILE -> CLASS -> METHOD       |
  +-------------------------------------------+-------------------------------+
  | Context Loading (Step 7)                  | orchestration/nodes/          |
  |                                           |   context_loading.py ->       |
  |                                           |   ContextLoadingNode.execute()|
  +-------------------------------------------+-------------------------------+
  | Query Analysis (Step 8, LLM #1)           | orchestration/nodes/          |
  |                                           |   query_analysis.py ->        |
  |                                           |   QueryAnalysisNode.execute() |
  +-------------------------------------------+-------------------------------+
  | Confidence Gate (Decision Point 1)        | orchestration/nodes/          |
  |                                           |   confidence_check.py ->      |
  |                                           |   ConfidenceCheckNode.        |
  |                                           |     execute()                 |
  +-------------------------------------------+-------------------------------+
  | Routing (Step 9A, team + SLA)             | orchestration/nodes/          |
  |                                           |   routing.py ->               |
  |                                           |   RoutingNode.execute()       |
  +-------------------------------------------+-------------------------------+
  | KB Search (Step 9B, vectors)              | orchestration/nodes/          |
  |                                           |   kb_search.py ->             |
  |                                           |   KBSearchNode.execute()      |
  +-------------------------------------------+-------------------------------+
  | Path Decision (Decision Point 2)          | orchestration/nodes/          |
  |                                           |   path_decision.py ->         |
  |                                           |   PathDecisionNode.execute()  |
  +-------------------------------------------+-------------------------------+
  | Resolution (Step 10A, Path A, LLM #2)     | orchestration/nodes/          |
  |                                           |   resolution.py ->            |
  |                                           |   ResolutionNode.execute()    |
  +-------------------------------------------+-------------------------------+
  | Acknowledgment (Step 10B, Path B, LLM #2) | orchestration/nodes/          |
  |                                           |   acknowledgment.py ->        |
  |                                           |   AcknowledgmentNode.execute()|
  +-------------------------------------------+-------------------------------+
  | Quality Gate (Step 11, 7 checks)          | orchestration/nodes/          |
  |                                           |   quality_gate.py ->          |
  |                                           |   QualityGateNode.execute()   |
  +-------------------------------------------+-------------------------------+
  | Delivery (Step 12, ticket + email)        | orchestration/nodes/          |
  |                                           |   delivery.py ->              |
  |                                           |   DeliveryNode.execute()      |
  +-------------------------------------------+-------------------------------+
  | Triage Placeholder (Path C, Phase 5)      | orchestration/graph.py ->     |
  |                                           |   triage_placeholder()        |
  +-------------------------------------------+-------------------------------+
  | Graph Wiring (all edges + conditions)     | orchestration/graph.py ->     |
  |                                           |   build_pipeline_graph()      |
  +-------------------------------------------+-------------------------------+
  | Conditional: after confidence check       | orchestration/graph.py ->     |
  |   -> "routing" or "triage"                |   route_after_confidence_     |
  |                                           |     check()                   |
  +-------------------------------------------+-------------------------------+
  | Conditional: after path decision          | orchestration/graph.py ->     |
  |   -> "resolution" or "acknowledgment"     |   route_after_path_decision() |
  +-------------------------------------------+-------------------------------+
```

### Prompt Templates — What the AI Reads

```
  +-------------------------------------------+-------------------------------+
  | TEMPLATE FILE                             | USED BY                       |
  +-------------------------------------------+-------------------------------+
  | orchestration/prompts/                    |                               |
  |   query_analysis_v1.j2                    | Step 8: Query Analysis        |
  |                                           |   Returns: intent, urgency,   |
  |                                           |   confidence, entities        |
  +-------------------------------------------+-------------------------------+
  | orchestration/prompts/                    |                               |
  |   resolution_v1.j2                        | Step 10A: Resolution (Path A) |
  |                                           |   Input: vendor, KB articles  |
  |                                           |   Returns: full answer email  |
  +-------------------------------------------+-------------------------------+
  | orchestration/prompts/                    |                               |
  |   acknowledgment_v1.j2                    | Step 10B: Acknowledgment (B)  |
  |                                           |   Input: vendor, ticket, SLA  |
  |                                           |   Returns: "we received it"   |
  +-------------------------------------------+-------------------------------+
```

### Status Transitions — What "status" Means at Each Stage

Every node updates the `status` field in PipelineState. Here is what
each status means and where it is set:

```
  STATUS TIMELINE (happy path — Path A):

  "ANALYZING"          <- context_loading sets this
       |
  "ANALYZING"          <- query_analysis keeps it
       |
  (confidence check)   <- does NOT change status if passing
       |
  "ROUTING"            <- routing sets this
       |
  (kb_search)          <- does NOT change status
       |
  "DRAFTING"           <- path_decision sets this (Path A or B)
       |
  "VALIDATING"         <- resolution/acknowledgment sets this
       |
  "DELIVERING"         <- quality_gate sets this (if passed)
       |
  "RESOLVED"           <- delivery sets this (Path A)
  or "AWAITING_RESOLUTION" <- delivery sets this (Path B)


  FAILURE STATUSES:

  "PAUSED"             <- confidence_check sets this (Path C)
  "DRAFT_FAILED"       <- resolution/acknowledgment sets this
                          (LLM call failed)
  "DRAFT_REJECTED"     <- quality_gate sets this
                          (checks failed)
  "DELIVERY_FAILED"    <- delivery sets this
                          (ServiceNow or Graph API failed)
```

### All Configurable Thresholds — Quick Reference

Every threshold below can be changed without touching code.
Just update the value in `.env` and restart.

```
  +------------------------------------+----------+---------------------------+
  | WHAT                               | VALUE    | ENV VARIABLE              |
  +------------------------------------+----------+---------------------------+
  | Confidence gate                    | 0.85     | AGENT_CONFIDENCE_THRESHOLD|
  | KB match threshold                 | 0.80     | KB_MATCH_THRESHOLD        |
  | KB max results per search          | 5        | KB_MAX_RESULTS            |
  | SLA warning                        | 70%      | SLA_WARNING_THRESHOLD_    |
  |                                    |          |   PERCENT                 |
  | SLA L1 escalation                  | 85%      | SLA_L1_ESCALATION_        |
  |                                    |          |   THRESHOLD_PERCENT       |
  | SLA L2 escalation                  | 95%      | SLA_L2_ESCALATION_        |
  |                                    |          |   THRESHOLD_PERCENT       |
  | Default SLA hours (no tier)        | 24       | SLA_DEFAULT_HOURS         |
  | LLM temperature (analysis)        | 0.1      | BEDROCK_TEMPERATURE       |
  | LLM temperature (drafting)        | 0.3      | (hardcoded in nodes)      |
  | Max LLM tokens                     | 4096     | BEDROCK_MAX_TOKENS        |
  | Embedding dimensions               | 1024     | BEDROCK_EMBEDDING_        |
  |                                    |          |   DIMENSIONS              |
  +------------------------------------+----------+---------------------------+

  NON-ENV CONSTANTS (in code files):

  +------------------------------------+----------+---------------------------+
  | WHAT                               | VALUE    | CODE FILE                 |
  +------------------------------------+----------+---------------------------+
  | Min KB content for Path A          | 100 chars| path_decision.py ->       |
  |                                    |          |   MIN_CONTENT_LENGTH      |
  | Min email word count               | 50 words | quality_gate.py ->        |
  |                                    |          |   MIN_WORD_COUNT          |
  | Max email word count               | 500 words| quality_gate.py ->        |
  |                                    |          |   MAX_WORD_COUNT          |
  | Max re-drafts before human         | 2        | quality_gate.py ->        |
  |                                    |          |   max_redrafts            |
  | Total quality checks               | 7        | quality_gate.py ->        |
  |                                    |          |   TOTAL_CHECKS            |
  | Restricted terms count             | 13 terms | quality_gate.py ->        |
  |                                    |          |   RESTRICTED_TERMS        |
  | PLATINUM base SLA                  | 4 hours  | routing.py ->             |
  |                                    |          |   TIER_SLA_HOURS          |
  | GOLD base SLA                      | 8 hours  | routing.py ->             |
  |                                    |          |   TIER_SLA_HOURS          |
  | SILVER base SLA                    | 16 hours | routing.py ->             |
  |                                    |          |   TIER_SLA_HOURS          |
  | BRONZE base SLA                    | 24 hours | routing.py ->             |
  |                                    |          |   TIER_SLA_HOURS          |
  | CRITICAL urgency multiplier        | x 0.25   | routing.py ->             |
  |                                    |          |   URGENCY_MULTIPLIER      |
  | HIGH urgency multiplier            | x 0.50   | routing.py ->             |
  |                                    |          |   URGENCY_MULTIPLIER      |
  | MEDIUM urgency multiplier          | x 1.00   | routing.py ->             |
  |                                    |          |   URGENCY_MULTIPLIER      |
  | LOW urgency multiplier             | x 1.50   | routing.py ->             |
  |                                    |          |   URGENCY_MULTIPLIER      |
  +------------------------------------+----------+---------------------------+
```

### Path A vs Path B vs Path C — Side by Side

```
  +---------------------+-----------------------+-----------------------+-----------------------+
  | ASPECT              | PATH A                | PATH B                | PATH C                |
  |                     | (AI Resolves)         | (Human Investigates)  | (Human Reviews)       |
  +---------------------+-----------------------+-----------------------+-----------------------+
  | When does it happen | Confidence >= 0.85    | Confidence >= 0.85    | Confidence < 0.85     |
  |                     | AND KB score >= 0.80  | AND KB score < 0.80   |                       |
  |                     | AND content >= 100    | OR content < 100      |                       |
  +---------------------+-----------------------+-----------------------+-----------------------+
  | LLM calls           | 2                     | 2 (+ 1 later)         | Same as A or B after  |
  |                     | (analysis +           | (analysis + ack +     | reviewer corrects     |
  |                     |  resolution)          |  resolution later)    |                       |
  +---------------------+-----------------------+-----------------------+-----------------------+
  | Email sent          | RESOLUTION            | ACKNOWLEDGMENT        | NOTHING until         |
  |                     | (full answer with     | (no answer, just      | reviewer acts         |
  |                     |  specific facts       |  "we received it,     |                       |
  |                     |  from KB articles)    |  team is reviewing")  |                       |
  +---------------------+-----------------------+-----------------------+-----------------------+
  | Ticket purpose      | Team MONITORS         | Team INVESTIGATES     | Depends on resumed    |
  |                     | (AI already answered) | (must find answer)    | path (A or B)         |
  +---------------------+-----------------------+-----------------------+-----------------------+
  | Final status        | RESOLVED              | AWAITING_RESOLUTION   | PAUSED (then          |
  |                     |                       |                       | RESOLVED or AWAITING) |
  +---------------------+-----------------------+-----------------------+-----------------------+
  | SLA starts          | At ticket creation    | At ticket creation    | AFTER reviewer acts   |
  |                     |                       |                       | (review time excluded)|
  +---------------------+-----------------------+-----------------------+-----------------------+
  | Human involvement   | None                  | Investigation team    | Reviewer first,       |
  |                     |                       |                       | then maybe team       |
  +---------------------+-----------------------+-----------------------+-----------------------+
  | KB articles used    | YES (source of facts) | NO (lacks specifics)  | Depends on resumed    |
  |                     |                       |                       | path                  |
  +---------------------+-----------------------+-----------------------+-----------------------+
  | Typical time        | ~11 seconds total     | ~10s ack, hours       | Minutes to hours      |
  |                     |                       | for resolution        | (reviewer avail.)     |
  +---------------------+-----------------------+-----------------------+-----------------------+
  | Typical cost        | ~$0.03 (2 LLM calls)  | ~$0.05 (3 LLM calls) | Same as A or B        |
  +---------------------+-----------------------+-----------------------+-----------------------+
```

### How Path B Completes (Step 15 — Future)

Path B doesn't end at the acknowledgment email. Here is the full lifecycle:

```
  Path B starts:
  +--------------------+
  | Acknowledgment     |
  | email sent to      | ---> Vendor knows we're
  | vendor             |      working on it
  +--------------------+
           |
  +--------------------+
  | ServiceNow ticket  |
  | created for HUMAN  | ---> Team sees it in their
  | INVESTIGATION      |      queue
  +--------------------+
           |
     (hours pass while team investigates)
           |
  +--------------------+
  | Team finds answer, |
  | marks ticket       | ---> ServiceNow status
  | RESOLVED with      |      changes to RESOLVED
  | work notes         |
  +--------------------+
           |
  +--------------------+
  | ServiceNow webhook | ---> "ResolutionPrepared"
  | fires back to VQMS |      event triggers
  +--------------------+
           |
  +--------------------+
  | Communication Agent| ---> LLM Call #3
  | reads team's notes,|      (drafts resolution
  | drafts resolution  |       from human notes)
  | email              |
  +--------------------+
           |
  +--------------------+
  | Quality Gate runs  | ---> Same 7 checks
  | again              |
  +--------------------+
           |
  +--------------------+
  | Resolution email   | ---> Vendor finally gets
  | sent to vendor     |      the actual answer
  +--------------------+
           |
  +--------------------+
  | Closure flow       | ---> Auto-close after 5
  | starts             |      business days if no
  +--------------------+      reply
```

### Quality Gate Failure Flow

```
  Draft email arrives at Quality Gate
           |
  +--------------------+
  | Run 7 checks       |
  +--------------------+
           |
      PASS |          FAIL
           |            |
           v            v
  +-------------+  +------------------+
  | DELIVERING  |  | DRAFT_REJECTED   |
  | (continue   |  | redraft_count=0  |
  |  to Step 12)|  +------------------+
  +-------------+           |
                    Re-draft attempt #1
                    (LLM generates new draft)
                            |
                    +------------------+
                    | Run 7 checks     |
                    +------------------+
                            |
                       PASS | FAIL
                            |   |
                            v   v
                   +------+ +------------------+
                   | OK   | | redraft_count=1  |
                   +------+ +------------------+
                                    |
                            Re-draft attempt #2 (final)
                                    |
                            +------------------+
                            | Run 7 checks     |
                            +------------------+
                                    |
                               PASS | FAIL
                                    |   |
                                    v   v
                           +------+ +------------------+
                           | OK   | | GIVE UP          |
                           +------+ | Route to HUMAN   |
                                    | REVIEW (AI tried  |
                                    | 3 times, failed) |
                                    +------------------+
```

---

## Part 14: End-to-End Example — SteelCraft Payment Overdue Email

A real trace through the pipeline for understanding:

```
  INPUT:
    From: accounts@steelcraft.in
    Subject: Payment Overdue — Invoice SCI-2026-0451
    Body: "Dear Sir, payment for invoice SCI-2026-0451
           (Rs 4,75,000) is now 15 days overdue..."
    Attachment: Payment_Reminder_SCI_V011.pdf

  STEP BY STEP:

  1. Email Intake (10 steps)
     -> Idempotency: NEW (not seen before)
     -> Graph API: fetch full email content
     -> Parse: sender=accounts@steelcraft.in,
               subject, body, date
     -> Generate IDs: query_id=VQ-2026-0795
     -> S3: store raw_email.json
     -> Attachment: extract PDF text with pdfplumber
        (4,127 chars extracted, truncated to 5000)
     -> Vendor ID: Salesforce body_extraction match
        found steelcraft -> VendorMatch(vendor_id="V011")
     -> Thread: NEW (no prior conversation)
     -> DB: write to intake.email_messages +
            workflow.case_execution
     -> SQS: enqueue to vqms-email-intake-queue

  2. Context Loading (Step 7)
     -> Load SteelCraft profile from Salesforce:
        tier=GOLD, contact="Priya Sharma"
     -> Load last 5 interactions from episodic_memory
     -> Status: ANALYZING

  3. Query Analysis (Step 8, LLM Call #1)
     -> Intent: payment_issue
     -> Urgency: HIGH (15 days overdue = urgent)
     -> Sentiment: NEGATIVE (vendor is unhappy)
     -> Confidence: 0.92 (clear, specific query)
     -> Entities: {invoice: "SCI-2026-0451",
                   amount: "Rs 4,75,000",
                   days_overdue: 15}
     -> Category: INVOICE_PAYMENT

  4. Confidence Check (Decision Point 1)
     -> 0.92 >= 0.85 -> PASS -> continue

  5. Routing (Step 9A)
     -> Category INVOICE_PAYMENT -> team: finance-ops
     -> GOLD tier (8h) x HIGH urgency (x0.50)
        = 4 hour SLA
     -> Escalation: warning at 2h48m, L1 at 3h24m,
        L2 at 3h48m

  6. KB Search (Step 9B)
     -> Embed query text -> vector(1024)
     -> Cosine search in memory.embedding_index
     -> Top match: "Invoice and Payment Procedures"
        score = 0.74 (74% similar)
     -> KB has general invoice procedures but
        NOT the specific payment status for
        SCI-2026-0451

  7. Path Decision (Decision Point 2)
     -> Best score 0.74 < 0.80 threshold
     -> PATH B (human team investigates)
     -> routing_decision updated:
        requires_human_investigation = True

  8. Acknowledgment (Step 10B, LLM Call #2)
     -> Draft acknowledgment email:
        "Dear Priya, Thank you for reaching out
         regarding invoice SCI-2026-0451. We have
         created ticket PENDING for your request.
         Our finance-ops team is prioritizing your
         request with Gold-tier priority..."
     -> draft_type = "ACKNOWLEDGMENT"
     -> sources = [] (no KB articles used)

  9. Quality Gate (Step 11)
     -> Check 1: "PENDING" found -> PASS
     -> Check 2: "prioritizing" found -> PASS
     -> Check 3: greeting + next steps + closing -> PASS
     -> Check 4: no restricted terms -> PASS
     -> Check 5: 127 words (50-500 range) -> PASS
     -> Check 6: Path B, citations not required -> PASS
     -> Check 7: no PII patterns -> PASS
     -> Result: 7/7 passed -> DELIVERING

  10. Delivery (Step 12)
      -> ServiceNow: create ticket INC-0019901
      -> Replace "PENDING" with "INC-0019901"
      -> Graph API: send email to accounts@steelcraft.in
      -> Status: AWAITING_RESOLUTION
      -> finance-ops team now investigates

  WHY PATH B (NOT PATH A)?
    The AI understood the question perfectly (confidence 0.92).
    But the KB has general invoice procedures, NOT the status
    of SteelCraft's specific invoice SCI-2026-0451. Only a
    human can check the actual payment system. The KB score
    was 0.74, below the 0.80 threshold needed for Path A.
```

---

*This document was generated from the actual codebase at `vqm_ps/`.
Every file path, class name, and method name references real code.
Last updated: 2026-04-16.*
