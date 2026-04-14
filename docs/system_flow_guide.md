# VQMS System Flow Guide — Technical Walkthrough

A step-by-step guide to how the VQMS (Vendor Query Management System)
works under the hood. Written in simple language with ASCII diagrams.

Last updated: 2026-04-13

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
|   |   +-- email_intake.py               10-step email ingestion pipeline
|   |   +-- portal_submission.py          Portal query submission
|   |   +-- auth.py                       JWT login, logout, token validation
|   |   +-- email_dashboard.py           Dashboard query service
|   |   +-- attachment_manifest.py        Attachment metadata builder
|   |   +-- polling.py                    Reconciliation polling (missed emails)
|   |
|   +-- adapters/                     <-- External service connectors
|   |   +-- bedrock.py                    Amazon Bedrock (Claude AI + embeddings)
|   |   +-- openai_llm.py                OpenAI (GPT-4o fallback)
|   |   +-- llm_gateway.py               Routes LLM calls: Bedrock first, OpenAI fallback
|   |   +-- graph_api.py                  Microsoft Graph API (email fetch/send)
|   |   +-- salesforce.py                 Salesforce CRM (vendor lookup)
|   |
|   +-- orchestration/               <-- AI pipeline (LangGraph)
|   |   +-- graph.py                      Wires all nodes into a state machine
|   |   +-- sqs_consumer.py              Pulls messages from SQS, feeds the pipeline
|   |   +-- dependencies.py              Creates connectors, injects into nodes
|   |   +-- nodes/
|   |   |   +-- context_loading.py        Step 7:  Load vendor profile + history
|   |   |   +-- query_analysis.py         Step 8:  LLM Call #1 (intent, urgency, confidence)
|   |   |   +-- confidence_check.py       Gate:    >= 0.85 continue, < 0.85 Path C
|   |   |   +-- routing.py               Step 9A: Assign team + SLA (deterministic rules)
|   |   |   +-- kb_search.py             Step 9B: Vector search in knowledge base
|   |   |   +-- path_decision.py         Gate:    KB match >= 0.80? Path A or Path B
|   |   +-- prompts/
|   |       +-- query_analysis_v1.j2      Jinja2 prompt template for Step 8
|   |
|   +-- db/                           <-- Database
|   |   +-- connection.py                 PostgreSQL connector (SSH tunnel + pool)
|   |   +-- migrations/                   10 SQL files (schemas, tables, indexes)
|   |
|   +-- queues/sqs.py                 <-- SQS message queue connector
|   +-- storage/s3_client.py          <-- S3 file storage connector
|   +-- events/eventbridge.py        <-- EventBridge event publisher
|   +-- cache/cache_client.py        <-- PostgreSQL-backed key-value cache
|   +-- api/routes/                   <-- REST API endpoints
|   +-- utils/                        <-- Helpers, exceptions, decorators, logging
|
+-- tests/                           <-- 178+ passing tests
+-- scripts/                         <-- Utility & testing scripts
+-- docs/                            <-- Documentation (this file lives here)
```

---

## Part 3: Email Intake Pipeline (10 Steps)

This is what happens when a vendor sends an email. Every step is inside
`src/services/email_intake.py` -> `EmailIntakeService.process_email()`.

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
  |  File: db/connection.py -> check_idempotency() |
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
  |  File: adapters/graph_api.py -> fetch_email()  |
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
  |  File: services/email_intake.py                |
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
  |  File: adapters/salesforce.py ->               |
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
  |  Why: If the AI is unsure about what the       |
  |       vendor is asking, a human should review  |
  |       before the system acts.                  |
  |                                                |
  |  File: orchestration/nodes/confidence_check.py |
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
             |             | [PLACEHOLDER - Phase 5]    |
             |             +----------------------------+
             |
             v
  +-----------------------------------------------+
  |  STEP 9A: ROUTING (deterministic rules)        |
  |  "Which team should handle this?"              |
  |                                                |
  |  What it does:                                 |
  |    1. Map category -> team:                    |
  |       billing    -> finance-ops                |
  |       delivery   -> logistics                  |
  |       contract   -> legal-contracts            |
  |       technical  -> technical-support           |
  |       general    -> general-support            |
  |    2. Calculate SLA based on vendor tier:       |
  |       GOLD + CRITICAL   = 4 hours              |
  |       GOLD + HIGH       = 8 hours              |
  |       SILVER + MEDIUM   = 16 hours             |
  |       BRONZE + LOW      = 48 hours             |
  |    3. Check special rules:                     |
  |       - CRITICAL urgency -> always escalate    |
  |       - BLOCK_AUTOMATION flag -> human only    |
  |       - Existing open ticket -> link to it     |
  |                                                |
  |  Why: This is pure business logic, no AI.      |
  |       Rules are deterministic and auditable.   |
  |                                                |
  |  Output: RoutingDecision with team, SLA,       |
  |          priority, requires_human flag         |
  |  File: orchestration/nodes/routing.py          |
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
  |       numbers) using Titan Embed v2 or         |
  |       OpenAI embeddings                        |
  |    3. Search memory.embedding_index table      |
  |       using pgvector cosine similarity         |
  |    4. Filter by category (billing, delivery..) |
  |    5. Return top 5 matches with scores         |
  |                                                |
  |  Why: If the KB has an article that answers    |
  |       the question (score >= 0.80), the AI     |
  |       can draft a full response without        |
  |       human help.                              |
  |                                                |
  |  WHAT IS A VECTOR?                             |
  |    Text converted to a list of numbers.        |
  |    Similar questions produce similar numbers.  |
  |    "Where is my invoice?" and "Invoice status" |
  |    will have vectors close to each other.      |
  |    We compare using cosine similarity (0-1).   |
  |                                                |
  |  Output: KBSearchResult with articles + scores |
  |  File: orchestration/nodes/kb_search.py        |
  +--------------------+--------------------------+
                       |
                       v
  +-----------------------------------------------+
  |  DECISION POINT 2: PATH DECISION              |
  |  "Can the AI answer this, or does a human     |
  |   need to investigate?"                        |
  |                                                |
  |  Conditions for PATH A (AI resolves):          |
  |    - Best KB match score >= 0.80               |
  |    - KB article has specific facts              |
  |    - Analysis confidence >= 0.85               |
  |                                                |
  |  Otherwise -> PATH B (human investigates)      |
  |                                                |
  |  File: orchestration/nodes/path_decision.py    |
  +----------+------------------+-----------------+
             |                  |
          PATH A             PATH B
             |                  |
             v                  v
  +-----------------+  +--------------------+
  | RESOLUTION      |  | ACKNOWLEDGMENT     |
  | (LLM Call #2)   |  | (LLM Call #2)      |
  | Draft full      |  | Draft "we got      |
  | answer using    |  | your email, ticket |
  | KB articles     |  | is INC-XXXXX,      |
  |                 |  | team is reviewing" |
  | [PLACEHOLDER]   |  | [PLACEHOLDER]      |
  | Phase 4         |  | Phase 4            |
  +---------+-------+  +----------+---------+
            |                      |
            +----------+-----------+
                       |
                       v
  +-----------------------------------------------+
  |  STEP 11: QUALITY GATE               [Phase 4]|
  |  "Is this email safe to send?"                 |
  |                                                |
  |  7 checks:                                     |
  |    1. Ticket # format (INC-XXXXXXX)            |
  |    2. SLA wording matches vendor tier           |
  |    3. Required sections (greeting, body,       |
  |       next steps, closing)                     |
  |    4. Restricted terms scan (no internal       |
  |       jargon, no competitor names)             |
  |    5. Response length (50-500 words)           |
  |    6. Source citations (Path A only)           |
  |    7. PII scan (Amazon Comprehend)             |
  |                                                |
  |  [PLACEHOLDER - Phase 4]                       |
  +--------------------+--------------------------+
                       |
                       v
  +-----------------------------------------------+
  |  STEP 12: DELIVERY                    [Phase 4]|
  |  "Create ticket + send the email"              |
  |                                                |
  |  1. Create incident in ServiceNow              |
  |  2. Send email via Graph API /sendMail         |
  |  3. Update case status in PostgreSQL           |
  |  4. Publish completion event to EventBridge    |
  |                                                |
  |  [PLACEHOLDER - Phase 4]                       |
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
      draft_response:    { ... from Step 10 ... }      <-- [Phase 4]
      quality_gate_result: { ... }                     <-- [Phase 4]
      ticket_info:       { ... }                       <-- [Phase 4]
      status:            "ANALYZING"                   <-- updated by each node
  }


  NODE WIRING (src/orchestration/graph.py):

  START
    |
    v
  [context_loading] ----> [query_analysis] ----> [confidence_check]
                                                       |
                                          +------------+------------+
                                          |                         |
                                     path != "C"              path == "C"
                                          |                         |
                                     [routing]                 [triage] --> END
                                          |                     (paused)
                                     [kb_search]
                                          |
                                    [path_decision]
                                          |
                                 +--------+--------+
                                 |                  |
                            path == "A"        path == "B"
                                 |                  |
                           [resolution]      [acknowledgment]
                                 |                  |
                                 +--------+---------+
                                          |
                                   [quality_gate]
                                          |
                                     [delivery]
                                          |
                                         END
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
  | Resolution node (Path A draft)    | STUB     | Phase 4 (next)    |
  | Acknowledgment node (Path B)      | STUB     | Phase 4           |
  | Quality Gate (7 checks)           | STUB     | Phase 4           |
  | Delivery (ServiceNow + send)      | STUB     | Phase 4           |
  | ServiceNow connector              | STUB     | Phase 4           |
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

# 4. Test email ingestion (real services)
uv run python scripts/test_email_ingestion.py

# 5. Test full pipeline (email -> analysis)
uv run python scripts/run_email_to_analysis.py

# 6. Run unit tests
uv run pytest tests/ -q

# 7. Lint code
uv run ruff check .
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
      |--- HTTPS (pysnow) ---> ServiceNow [Phase 4] (tickets)
```

---

*This document was generated from the actual codebase at `vqm_ps/`.
Every file path, class name, and method name references real code.*
