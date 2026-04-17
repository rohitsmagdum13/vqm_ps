# VQMS Detailed Technical Guide

A deep-dive into every service, every function, every database table,
and every pipeline step — with code references and ASCII diagrams.

Each section has two parts:
- **Technical Details** — for developers (you)
- **How to Explain to Your Manager** — in 2-3 simple sentences

Last updated: 2026-04-16

---

## TABLE OF CONTENTS

1. Email Ingestion Service (10 steps, every function)
2. Portal Intake Service (6 steps)
3. Query Analysis Agent (8-layer defense, LLM call)
4. AI Pipeline — Full Step-by-Step (Steps 7–12, all 3 paths)
5. Database Schema — Every Table, Every Column, Why
6. Why SQS, EventBridge, and LangGraph (not Step Functions)
7. Code Trigger Map — Which File, Which Class, Which Function
8. Authentication System — End-to-End (Login, JWT, Middleware, Logout, Refresh)
9. API Documentation — Complete Endpoint Reference (14 endpoints)

---

## 1. EMAIL INGESTION SERVICE

```
  FILE:   src/services/email_intake/ (folder module)
  CLASS:  EmailIntakeService
  ENTRY:  process_email(message_id, correlation_id) -> ParsedEmailPayload
```

### How to Explain to Your Manager

> "When a vendor sends us an email, our system automatically picks
>  it up within 5 seconds, reads it, identifies who the vendor is,
>  saves everything to the database, and queues it for the AI to
>  analyze. The whole thing takes about 10-12 seconds and no human
>  touches it."

### What Happens — All 10 Steps

```
  Vendor sends email to vendorsupport@company.com
  |
  | Microsoft detects new email
  | (two ways: webhook push + polling every 5 min)
  |
  v
  EmailIntakeService.process_email(message_id, correlation_id)
  |
  |
  +=== STEP E2.1: IDEMPOTENCY CHECK ================================+
  |                                                                   |
  |  PURPOSE: Don't process the same email twice                      |
  |                                                                   |
  |  PROBLEM: Both the webhook AND the polling job can detect the     |
  |           same email. If we process it twice, the vendor gets     |
  |           two responses and we have duplicate tickets.            |
  |                                                                   |
  |  HOW IT WORKS:                                                    |
  |    1. Take the email's message_id (unique ID from Microsoft)      |
  |    2. Try to INSERT it into cache.idempotency_keys table          |
  |    3. The table has a UNIQUE constraint on the key column         |
  |    4. If INSERT succeeds -> this is a new email, continue         |
  |    5. If INSERT conflicts -> this is a duplicate, return None     |
  |                                                                   |
  |  SQL:                                                             |
  |    INSERT INTO cache.idempotency_keys (key, source, correlation_id)|
  |    VALUES ($1, 'email', $2)                                       |
  |    ON CONFLICT (key) DO NOTHING                                   |
  |                                                                   |
  |  WHY ON CONFLICT (not SELECT then INSERT):                        |
  |    Two workers could SELECT at the same time, both see "not       |
  |    found", both INSERT. ON CONFLICT is atomic — only one wins.    |
  |                                                                   |
  |  CODE:                                                            |
  |    db/connection/ -> PostgresConnector.check_idempotency()      |
  |    Returns: True (new) or False (duplicate)                       |
  |                                                                   |
  |  CLASSIFICATION: CRITICAL                                         |
  |  (if this fails, the whole process fails — SQS retries later)    |
  +===================================================================+
  |
  v
  +=== STEP E1: FETCH EMAIL FROM GRAPH API ==========================+
  |                                                                   |
  |  PURPOSE: Get the actual email content from Microsoft             |
  |                                                                   |
  |  HOW IT WORKS:                                                    |
  |    1. Authenticate with Microsoft using MSAL (OAuth2)             |
  |       - Tenant ID + Client ID + Client Secret -> Access Token     |
  |       - Token is cached and reused until it expires               |
  |    2. Call: GET /users/{mailbox}/messages/{message_id}            |
  |       - Includes: $expand=attachments to get file data            |
  |    3. Microsoft returns JSON with:                                |
  |       - sender (name + email)                                     |
  |       - subject line                                              |
  |       - body (HTML and/or plain text)                             |
  |       - receivedDateTime                                          |
  |       - conversationId (thread grouping)                          |
  |       - attachments[] (name, size, contentBytes as Base64)        |
  |       - internetMessageHeaders (In-Reply-To, References)          |
  |                                                                   |
  |  WHAT IS MSAL?                                                    |
  |    Microsoft Authentication Library. It handles the OAuth2        |
  |    "client credentials" flow — our app proves its identity to     |
  |    Microsoft and gets a token to read the mailbox. No human       |
  |    login needed.                                                  |
  |                                                                   |
  |  CODE:                                                            |
  |    adapters/graph_api/ -> GraphAPIConnector.fetch_email()       |
  |    adapters/graph_api/ -> GraphAPIConnector._acquire_token()    |
  |    adapters/graph_api/ -> GraphAPIConnector._request()          |
  |                                                                   |
  |  CLASSIFICATION: CRITICAL                                         |
  +===================================================================+
  |
  v
  +=== STEP E2.2: PARSE EMAIL FIELDS ================================+
  |                                                                   |
  |  PURPOSE: Extract useful data from the raw Graph API response     |
  |                                                                   |
  |  WHAT GETS EXTRACTED:                                             |
  |    sender_email:    "john@acme.com"                               |
  |    sender_name:     "John Smith"                                  |
  |    subject:         "Invoice INV-2024-0567 payment status"        |
  |    body_text:       (HTML stripped to plain text)                  |
  |    body_html:       (original HTML preserved for S3)              |
  |    received_at:     "2026-04-14T10:30:00"                         |
  |    conversation_id: "AAQkAGI2..." (Microsoft thread ID)           |
  |    in_reply_to:     "<prev-msg-id>" (email threading header)      |
  |                                                                   |
  |  HTML TO TEXT:                                                    |
  |    _html_to_text() strips all HTML tags using regex,              |
  |    decodes HTML entities, and collapses whitespace.               |
  |    We keep body_html too (stored in S3 for debugging).            |
  |                                                                   |
  |  CODE:                                                            |
  |    services/email_intake/ -> _parse_email_fields(raw_email)     |
  |    services/email_intake/ -> _html_to_text(html)               |
  |                                                                   |
  |  CLASSIFICATION: CRITICAL                                         |
  +===================================================================+
  |
  v
  +=== STEP E2.7: GENERATE IDs ======================================+
  |                                                                   |
  |  PURPOSE: Give this query unique tracking numbers                 |
  |                                                                   |
  |  THREE IDs ARE GENERATED:                                         |
  |                                                                   |
  |  query_id = "VQ-2026-0042"                                       |
  |    - Human-readable, sequential                                   |
  |    - Format: VQ-{year}-{4-digit-sequence}                        |
  |    - This is what the vendor sees in their response               |
  |    - Generated by: IdGenerator.generate_query_id()                |
  |                                                                   |
  |  correlation_id = "550e8400-e29b-41d4-a716-446655440000"          |
  |    - UUID v4 (random, globally unique)                            |
  |    - Travels through EVERY service call, database write,          |
  |      and API request for this query                               |
  |    - Used for: log tracing, debugging, audit trail                |
  |    - Generated by: IdGenerator.generate_correlation_id()          |
  |                                                                   |
  |  execution_id = "a3f5c8d2-1234-5678-9abc-def012345678"           |
  |    - UUID v4 for this specific pipeline run                       |
  |    - If the same query is retried, it gets a NEW execution_id     |
  |      but keeps the SAME correlation_id                            |
  |    - Generated by: IdGenerator.generate_execution_id()            |
  |                                                                   |
  |  WHY THREE IDs?                                                   |
  |    - query_id:       "Which vendor question is this?"             |
  |    - correlation_id: "Show me every log line for this question"   |
  |    - execution_id:   "Which attempt at processing is this?"       |
  |                                                                   |
  |  CODE:                                                            |
  |    utils/helpers.py -> IdGenerator class                          |
  |    utils/helpers.py -> TimeHelper.ist_now()                       |
  |                                                                   |
  |  CLASSIFICATION: CRITICAL                                         |
  +===================================================================+
  |
  v
  +=== STEP E2.3: STORE RAW EMAIL IN S3 ============================+
  |                                                                   |
  |  PURPOSE: Keep a copy of the original email for compliance        |
  |                                                                   |
  |  S3 KEY: inbound-emails/VQ-2026-0042/raw_email.json              |
  |                                                                   |
  |  HOW: Upload the full Graph API JSON response to S3              |
  |       using build_s3_key() from config/s3_paths.py               |
  |                                                                   |
  |  WHY: If something goes wrong later, we can re-read the          |
  |       original email. Also needed for audit compliance.           |
  |                                                                   |
  |  CODE:                                                            |
  |    services/email_intake/ -> _store_raw_email()                 |
  |    storage/s3_client.py -> S3Connector.upload_file()              |
  |    config/s3_paths.py -> build_s3_key()                           |
  |                                                                   |
  |  CLASSIFICATION: NON-CRITICAL                                     |
  |  (if S3 fails, log warning and continue — email is still         |
  |   in Outlook and DB has the parsed version)                       |
  +===================================================================+
  |
  v
  +=== STEP E2.4: PROCESS ATTACHMENTS ===============================+
  |                                                                   |
  |  PURPOSE: Extract text from PDFs, Excel, Word docs attached      |
  |           to the email so the AI can read them                    |
  |                                                                   |
  |  FOR EACH ATTACHMENT:                                             |
  |    1. VALIDATE:                                                   |
  |       - Not a blocked extension (.exe, .bat, .cmd, .ps1, .sh, .js)|
  |       - Under 10 MB per file                                      |
  |       - Total under 50 MB per email                               |
  |       - Max 10 attachments per email                              |
  |                                                                   |
  |    2. DECODE:                                                     |
  |       - Graph API sends attachments as Base64 string              |
  |       - We decode: base64.b64decode(contentBytes)                 |
  |                                                                   |
  |    3. STORE TO S3:                                                |
  |       Key: attachments/VQ-2026-0042/att001_invoice.pdf            |
  |                                                                   |
  |    4. EXTRACT TEXT (based on file type):                          |
  |       +----------+------------+--------------------------+        |
  |       | Type     | Library    | How It Works             |        |
  |       +----------+------------+--------------------------+        |
  |       | PDF      | pdfplumber | Opens PDF, reads each    |        |
  |       |          |            | page, extracts text      |        |
  |       | Excel    | openpyxl   | Opens .xlsx, reads each  |        |
  |       |          |            | sheet and row            |        |
  |       | Word     | python-docx| Opens .docx, reads each  |        |
  |       |          |            | paragraph                |        |
  |       | CSV/TXT  | built-in   | Decode bytes to string   |        |
  |       +----------+------------+--------------------------+        |
  |                                                                   |
  |    5. TRUNCATE: Max 5000 characters per attachment                |
  |       (to stay within LLM token limits)                           |
  |                                                                   |
  |    6. BUILD MANIFEST:                                             |
  |       _manifest.json stored at:                                   |
  |       attachments/VQ-2026-0042/_manifest.json                     |
  |       Lists all attachments with s3_keys and extraction status    |
  |                                                                   |
  |  CODE:                                                            |
  |    services/email_intake/ -> _process_attachments()             |
  |    services/email_intake/ -> _extract_text()                    |
  |    services/email_intake/ -> _extract_pdf_text()                |
  |    services/email_intake/ -> _extract_excel_text()              |
  |    services/email_intake/ -> _extract_docx_text()               |
  |    services/attachment_manifest.py -> AttachmentManifestBuilder    |
  |                                                                   |
  |  CLASSIFICATION: NON-CRITICAL                                     |
  |  (if attachment extraction fails for one file, the rest           |
  |   still process — partial results are fine)                       |
  +===================================================================+
  |
  v
  +=== STEP E2.5: IDENTIFY VENDOR (Salesforce) ======================+
  |                                                                   |
  |  PURPOSE: Figure out which vendor sent this email                 |
  |                                                                   |
  |  3-STEP FALLBACK CHAIN:                                           |
  |                                                                   |
  |    STEP 1: EXACT EMAIL MATCH                                      |
  |      Search Salesforce Contacts where Email = "john@acme.com"     |
  |      If found -> return vendor_id, match_method="email_match"     |
  |                                                                   |
  |          |                                                        |
  |    if not found                                                   |
  |          v                                                        |
  |                                                                   |
  |    STEP 2: BODY EXTRACTION                                        |
  |      Scan the email body text for company names                   |
  |      Search Salesforce Accounts where Name LIKE '%CompanyName%'   |
  |      If found -> return vendor_id, match_method="body_extraction" |
  |                                                                   |
  |          |                                                        |
  |    if not found                                                   |
  |          v                                                        |
  |                                                                   |
  |    STEP 3: FUZZY NAME MATCH                                       |
  |      Take the sender's display name "John Smith"                  |
  |      Search Salesforce Contacts with partial name match           |
  |      If found -> return vendor_id, match_method="fuzzy_match"     |
  |                                                                   |
  |          |                                                        |
  |    if not found                                                   |
  |          v                                                        |
  |                                                                   |
  |    UNRESOLVED: vendor_id=None, match_method="unresolved"          |
  |    (pipeline continues without vendor context — the AI will       |
  |     analyze the query anyway, just without vendor history)        |
  |                                                                   |
  |  CODE:                                                            |
  |    services/email_intake/ -> _identify_vendor()                  |
  |    adapters/salesforce/ -> SalesforceConnector.identify_vendor() |
  |    adapters/salesforce/ -> find_vendor_by_email()                |
  |    adapters/salesforce/ -> fuzzy_name_match()                    |
  |                                                                   |
  |  CLASSIFICATION: NON-CRITICAL                                     |
  +===================================================================+
  |
  v
  +=== STEP E2.6: THREAD CORRELATION ================================+
  |                                                                   |
  |  PURPOSE: Is this a new question or a reply to an old one?        |
  |                                                                   |
  |  HOW:                                                             |
  |    1. Get conversationId from the email (Microsoft thread ID)     |
  |    2. Search workflow.case_execution table for matching            |
  |       conversation_id                                             |
  |    3. Determine status:                                           |
  |                                                                   |
  |    +--------------------+-----------------------------------------+
  |    | Result             | Meaning                                 |
  |    +--------------------+-----------------------------------------+
  |    | NEW                | No prior conversation found             |
  |    | EXISTING_OPEN      | Reply to a case that is still open      |
  |    | REPLY_TO_CLOSED    | Reply to a case that was already closed |
  |    +--------------------+-----------------------------------------+
  |                                                                   |
  |  WHY: If the vendor is replying to an existing case, we should    |
  |       update that case — not create a brand new one.              |
  |                                                                   |
  |  CODE:                                                            |
  |    services/email_intake/ -> _determine_thread_status()          |
  |                                                                   |
  |  CLASSIFICATION: NON-CRITICAL (defaults to "NEW")                 |
  +===================================================================+
  |
  v
  +=== STEP E2.8: WRITE METADATA TO DATABASE ========================+
  |                                                                   |
  |  PURPOSE: Save the parsed email data permanently                  |
  |                                                                   |
  |  THREE INSERTS:                                                   |
  |                                                                   |
  |  1. intake.email_messages (one row per email)                     |
  |     query_id, message_id, sender_email, sender_name,             |
  |     subject, body_text, body_html, received_at, parsed_at,       |
  |     conversation_id, thread_status, vendor_id,                   |
  |     vendor_match_method, s3_raw_email_key                        |
  |                                                                   |
  |  2. intake.email_attachments (one row per attachment)             |
  |     query_id, attachment_id, filename, content_type,             |
  |     size_bytes, s3_key, extracted_text, extraction_status        |
  |                                                                   |
  |  3. workflow.case_execution (central tracking row)                |
  |     query_id, correlation_id, execution_id, source="email",      |
  |     status="RECEIVED", vendor_id                                 |
  |                                                                   |
  |  CODE:                                                            |
  |    services/email_intake/ -> _store_email_metadata()            |
  |    services/email_intake/ -> _store_attachment_metadata()       |
  |    services/email_intake/ -> _create_case_execution()           |
  |    db/connection/ -> PostgresConnector.execute()                |
  |                                                                   |
  |  CLASSIFICATION: CRITICAL                                         |
  +===================================================================+
  |
  v
  +=== STEP E2.9: PUBLISH EVENT + ENQUEUE ===========================+
  |                                                                   |
  |  TWO ACTIONS:                                                     |
  |                                                                   |
  |  a) EVENTBRIDGE: Publish "EmailParsed" event                     |
  |     Contains: query_id, vendor_id, subject, source               |
  |     Purpose: Other systems can listen (monitoring, dashboards)    |
  |     -> events/eventbridge.py -> publish_event("EmailParsed", ...)  |
  |     NON-CRITICAL                                                  |
  |                                                                   |
  |  b) SQS: Send UnifiedQueryPayload to queue                       |
  |     Contains: query_id, correlation_id, execution_id, source,    |
  |               subject, body, vendor_id, attachments text,        |
  |               thread_status                                       |
  |     -> queues/sqs.py -> SQSConnector.send_message()               |
  |     CRITICAL (this triggers the AI pipeline)                      |
  |                                                                   |
  |  CODE:                                                            |
  |    events/eventbridge.py -> EventBridgeConnector.publish_event()  |
  |    queues/sqs.py -> SQSConnector.send_message()                   |
  +===================================================================+
  |
  v
  Return ParsedEmailPayload
  (the intake is done, AI pipeline picks it up from SQS)
```

### For Your Manager

> "Think of it like a mailroom with 10 checkpoints. The email comes in,
>  we make sure it is not a duplicate, we read it, we figure out who sent
>  it by checking our CRM, we save everything to the database, and then
>  we put it in a queue for the AI brain to analyze. If any non-essential
>  step fails (like saving a backup copy), we skip it and keep going.
>  If an essential step fails (like reading the email), we retry later."

---

## 2. PORTAL INTAKE SERVICE

```
  FILE:   src/services/portal_submission.py
  CLASS:  PortalIntakeService
  ENTRY:  submit_query(submission, vendor_id, correlation_id) -> UnifiedQueryPayload
```

### How to Explain to Your Manager

> "A vendor logs into our web portal, fills out a form with their
>  question, and clicks Submit. Our backend validates the form,
>  creates a tracking number, saves it to the database, and queues
>  it for the AI — all in under 400 milliseconds. The vendor sees
>  their tracking number immediately."

### Portal vs Email — Key Differences

```
  +---------------------------+-------------------+--------------------+
  | Aspect                    | Email Path        | Portal Path        |
  +---------------------------+-------------------+--------------------+
  | Entry point               | vendorsupport@    | POST /queries      |
  | Vendor identification     | Salesforce lookup | JWT token (known)  |
  | Idempotency key           | message_id        | SHA-256 hash of    |
  |                           | (from Microsoft)  | vendor+subject+desc|
  | Attachments               | From email body   | File upload form   |
  | Thread correlation        | conversationId    | Not needed (new)   |
  | Raw storage               | S3 raw_email.json | Not needed         |
  | Response time             | ~12 seconds       | ~400 ms            |
  +---------------------------+-------------------+--------------------+

  BOTH PATHS PRODUCE THE SAME OUTPUT:
    UnifiedQueryPayload -> SQS Queue -> Same AI Pipeline
```

### What Happens — All Steps

```
  Vendor logs into portal (Cognito JWT auth)
  |
  v
  POST /queries with JSON body:
    { query_type, subject, description, priority, reference_number }
  |
  | FastAPI validates with Pydantic QuerySubmission model
  | vendor_id extracted from JWT token (NEVER from request body)
  |
  v
  PortalIntakeService.submit_query(submission, vendor_id, correlation_id)
  |
  +--- Step 1: Generate correlation_id (if not provided)
  |
  +--- Step 2: Compute idempotency key
  |      SHA-256( vendor_id + ":" + subject + ":" + description )
  |      Why SHA-256: creates a consistent, fixed-length key from
  |      variable-length input. Same vendor + same question = same hash.
  |
  +--- Step 3: Check idempotency (same as email path)
  |      INSERT INTO cache.idempotency_keys ON CONFLICT DO NOTHING
  |      If duplicate -> raise DuplicateQueryError (HTTP 409)
  |
  +--- Step 4: Generate query_id, execution_id, timestamp
  |      query_id = "VQ-2026-0043"
  |
  +--- Step 5: INSERT into workflow.case_execution
  |      status="RECEIVED", source="portal"
  |
  +--- Step 6a: EventBridge "QueryReceived" event (non-critical)
  |
  +--- Step 6b: SQS send UnifiedQueryPayload (critical)
  |      Same format as email path -> same AI pipeline
  |
  +--- Return UnifiedQueryPayload (with query_id)
       |
       v
  HTTP 201 { query_id: "VQ-2026-0043" }
  (vendor sees tracking number instantly)
```

### For Your Manager

> "Portal is simpler than email because the vendor is already logged in.
>  We know who they are (from their login token), we know what they are
>  asking (from the form), and we do not need to parse HTML or identify
>  the sender. It takes 400 milliseconds and the vendor gets a tracking
>  number right away."

---

## 3. QUERY ANALYSIS AGENT (LLM Call #1)

```
  FILE:   src/orchestration/nodes/query_analysis.py
  CLASS:  QueryAnalysisNode
  ENTRY:  execute(state: PipelineState) -> PipelineState update
```

### How to Explain to Your Manager

> "This is the AI brain. It reads the vendor's question, understands
>  what they are asking (invoice issue? delivery problem?), how urgent
>  it is, and how confident it is in its understanding. It is like
>  having an experienced support agent read every email and categorize
>  it — except it does it in 3 seconds and costs $0.01."

### The 8-Layer Defense Strategy

```
  WHY 8 LAYERS?

  The AI (Claude) is powerful but not perfect. It might:
  - Return invalid JSON
  - Hallucinate confidence scores
  - Fail to respond at all
  - Return unexpected field names

  Each layer catches a different type of failure.
  If ALL 8 layers fail, the query still does not crash —
  it routes to a human reviewer (Path C).

  +=================================================================+
  |                                                                 |
  |  LAYER 1: INPUT VALIDATION                                     |
  |  "Is the input even valid?"                                     |
  |                                                                 |
  |  Check: subject is not empty, body is not empty                 |
  |  If empty -> return safe fallback (confidence=0.3, Path C)      |
  |                                                                 |
  |  Truncate body to 10,000 chars (prevent token overflow)         |
  |  Truncate attachment text to 5,000 chars                        |
  |                                                                 |
  |  CODE: execute() lines checking unified_payload fields          |
  +=================================================================+
            |
            v
  +=================================================================+
  |                                                                 |
  |  LAYER 2: PROMPT ENGINEERING                                    |
  |  "Ask the AI in the right way"                                  |
  |                                                                 |
  |  Load Jinja2 template: query_analysis_v1.j2                     |
  |  Fill in variables:                                              |
  |    {{ vendor_name }}    = "Acme Corp"                            |
  |    {{ vendor_tier }}    = "GOLD"                                  |
  |    {{ query_source }}   = "email"                                |
  |    {{ query_subject }}  = "Invoice INV-2024-0567..."             |
  |    {{ query_body }}     = (full email body)                      |
  |    {{ attachment_text }}= (extracted text from PDFs etc)         |
  |    {{ recent_interactions }} = (last 5 vendor queries)           |
  |                                                                 |
  |  The prompt tells Claude:                                        |
  |    "Return ONLY a JSON object with these exact fields:           |
  |     intent_classification, extracted_entities, urgency_level,    |
  |     sentiment, confidence_score, multi_issue_detected,           |
  |     suggested_category"                                          |
  |                                                                 |
  |  WHY JINJA2: Templates are versioned files (v1, v2...).          |
  |  We can A/B test different prompt versions without changing code.|
  |                                                                 |
  |  CODE: prompts/query_analysis_v1.j2 (template)                  |
  |        orchestration/prompts/prompt_manager.py (loader)          |
  +=================================================================+
            |
            v
  +=================================================================+
  |                                                                 |
  |  LAYER 3: LLM CALL WITH RETRY                                  |
  |  "Send to Claude, retry if network fails"                       |
  |                                                                 |
  |  Call: gateway.llm_complete(                                     |
  |      prompt = rendered_template,                                 |
  |      temperature = 0.1,       (very low = consistent output)    |
  |      max_tokens = 4096,                                          |
  |      correlation_id = "..."                                      |
  |  )                                                               |
  |                                                                 |
  |  FALLBACK CHAIN:                                                 |
  |    1. Try Bedrock Claude Sonnet 3.5                              |
  |    2. If Bedrock fails -> Try OpenAI GPT-4o                      |
  |    3. If both fail -> Layer 7 safe fallback                      |
  |                                                                 |
  |  RETRY (inside Bedrock connector, via tenacity library):         |
  |    - 3 attempts                                                  |
  |    - Exponential backoff: 1s, 2s, 4s                             |
  |    - Only retries on: ThrottlingException,                       |
  |      ServiceUnavailableException, ModelTimeoutException          |
  |    - Does NOT retry on: AccessDenied, ValidationError            |
  |                                                                 |
  |  CODE:                                                            |
  |    adapters/llm_gateway.py -> LLMGateway.llm_complete()          |
  |    adapters/bedrock.py -> BedrockConnector.llm_complete()        |
  |    adapters/openai_llm.py -> OpenAIConnector.llm_complete()      |
  +=================================================================+
            |
            v
  +=================================================================+
  |                                                                 |
  |  LAYER 4: OUTPUT PARSING                                        |
  |  "Extract JSON from Claude's response"                          |
  |                                                                 |
  |  Claude might return:                                            |
  |    a) Clean JSON:  {"intent_classification": "..."}              |
  |    b) With fences: ```json\n{"intent...}\n```                    |
  |    c) With text:   "Here is the analysis:\n{...}"               |
  |                                                                 |
  |  THREE PARSING STRATEGIES (tried in order):                      |
  |    1. json.loads(response_text)      <- try raw parse first      |
  |    2. Strip ```json ... ``` fences   <- markdown format          |
  |    3. Regex extract first {...}      <- find JSON in text        |
  |                                                                 |
  |  If all 3 fail -> go to Layer 6 (self-correction)               |
  |                                                                 |
  |  CODE: _parse_json_from_response(response_text)                  |
  +=================================================================+
            |
            v
  +=================================================================+
  |                                                                 |
  |  LAYER 5: PYDANTIC VALIDATION                                  |
  |  "Does the JSON have the right fields and types?"               |
  |                                                                 |
  |  Validate parsed dict against AnalysisResult model:              |
  |    - intent_classification: must be a string                     |
  |    - urgency_level: must be LOW | MEDIUM | HIGH | CRITICAL       |
  |    - sentiment: must be POSITIVE | NEUTRAL | NEGATIVE | FRUSTR.  |
  |    - confidence_score: must be float between 0.0 and 1.0         |
  |    - multi_issue_detected: must be boolean                       |
  |    - suggested_category: must be a string                        |
  |                                                                 |
  |  If validation fails -> go to Layer 6 (self-correction)          |
  |                                                                 |
  |  CODE: AnalysisResult(**parsed_dict) in models/workflow.py        |
  +=================================================================+
            |
            v
  +=================================================================+
  |                                                                 |
  |  LAYER 6: SELF-CORRECTION (1 retry)                             |
  |  "Hey Claude, your output was wrong. Fix it."                    |
  |                                                                 |
  |  If Layer 4 or 5 failed, we send Claude a new prompt:            |
  |    "Your previous response could not be parsed.                  |
  |     Error: {error_message}                                       |
  |     Original response: {raw_response}                            |
  |     Please return ONLY valid JSON with the correct fields."      |
  |                                                                 |
  |  This works surprisingly well — Claude can usually fix its       |
  |  own mistakes when told what went wrong.                         |
  |                                                                 |
  |  Only 1 retry attempt. If self-correction also fails -> Layer 7  |
  |                                                                 |
  |  CODE: _self_correct(raw_response, error_message, corr_id)       |
  +=================================================================+
            |
            v
  +=================================================================+
  |                                                                 |
  |  LAYER 7: SAFE FALLBACK                                         |
  |  "If everything fails, send to a human"                         |
  |                                                                 |
  |  Returns a hardcoded AnalysisResult:                              |
  |    intent_classification = "UNKNOWN"                              |
  |    confidence_score = 0.3   (below 0.85 threshold)               |
  |    urgency_level = "MEDIUM"                                       |
  |    sentiment = "NEUTRAL"                                          |
  |    model_id = "fallback"                                          |
  |                                                                 |
  |  Because confidence=0.3 is below the 0.85 threshold,             |
  |  the Confidence Check node will automatically route this          |
  |  query to PATH C (human review).                                  |
  |                                                                 |
  |  THE SYSTEM NEVER CRASHES. It always produces a result.           |
  |                                                                 |
  |  CODE: _safe_fallback(start_time, reason)                         |
  +=================================================================+
            |
            v
  +=================================================================+
  |                                                                 |
  |  LAYER 8: AUDIT & MONITORING                                   |
  |  "Log everything for debugging and compliance"                   |
  |                                                                 |
  |  Logged via structlog with correlation_id:                        |
  |    - Input prompt (truncated)                                     |
  |    - Raw LLM response                                             |
  |    - Parsed JSON (or parse error)                                 |
  |    - Validation result (or validation error)                      |
  |    - Final AnalysisResult                                         |
  |    - Token counts (in/out), cost_usd, latency_ms                  |
  |    - Model used (bedrock or openai)                               |
  |                                                                 |
  |  CODE: @log_llm_call decorator on llm_complete()                  |
  |        structlog calls throughout query_analysis.py               |
  +=================================================================+
```

### Output Example (What the AI Returns)

```json
  {
    "intent_classification": "invoice_inquiry",
    "extracted_entities": {
      "invoice_numbers": ["INV-2024-0567"],
      "po_numbers": ["PO-8834"],
      "dates": ["March 5, 2024"],
      "amounts": ["$45,200"],
      "other": {}
    },
    "urgency_level": "HIGH",
    "sentiment": "FRUSTRATED",
    "confidence_score": 0.93,
    "multi_issue_detected": false,
    "suggested_category": "billing"
  }
```

### The 8 Intent Types

```
  Defined in: src/orchestration/prompts/query_analysis_v1.j2 (line 47)
  Stored in: AnalysisResult.intent_classification (str, not enum)

  +-----+---------------------+--------------------------------------+
  | #   | Intent              | When It Is Used                      |
  +-----+---------------------+--------------------------------------+
  | 1   | invoice_inquiry     | "Where is my invoice payment?"       |
  | 2   | delivery_status     | "When will my shipment arrive?"      |
  | 3   | payment_issue       | "Payment was rejected/delayed"       |
  | 4   | contract_question   | "What are the renewal terms?"        |
  | 5   | technical_support   | "API integration is failing"         |
  | 6   | onboarding          | "How do I register as a new vendor?" |
  | 7   | compliance          | "Need updated compliance cert"       |
  | 8   | general_inquiry     | Everything else                      |
  +-----+---------------------+--------------------------------------+

  NOTE: The field is a free-text string, not a strict enum.
  Claude may return other values. The system handles any string.
```

### For Your Manager

> "The AI reads the vendor's email and fills out a form: what are they
>  asking about, how urgent is it, are they frustrated, and how sure
>  is the AI about its answer. If the AI is less than 85% sure, it
>  sends the email to a human reviewer instead of guessing. We built
>  8 safety layers so the system never crashes — the worst case is
>  a human gets the email, which is what would happen anyway without AI."

---

## 4. DATABASE SCHEMA — EVERY TABLE, EVERY COLUMN, WHY

### How to Explain to Your Manager

> "We have one PostgreSQL database with 6 organized sections (schemas).
>  Think of it like a filing cabinet with 6 labeled drawers: one for
>  incoming emails, one for tracking case progress, one for remembering
>  vendor history, one for compliance records, one for performance
>  reports, and one for speed optimization."

### Schema Overview

```
  PostgreSQL Database: vqms
  Connection: Laptop --SSH Tunnel--> Bastion Host ---> RDS (private subnet)

  +=====================================================================+
  |                                                                     |
  |  SCHEMA: intake                                                     |
  |  PURPOSE: "What came in?" — raw email data                         |
  |  MANAGER SPEAK: "This is our inbox records"                        |
  |                                                                     |
  |  +--- intake.email_messages -----------------------------------+   |
  |  |                                                             |   |
  |  |  COLUMN              TYPE          WHY                      |   |
  |  |  ------              ----          ---                      |   |
  |  |  id                  SERIAL PK     Auto-increment row ID    |   |
  |  |  message_id          VARCHAR(512)  Microsoft's unique ID    |   |
  |  |                      UNIQUE        (prevents duplicate rows)|   |
  |  |  query_id            VARCHAR(20)   Our tracking number      |   |
  |  |                      UNIQUE        "VQ-2026-0042"           |   |
  |  |  correlation_id      VARCHAR(36)   UUID for log tracing     |   |
  |  |  sender_email        VARCHAR(320)  Who sent it              |   |
  |  |  sender_name         VARCHAR(256)  Display name             |   |
  |  |  subject             TEXT          Email subject line       |   |
  |  |  body_text           TEXT          Plain text version       |   |
  |  |  body_html           TEXT          Original HTML version    |   |
  |  |  received_at         TIMESTAMP     When email was received  |   |
  |  |  parsed_at           TIMESTAMP     When we processed it     |   |
  |  |  in_reply_to         VARCHAR(512)  Threading header         |   |
  |  |  conversation_id     VARCHAR(512)  Microsoft thread ID      |   |
  |  |  thread_status       VARCHAR(20)   NEW / EXISTING_OPEN /    |   |
  |  |                                    REPLY_TO_CLOSED          |   |
  |  |  vendor_id           VARCHAR(50)   Salesforce account ID    |   |
  |  |  vendor_match_method VARCHAR(20)   How we found the vendor  |   |
  |  |  s3_raw_email_key    VARCHAR(512)  S3 backup location       |   |
  |  |  source              VARCHAR(10)   "email" always           |   |
  |  |  created_at          TIMESTAMP     Row creation time        |   |
  |  +-------------------------------------------------------------+   |
  |                                                                     |
  |  +--- intake.email_attachments --------------------------------+   |
  |  |                                                             |   |
  |  |  COLUMN              TYPE          WHY                      |   |
  |  |  ------              ----          ---                      |   |
  |  |  id                  SERIAL PK     Auto-increment row ID    |   |
  |  |  message_id          VARCHAR(512)  FK -> email_messages     |   |
  |  |  query_id            VARCHAR(20)   Links to query           |   |
  |  |  attachment_id       VARCHAR(512)  Unique attachment ID     |   |
  |  |  filename            VARCHAR(512)  "invoice.pdf"            |   |
  |  |  content_type        VARCHAR(128)  "application/pdf"        |   |
  |  |  size_bytes          INTEGER       File size                |   |
  |  |  s3_key              VARCHAR(512)  Where in S3              |   |
  |  |  extracted_text      TEXT          Text pulled from file    |   |
  |  |  extraction_status   VARCHAR(20)   success / failed / skip  |   |
  |  |  created_at          TIMESTAMP     Row creation time        |   |
  |  +-------------------------------------------------------------+   |
  +=====================================================================+

  +=====================================================================+
  |                                                                     |
  |  SCHEMA: workflow                                                   |
  |  PURPOSE: "What is happening with each query?" — processing state  |
  |  MANAGER SPEAK: "This tracks every case from start to finish"      |
  |                                                                     |
  |  +--- workflow.case_execution (THE MOST IMPORTANT TABLE) ------+   |
  |  |                                                             |   |
  |  |  This is the CENTRAL STATE TABLE. Every query — whether     |   |
  |  |  from email or portal — has exactly ONE row here. This row  |   |
  |  |  tracks the query from RECEIVED all the way to RESOLVED.    |   |
  |  |                                                             |   |
  |  |  COLUMN              TYPE          WHY                      |   |
  |  |  ------              ----          ---                      |   |
  |  |  id                  SERIAL PK     Auto-increment row ID    |   |
  |  |  query_id            VARCHAR(20)   "VQ-2026-0042" (unique)  |   |
  |  |  correlation_id      VARCHAR(36)   UUID for tracing         |   |
  |  |  execution_id        VARCHAR(36)   This pipeline run's ID   |   |
  |  |  source              VARCHAR(10)   "email" or "portal"      |   |
  |  |  status              VARCHAR(20)   Current state:           |   |
  |  |                                    RECEIVED -> ANALYZING -> |   |
  |  |                                    ROUTING -> DRAFTING ->   |   |
  |  |                                    VALIDATING -> DELIVERING |   |
  |  |                                    -> RESOLVED | PAUSED |   |   |
  |  |                                    FAILED                   |   |
  |  |  processing_path     VARCHAR(1)    "A", "B", or "C"        |   |
  |  |  vendor_id           VARCHAR(50)   Salesforce ID            |   |
  |  |  analysis_result     JSONB         Full AI analysis output  |   |
  |  |  routing_decision    JSONB         Team, SLA, priority      |   |
  |  |  draft_response      JSONB         AI-drafted email         |   |
  |  |  quality_gate_result JSONB         7-check validation       |   |
  |  |  created_at          TIMESTAMP     When case was created    |   |
  |  |  updated_at          TIMESTAMP     Last status change       |   |
  |  +-------------------------------------------------------------+   |
  |                                                                     |
  |  +--- workflow.ticket_link ------------------------------------+   |
  |  |  Links our query_id to a ServiceNow ticket ID               |   |
  |  |  query_id, ticket_id ("INC-XXXXXXX"), servicenow_sys_id     |   |
  |  +-------------------------------------------------------------+   |
  |                                                                     |
  |  +--- workflow.routing_decision -------------------------------+   |
  |  |  Records the routing rules output                            |   |
  |  |  query_id, assigned_team, category, priority, sla_hours,     |   |
  |  |  routing_reason (human-readable audit string)                |   |
  |  +-------------------------------------------------------------+   |
  +=====================================================================+

  +=====================================================================+
  |                                                                     |
  |  SCHEMA: memory                                                     |
  |  PURPOSE: "What do we remember?" — vendor history + KB articles    |
  |  MANAGER SPEAK: "This is the AI's memory and knowledge base"       |
  |                                                                     |
  |  +--- memory.episodic_memory ----------------------------------+   |
  |  |  Stores the last N interactions with each vendor.            |   |
  |  |  When the AI analyzes a new query, it reads the last 5       |   |
  |  |  interactions to understand context.                          |   |
  |  |                                                             |   |
  |  |  vendor_id, query_id, intent, resolution_path (A/B/C),     |   |
  |  |  outcome (resolved/escalated), resolved_at, summary          |   |
  |  +-------------------------------------------------------------+   |
  |                                                                     |
  |  +--- memory.vendor_profile_cache -----------------------------+   |
  |  |  Cached vendor profiles from Salesforce (1-hour TTL).        |   |
  |  |  Reduces Salesforce API calls from ~100/hour to ~10/hour.    |   |
  |  |                                                             |   |
  |  |  vendor_id, profile_data (JSONB), expires_at                |   |
  |  +-------------------------------------------------------------+   |
  |                                                                     |
  |  +--- memory.embedding_index (pgvector) -----------------------+   |
  |  |  THIS IS THE KNOWLEDGE BASE.                                 |   |
  |  |                                                             |   |
  |  |  Each row is a KB article (or article chunk) with its       |   |
  |  |  text content AND a vector embedding (list of 1024 numbers). |   |
  |  |                                                             |   |
  |  |  article_id, title, content_text, category,                 |   |
  |  |  embedding vector(1024), metadata (JSONB)                   |   |
  |  |                                                             |   |
  |  |  HNSW index on embedding column for fast similarity search  |   |
  |  |  (m=16, ef_construction=64)                                  |   |
  |  |                                                             |   |
  |  |  HOW VECTOR SEARCH WORKS:                                    |   |
  |  |    "Where is my invoice?" -> [0.12, 0.84, 0.03, ...]        |   |
  |  |    Compare with every KB article's vector using cosine       |   |
  |  |    similarity. Score 0.95 = very similar. Score 0.3 = not.   |   |
  |  +-------------------------------------------------------------+   |
  +=====================================================================+

  +=====================================================================+
  |                                                                     |
  |  SCHEMA: cache                                                      |
  |  PURPOSE: "Speed things up" — prevent duplicate work               |
  |  MANAGER SPEAK: "This prevents us from doing the same work twice"  |
  |                                                                     |
  |  +--- cache.idempotency_keys ---------------------------------+    |
  |  |  Stores message_ids / query hashes for 7 days.              |    |
  |  |  UNIQUE constraint prevents duplicate processing.            |    |
  |  |  Background job cleans up keys older than 7 days.            |    |
  |  +-------------------------------------------------------------+    |
  |                                                                     |
  |  +--- cache.vendor_cache (1-hour TTL) -------------------------+   |
  |  |  Cached Salesforce vendor data.                              |   |
  |  +-------------------------------------------------------------+   |
  |                                                                     |
  |  +--- cache.workflow_state_cache (24-hour TTL) ----------------+   |
  |  |  Cached pipeline state for retry/resume.                     |   |
  |  +-------------------------------------------------------------+   |
  |                                                                     |
  |  +--- cache.kv_store -----------------------------------------+    |
  |  |  General purpose key-value cache.                            |    |
  |  |  Used for JWT token blacklist (logout).                      |    |
  |  +-------------------------------------------------------------+    |
  |                                                                     |
  |  WHY NOT REDIS?                                                     |
  |    PostgreSQL handles all caching needs. No need for a separate     |
  |    Redis server. Simpler infrastructure, fewer things to manage.    |
  +=====================================================================+

  +=====================================================================+
  |                                                                     |
  |  SCHEMA: audit                                                      |
  |  PURPOSE: "What happened and when?" — compliance trail             |
  |  MANAGER SPEAK: "This is our audit trail for compliance"           |
  |                                                                     |
  |  +--- audit.action_log ---------------------------------------+    |
  |  |  Every state transition is recorded here.                    |    |
  |  |  correlation_id, step_name, actor, action, status,           |    |
  |  |  details (JSONB), duration_ms                                |    |
  |  +-------------------------------------------------------------+    |
  |                                                                     |
  |  +--- audit.validation_results -------------------------------+    |
  |  |  Quality Gate check results.                                 |    |
  |  |  query_id, gate_name, passed, checks_run, checks_passed,    |    |
  |  |  failed_checks (JSONB)                                       |    |
  |  +-------------------------------------------------------------+    |
  +=====================================================================+

  +=====================================================================+
  |                                                                     |
  |  SCHEMA: reporting                                                  |
  |  PURPOSE: "How are we performing?" — SLA and metrics               |
  |  MANAGER SPEAK: "This powers the dashboard and SLA reports"        |
  |                                                                     |
  |  +--- reporting.sla_metrics -----------------------------------+   |
  |  |  Tracks SLA compliance per query.                            |   |
  |  |  query_id, sla_target_hours, sla_deadline,                  |   |
  |  |  warning_fired (70%), l1_escalation_fired (85%),            |   |
  |  |  l2_escalation_fired (95%), resolved_at, total_duration     |   |
  |  +-------------------------------------------------------------+   |
  +=====================================================================+
```

---

## 5. WHY SQS, EVENTBRIDGE, AND LANGGRAPH?

### How to Explain to Your Manager

> "Think of our system as a factory assembly line.
>  SQS is the conveyor belt between departments — it makes sure
>  nothing gets lost even if a machine breaks down.
>  EventBridge is the announcement speaker — it tells everyone
>  what just happened without interrupting the work.
>  LangGraph is the assembly line controller — it decides which
>  station to go to next based on the product being built."

### SQS (Simple Queue Service) — The Conveyor Belt

```
  WHAT IS IT?
    A message queue. You put a message in one end, a worker picks
    it up from the other end. If the worker crashes, the message
    goes back into the queue and another worker picks it up.

  WHY WE USE IT:
    Email intake and the AI pipeline run at different speeds.
    Intake might process 50 emails in 10 seconds.
    The AI pipeline takes 30 seconds per email.
    SQS holds the emails in line so nothing is lost.

  HOW IT WORKS:

    EMAIL INTAKE                    SQS QUEUE                   AI PIPELINE
    (fast, ~10s)                    (buffer)                    (slow, ~30s)
        |                               |                           |
        |  send_message()               |                           |
        |----> [ msg1 ] [ msg2 ] [ msg3 ]  <----receive_messages()  |
        |                               |                           |
        |                               |  After processing:        |
        |                               |  delete_message()         |
        |                               |  (removes from queue)     |


  WHAT HAPPENS IF THE AI PIPELINE CRASHES?

    1. Worker picks up message from SQS
    2. SQS makes message INVISIBLE (5 min timeout)
    3. Worker crashes during processing
    4. After 5 minutes, SQS makes message VISIBLE again
    5. Another worker picks it up and retries
    6. After 3 failed attempts -> message goes to DLQ
       (Dead Letter Queue — alerts the team)

  +----------------------------------------------------------------+
  |                                                                |
  |  Dead Letter Queue (DLQ)                                       |
  |                                                                |
  |  "A hospital for messages that keep failing"                   |
  |                                                                |
  |  If a message fails 3 times, it goes to vqms-dlq.             |
  |  A CloudWatch alarm fires when DLQ has messages.               |
  |  An engineer investigates why the message keeps failing.        |
  |                                                                |
  |  Without DLQ: failing messages would retry forever,            |
  |  blocking the queue and preventing new messages from           |
  |  being processed.                                              |
  +----------------------------------------------------------------+

  CODE:
    queues/sqs.py -> SQSConnector
    .send_message(queue_url, message_body, correlation_id)
    .receive_messages(queue_url, max_messages, wait_time)
    .delete_message(queue_url, receipt_handle)

  QUEUES WE USE:
    vqms-email-intake-queue    (email -> AI pipeline)
    vqms-query-intake-queue    (portal -> AI pipeline)
    vqms-dlq                   (failed messages land here)
```

### EventBridge — The Announcement Speaker

```
  WHAT IS IT?
    An event bus. When something happens in our system, we publish
    an event. Other systems can listen and react — without our code
    knowing or caring who is listening.

  WHY WE USE IT:
    1. AUDIT TRAIL: Every event is recorded (who, what, when)
    2. DECOUPLING: The email service does not need to know about
       the dashboard. It just says "EmailParsed" and the dashboard
       picks it up.
    3. MONITORING: CloudWatch can watch for specific events
       (like SLAEscalation) and send alerts.

  ANALOGY:
    Imagine a factory PA system:
    "Attention: Order #42 has been packed and is ready for shipping."
    The shipping dept hears it and acts. Accounting hears it and
    updates the books. Quality control hears it and logs it.
    The packing dept does not need to call each of them individually.

  20 EVENT TYPES WE PUBLISH:

    +---------------------------+----------------------------------+
    | Event                     | When It Fires                    |
    +---------------------------+----------------------------------+
    | EmailReceived             | New email detected               |
    | EmailParsed               | Email intake complete            |
    | QueryReceived             | Portal submission complete        |
    | AnalysisCompleted         | AI analysis done                 |
    | VendorResolved            | Vendor identified in Salesforce  |
    | TicketCreated             | ServiceNow ticket created        |
    | TicketUpdated             | Ticket status changed            |
    | DraftPrepared             | AI email draft ready             |
    | ValidationPassed          | Quality gate passed              |
    | ValidationFailed          | Quality gate failed              |
    | EmailSent                 | Reply sent to vendor             |
    | SLAWarning70              | 70% of SLA time used             |
    | SLAEscalation85           | 85% of SLA time used             |
    | SLAEscalation95           | 95% of SLA time used (critical)  |
    | VendorReplyReceived       | Vendor replied to our email      |
    | ResolutionPrepared        | Human team provided answer       |
    | TicketClosed              | Case resolved and closed         |
    | TicketReopened            | Closed case reopened             |
    | HumanReviewRequired       | Path C triggered                 |
    | HumanReviewCompleted      | Reviewer submitted corrections   |
    +---------------------------+----------------------------------+

  CODE:
    events/eventbridge.py -> EventBridgeConnector.publish_event()
    Validates event_type against VALID_EVENT_TYPES whitelist
    Adds correlation_id and IST timestamp to every event
```

### LangGraph (Not Step Functions) — The Assembly Line Controller

```
  WHAT IS IT?
    A Python library for building AI pipelines as a state machine.
    You define "nodes" (steps) and "edges" (connections), and
    LangGraph runs them in order with conditional branching.

  WHY LANGGRAPH INSTEAD OF AWS STEP FUNCTIONS?

    +--------------------+------------------+---------------------+
    | Feature            | LangGraph        | Step Functions      |
    +--------------------+------------------+---------------------+
    | Runs where?        | Inside our Python| AWS cloud service   |
    |                    | app (local or EC2)| (separate infra)   |
    | State management   | Python dict in   | JSON in AWS         |
    |                    | memory           |                     |
    | LLM integration    | Native (built    | Requires Lambda     |
    |                    | for AI agents)   | wrapper functions   |
    | Cost               | Free (library)   | Pay per transition  |
    | Debugging          | Python debugger   | CloudWatch logs     |
    |                    | (step through)   | (harder to debug)   |
    | Deployment         | Part of our app   | Separate AWS service|
    | IAM permissions    | None needed       | Step Functions IAM  |
    |                    |                   | (we may not have)  |
    +--------------------+------------------+---------------------+

    MAIN REASON: We are building an AI pipeline with multiple LLM
    calls, conditional branching, and shared state. LangGraph was
    specifically designed for this. Step Functions was designed for
    general workflow orchestration (not AI-specific).

    ALSO: We have limited AWS IAM permissions. LangGraph runs inside
    our Python process — no extra AWS permissions needed.

  HOW IT WORKS:

    1. Define nodes (Python functions)
    2. Define edges (connections between nodes)
    3. Define conditional edges (if/else branching)
    4. Compile into an executable graph
    5. Run: pass initial state -> get final state

    graph = StateGraph(PipelineState)
    graph.add_node("context_loading", context_node.execute)
    graph.add_node("query_analysis", analysis_node.execute)
    graph.add_edge("context_loading", "query_analysis")
    graph.add_conditional_edges("confidence_check", route_fn, {...})
    compiled = graph.compile()
    result = compiled.invoke(initial_state)

  CODE:
    orchestration/graph.py -> build_pipeline_graph()
    Returns compiled StateGraph ready for invocation
```

### For Your Manager (All Three Together)

> "SQS is like a to-do list between our email reader and our AI brain.
>  Even if the AI brain is busy, emails pile up safely and get processed
>  in order. EventBridge is like an office announcement system — every
>  time something happens, it broadcasts it so monitoring, dashboards,
>  and alerts can all react without being directly connected. LangGraph
>  is the AI brain's decision-making engine — it decides whether the AI
>  can answer the question directly or if a human needs to step in."

---

## 6. FULL AI PIPELINE — STEP BY STEP

```
  FILE: src/orchestration/graph.py -> build_pipeline_graph()

  Each node is a Python class with an execute(state) method.
  The state is a shared dictionary (PipelineState) that every
  node reads from and writes to.


  SQS Message arrives
  (UnifiedQueryPayload from email or portal intake)
       |
       v
  +====================================================================+
  | STEP 7: CONTEXT LOADING                                            |
  |                                                                    |
  | FILE:  orchestration/nodes/context_loading.py                      |
  | CLASS: ContextLoadingNode                                          |
  | METHOD: execute(state) -> state update                             |
  |                                                                    |
  | WHAT IT DOES:                                                      |
  |   1. Read vendor_id from state                                     |
  |   2. Check cache.vendor_cache (PostgreSQL) for vendor profile      |
  |      - Cache hit AND not expired? -> use cached data               |
  |      - Cache miss? -> call Salesforce API                          |
  |      - Salesforce down? -> use default BRONZE profile              |
  |   3. Load last 5 rows from memory.episodic_memory                  |
  |      (past interactions with this vendor)                          |
  |   4. Build VendorContext: { profile, recent_interactions }         |
  |   5. Set status = "ANALYZING"                                      |
  |                                                                    |
  | WRITES TO STATE: vendor_context, status                            |
  |                                                                    |
  | CALLS:                                                             |
  |   db/connection/  -> cache_read("cache.vendor_cache", ...)         |
  |   adapters/salesforce/ -> find_vendor_by_id(vendor_id)           |
  |   db/connection/  -> fetch("SELECT FROM memory.episodic_memory")   |
  +====================================================================+
       |
       v
  +====================================================================+
  | STEP 8: QUERY ANALYSIS (LLM CALL #1)                              |
  |                                                                    |
  | FILE:  orchestration/nodes/query_analysis.py                       |
  | CLASS: QueryAnalysisNode                                           |
  | METHOD: execute(state) -> state update                             |
  |                                                                    |
  | (See Section 3 above for the full 8-layer breakdown)               |
  |                                                                    |
  | WRITES TO STATE: analysis_result (AnalysisResult as dict)          |
  |                                                                    |
  | CALLS:                                                             |
  |   orchestration/prompts/prompt_manager.py -> render("query_an..")  |
  |   adapters/llm_gateway.py -> llm_complete(prompt, temp=0.1)       |
  +====================================================================+
       |
       v
  +====================================================================+
  | DECISION POINT 1: CONFIDENCE CHECK                                |
  |                                                                    |
  | FILE:  orchestration/nodes/confidence_check.py                     |
  | CLASS: ConfidenceCheckNode                                         |
  | METHOD: execute(state) -> state update                             |
  |                                                                    |
  | LOGIC (4 lines of real code):                                      |
  |   confidence = state["analysis_result"]["confidence_score"]        |
  |   if confidence >= 0.85:                                           |
  |       return {}  # continue to routing                             |
  |   else:                                                            |
  |       return {"processing_path": "C", "status": "PAUSED"}         |
  |                                                                    |
  | CONDITIONAL EDGE (in graph.py):                                    |
  |   route_after_confidence_check(state):                             |
  |     if state["processing_path"] == "C" -> go to "triage"          |
  |     else -> go to "routing"                                        |
  +====================================================================+
       |                              |
    >= 0.85                        < 0.85
       |                              |
       v                              v
  CONTINUE                     TRIAGE [Phase 5 stub]
       |                       (workflow PAUSES)
       |                       (human reviews)
       v
  +====================================================================+
  | STEP 9A: ROUTING (pure business logic, no AI)                     |
  |                                                                    |
  | FILE:  orchestration/nodes/routing.py                              |
  | CLASS: RoutingNode                                                 |
  | METHOD: execute(state) -> state update                             |
  |                                                                    |
  | TEAM ASSIGNMENT — TWO-LEVEL LOOKUP:                                |
  |                                                                    |
  |   LEVEL 1: Exact match on official query type (12 types)           |
  |   Defined in: models/query.py -> QUERY_TYPE_TEAM_MAP               |
  |                                                                    |
  |     RETURN_REFUND       -> "finance-ops"                           |
  |     GENERAL_INQUIRY     -> "general-support"                       |
  |     CATALOG_PRICING     -> "procurement"                           |
  |     CONTRACT_QUERY      -> "legal-compliance"                      |
  |     PURCHASE_ORDER      -> "procurement"                           |
  |     SLA_BREACH_REPORT   -> "sla-compliance"                        |
  |     DELIVERY_SHIPMENT   -> "supply-chain"                          |
  |     INVOICE_PAYMENT     -> "finance-ops"                           |
  |     COMPLIANCE_AUDIT    -> "legal-compliance"                      |
  |     TECHNICAL_SUPPORT   -> "tech-support"                          |
  |     ONBOARDING          -> "vendor-management"                     |
  |     QUALITY_ISSUE       -> "quality-assurance"                     |
  |                                                                    |
  |   LEVEL 2: Keyword fallback (if Level 1 misses)                    |
  |   Defined in: orchestration/nodes/routing.py -> CATEGORY_TEAM_MAP  |
  |                                                                    |
  |     billing/invoice/payment/return/refund -> "finance-ops"         |
  |     delivery/shipping/logistics/shipment  -> "supply-chain"        |
  |     contract/agreement/terms/legal/       -> "legal-compliance"    |
  |       compliance/audit                                             |
  |     technical/integration/api/product     -> "tech-support"        |
  |     catalog/pricing/purchase              -> "procurement"         |
  |     onboarding                            -> "vendor-management"   |
  |     quality/defect                        -> "quality-assurance"   |
  |     sla                                   -> "sla-compliance"      |
  |     (no match)                            -> "general-support"     |
  |                                                                    |
  |   CODE (routing.py line 119-122):                                  |
  |     assigned_team = QUERY_TYPE_TEAM_MAP.get(                       |
  |         suggested_category.upper(),           # try Level 1        |
  |         CATEGORY_TEAM_MAP.get(                                     |
  |             suggested_category.lower(),        # try Level 2       |
  |             DEFAULT_TEAM))                     # fallback           |
  |                                                                    |
  | SLA CALCULATION:                                                   |
  |   Formula: SLA Hours = max(1, floor(Base × Multiplier))            |
  |                                                                    |
  |   Base hours by vendor tier (TIER_SLA_HOURS):                      |
  |     PLATINUM=4h, GOLD=8h, SILVER=16h, BRONZE=24h                  |
  |                                                                    |
  |   Multiplied by urgency (URGENCY_MULTIPLIER):                      |
  |     CRITICAL=0.25x, HIGH=0.5x, MEDIUM=1.0x, LOW=1.5x             |
  |                                                                    |
  |   FULL SLA MATRIX (hours):                                         |
  |   +----------+----------+------+--------+------+                   |
  |   | Tier     | CRITICAL | HIGH | MEDIUM | LOW  |                   |
  |   +----------+----------+------+--------+------+                   |
  |   | PLATINUM |    1     |  2   |   4    |  6   |                   |
  |   | GOLD     |    2     |  4   |   8    | 12   |                   |
  |   | SILVER   |    4     |  8   |  16    | 24   |                   |
  |   | BRONZE   |    6     | 12   |  24    | 36   |                   |
  |   +----------+----------+------+--------+------+                   |
  |                                                                    |
  |   Example: SILVER + HIGH = 16 × 0.5 = 8 hours                     |
  |   Example: GOLD + CRITICAL = 8 × 0.25 = 2 hours                   |
  |   Example: PLATINUM + CRITICAL = 4 × 0.25 = 1 hour (min=1)        |
  |                                                                    |
  | SLA ESCALATION THRESHOLDS:                                         |
  |   Warning     at 70% of SLA hours  (env: SLA_WARNING_THRESHOLD_PERCENT)     |
  |   L1 Escalate at 85% of SLA hours  (env: SLA_L1_ESCALATION_THRESHOLD_PERCENT)|
  |   L2 Escalate at 95% of SLA hours  (env: SLA_L2_ESCALATION_THRESHOLD_PERCENT)|
  |                                                                    |
  |   Worked example (GOLD + HIGH = 4 hours):                          |
  |     Warning:  4 × 0.70 = 2.8 hours -> after 2h 48m                |
  |     L1:       4 × 0.85 = 3.4 hours -> after 3h 24m                |
  |     L2:       4 × 0.95 = 3.8 hours -> after 3h 48m                |
  |                                                                    |
  | WRITES TO STATE: routing_decision (RoutingDecision as dict)        |
  |   { assigned_team, sla_target: {total_hours,                       |
  |     warning_at_percent, l1_escalation_at_percent,                  |
  |     l2_escalation_at_percent},                                     |
  |     category, priority, routing_reason }                           |
  +====================================================================+
       |
       v
  +====================================================================+
  | STEP 9B: KB SEARCH (vector similarity — no AI reasoning)          |
  |                                                                    |
  | FILE:  orchestration/nodes/kb_search.py                            |
  | CLASS: KBSearchNode                                                |
  | METHOD: execute(state) -> state update                             |
  |                                                                    |
  | HOW VECTOR SEARCH WORKS (step by step):                            |
  |                                                                    |
  |   1. Take the vendor's question:                                   |
  |      "Where is my invoice INV-2024-0567 payment?"                  |
  |                                                                    |
  |   2. Convert to a vector (list of 1024 numbers):                   |
  |      [0.12, 0.84, 0.03, -0.45, 0.67, ...]                         |
  |      Using: Titan Embed v2 or OpenAI text-embedding-3-small       |
  |                                                                    |
  |   3. Run SQL query against memory.embedding_index:                 |
  |      SELECT article_id, title, content_text,                       |
  |             1 - (embedding <=> $1::vector) AS similarity           |
  |      FROM memory.embedding_index                                   |
  |      ORDER BY embedding <=> $1::vector                             |
  |      LIMIT 5                                                       |
  |                                                                    |
  |      <=> is pgvector's cosine distance operator                    |
  |      1 - distance = similarity (0.0 to 1.0)                       |
  |                                                                    |
  |   4. Filter: only keep matches above 0.80 threshold               |
  |                                                                    |
  |   5. Return KBSearchResult:                                        |
  |      { matches: [{title, content_snippet, score}],                 |
  |        best_score: 0.92,                                           |
  |        has_sufficient_match: true }                                 |
  |                                                                    |
  | WRITES TO STATE: kb_search_result                                  |
  |                                                                    |
  | CALLS:                                                             |
  |   adapters/llm_gateway.py -> llm_embed(search_text)               |
  |   db/connection/ -> fetch(pgvector_similarity_query)             |
  +====================================================================+
       |
       v
  +====================================================================+
  | DECISION POINT 2: PATH DECISION                                   |
  |                                                                    |
  | FILE:  orchestration/nodes/path_decision.py                        |
  | CLASS: PathDecisionNode                                            |
  | METHOD: execute(state) -> state update                             |
  |                                                                    |
  | LOGIC:                                                             |
  |   has_match = kb_search_result["has_sufficient_match"]             |
  |   has_facts = len(top_match["content_snippet"]) >= 100             |
  |                                                                    |
  |   if has_match AND has_facts:                                      |
  |       return {"processing_path": "A", "status": "DRAFTING"}       |
  |       # AI can draft a full answer                                 |
  |                                                                    |
  |   else:                                                            |
  |       return {"processing_path": "B", "status": "DRAFTING",       |
  |               routing_decision.requires_human_investigation: True} |
  |       # Human team must investigate                                |
  |                                                                    |
  | CONDITIONAL EDGE (in graph.py):                                    |
  |   route_after_path_decision(state):                                |
  |     if state["processing_path"] == "A" -> go to "resolution"      |
  |     else -> go to "acknowledgment"                                 |
  +====================================================================+
       |                              |
    PATH A                         PATH B
       |                              |
       v                              v
  +====================================================================+
  | STEP 10A: RESOLUTION (Path A only — AI drafts full answer)        |
  |                                                                    |
  | FILE:  orchestration/nodes/resolution.py                           |
  | CLASS: ResolutionNode                                              |
  | METHOD: execute(state) -> state update                             |
  |                                                                    |
  | WHAT IT DOES:                                                      |
  |   LLM Call #2 — generates a FULL RESOLUTION email using KB         |
  |   articles as the source of facts. This is the "happy path"        |
  |   where the AI found a good answer in the knowledge base.          |
  |                                                                    |
  | HOW IT WORKS:                                                      |
  |   1. Gather from state:                                            |
  |      - subject, body (the vendor's question)                       |
  |      - analysis_result (from Step 8)                               |
  |      - kb_search_result (from Step 9B — the KB articles)           |
  |      - routing_decision (from Step 9A — team, SLA)                 |
  |      - vendor_context (tier, history)                              |
  |                                                                    |
  |   2. Format KB articles into a readable block:                     |
  |      _format_kb_articles(matches) -> string                        |
  |      "Article 1: <title> (score: 0.92)\n<content>\n..."           |
  |                                                                    |
  |   3. Look up SLA statement by vendor tier:                         |
  |      SLA_STATEMENTS = {                                            |
  |        "PLATINUM": "4 hours",                                      |
  |        "GOLD": "8 hours",                                          |
  |        "SILVER": "16 hours",                                       |
  |        "BRONZE": "24 hours",                                       |
  |      }                                                             |
  |                                                                    |
  |   4. Render prompt template:                                       |
  |      orchestration/prompts/resolution_v1.j2                        |
  |      (includes: query, KB articles, vendor context, SLA)           |
  |                                                                    |
  |   5. Call LLM via adapters/llm_gateway.py -> llm_complete()        |
  |      temperature=0.3 (slightly creative for natural language)      |
  |      max_tokens=4096                                               |
  |                                                                    |
  |   6. Parse JSON from LLM response:                                 |
  |      _parse_json_from_response(raw_text) -> dict                   |
  |      Handles markdown fences, preamble text, etc.                  |
  |                                                                    |
  |   7. Build draft_response dict:                                    |
  |      {                                                             |
  |        "draft_type": "RESOLUTION",                                 |
  |        "subject": "Re: <original subject>",                        |
  |        "body": "<full answer with facts from KB>",                 |
  |        "confidence": 0.92,                                         |
  |        "sources": ["KB Article Title 1", "KB Article Title 2"],    |
  |        "ticket_number": "PENDING"  (replaced by Delivery node)     |
  |      }                                                             |
  |                                                                    |
  | IF LLM CALL FAILS:                                                 |
  |   Returns a safe fallback draft with low confidence                |
  |   that will route to human review via Quality Gate                 |
  |                                                                    |
  | WRITES TO STATE: draft_response, status="QUALITY_CHECK"            |
  |                                                                    |
  | CALLS:                                                             |
  |   orchestration/prompts/prompt_manager.py -> render()              |
  |   adapters/llm_gateway.py -> llm_complete()                        |
  |     -> adapters/bedrock.py -> llm_complete()                       |
  +====================================================================+
           |
           |                              |
           |     +====================================================================+
           |     | STEP 10B: ACKNOWLEDGMENT (Path B only — confirms receipt)          |
           |     |                                                                    |
           |     | FILE:  orchestration/nodes/acknowledgment.py                       |
           |     | CLASS: AcknowledgmentNode                                          |
           |     | METHOD: execute(state) -> state update                             |
           |     |                                                                    |
           |     | WHAT IT DOES:                                                      |
           |     |   LLM Call #2 — generates an ACKNOWLEDGMENT-ONLY email.            |
           |     |   This NEVER answers the vendor's question.                        |
           |     |   It just says: "We got your email, ticket is INC-XXXXXXX,         |
           |     |   our team is reviewing, SLA is X hours."                          |
           |     |                                                                    |
           |     | CRITICAL DIFFERENCE FROM RESOLUTION:                               |
           |     |   Resolution = "Here is the answer to your question"               |
           |     |   Acknowledgment = "We received your question, team is on it"      |
           |     |                                                                    |
           |     | HOW IT WORKS:                                                      |
           |     |   Same 7-step pattern as ResolutionNode but:                       |
           |     |   - Uses acknowledgment_v1.j2 prompt template                     |
           |     |   - Prompt explicitly says "DO NOT answer the question"            |
           |     |   - draft_type = "ACKNOWLEDGMENT"                                  |
           |     |   - sources = [] (always empty — no KB articles used)              |
           |     |                                                                    |
           |     | OUTPUT:                                                            |
           |     |   {                                                                |
           |     |     "draft_type": "ACKNOWLEDGMENT",                                |
           |     |     "subject": "Re: <original subject>",                           |
           |     |     "body": "Dear <vendor>, we received your query...",             |
           |     |     "confidence": 0.88,                                            |
           |     |     "sources": [],                                                 |
           |     |     "ticket_number": "PENDING"                                     |
           |     |   }                                                                |
           |     |                                                                    |
           |     | WRITES TO STATE: draft_response, status="QUALITY_CHECK"            |
           |     |                                                                    |
           |     | CALLS:                                                             |
           |     |   orchestration/prompts/prompt_manager.py -> render()              |
           |     |   adapters/llm_gateway.py -> llm_complete()                        |
           |     |     -> adapters/bedrock.py -> llm_complete()                       |
           |     +====================================================================+
           |                           |
           +-------------+------------+
                         |
                         v
  +====================================================================+
  | STEP 11: QUALITY GATE (7 deterministic checks on every draft)     |
  |                                                                    |
  | FILE:  orchestration/nodes/quality_gate.py                         |
  | CLASS: QualityGateNode                                             |
  | METHOD: execute(state) -> state update                             |
  |                                                                    |
  | WHAT IT DOES:                                                      |
  |   Runs 7 validation checks on EVERY outbound email draft           |
  |   before it can be sent to the vendor. Both Path A and Path B      |
  |   drafts must pass all 7 checks.                                   |
  |                                                                    |
  | THE 7 CHECKS:                                                      |
  |                                                                    |
  |   CHECK 1: TICKET NUMBER FORMAT                                    |
  |   _check_ticket_number(body)                                       |
  |   Regex: r"INC-\d{7}" or "PENDING"                                |
  |   Must contain a valid ticket reference in the draft body          |
  |                                                                    |
  |   CHECK 2: SLA WORDING                                             |
  |   _check_sla_wording(body, vendor_tier)                            |
  |   Draft must mention the correct SLA timeframe matching            |
  |   the vendor's tier (e.g., PLATINUM vendor = "4 hours")            |
  |   Uses SLA_STATEMENTS dict (same as Resolution/Ack nodes)          |
  |                                                                    |
  |   CHECK 3: REQUIRED SECTIONS                                       |
  |   _check_required_sections(body)                                   |
  |   Every email must have these 4 sections:                          |
  |     - Greeting (Dear/Hello/Hi)                                     |
  |     - Body (actual content)                                        |
  |     - Next steps section                                           |
  |     - Closing (Regards/Best/Thank)                                 |
  |                                                                    |
  |   CHECK 4: RESTRICTED TERMS                                        |
  |   _check_restricted_terms(body)                                    |
  |   Scans for 13 banned terms that should never appear:              |
  |   "internal only", "confidential", "do not share",                |
  |   "todo", "fixme", "hack", "workaround", "placeholder",          |
  |   "test data", "dummy", "fake", "mock", "debug"                   |
  |                                                                    |
  |   CHECK 5: WORD COUNT                                              |
  |   MIN_WORD_COUNT = 50, MAX_WORD_COUNT = 500                        |
  |   Too short = not enough information                               |
  |   Too long = vendor won't read it                                  |
  |                                                                    |
  |   CHECK 6: SOURCE CITATIONS (Path A only)                          |
  |   If draft_type == "RESOLUTION":                                   |
  |     sources list must not be empty                                 |
  |     (Path A claims to answer the question — must cite KB sources)  |
  |   If draft_type == "ACKNOWLEDGMENT":                               |
  |     This check is SKIPPED (Path B has no sources)                  |
  |                                                                    |
  |   CHECK 7: PII SCAN (stub — Phase 4)                               |
  |   _check_pii_stub(body) -> always passes for now                   |
  |   Will use Amazon Comprehend in production                         |
  |                                                                    |
  | SCORING:                                                           |
  |   TOTAL_CHECKS = 7                                                 |
  |   Result: { passed: true/false, checks_run: 7,                     |
  |             checks_passed: N, failed_checks: [...],                |
  |             redraft_count: 0, max_redrafts: 2 }                    |
  |                                                                    |
  | IF CHECKS FAIL:                                                    |
  |   Up to 2 re-drafts allowed (redraft_count tracks attempts)        |
  |   After 2 failures -> routes to human review                       |
  |                                                                    |
  | WRITES TO STATE: quality_gate_result, status="VALIDATED"           |
  +====================================================================+
                         |
                         v
  +====================================================================+
  | STEP 12: DELIVERY (ServiceNow ticket + email send)                |
  |                                                                    |
  | FILE:  orchestration/nodes/delivery.py                             |
  | CLASS: DeliveryNode                                                |
  | METHOD: execute(state) -> state update                             |
  |                                                                    |
  | WHAT IT DOES:                                                      |
  |   Four-phase execution that creates a real ticket and sends        |
  |   the validated email to the vendor.                               |
  |                                                                    |
  | PHASE 1: CREATE SERVICENOW TICKET                                  |
  |   _create_ticket(state) -> ticket_number (INC-XXXXXXX)            |
  |   Calls: adapters/servicenow/ -> ServiceNowAdapter.create_ticket()|
  |   POST /api/now/table/incident with:                               |
  |     short_description, description, urgency, impact,               |
  |     assignment_group (from routing_decision.assigned_team),         |
  |     caller_id, correlation_id                                      |
  |   Returns: INC-XXXXXXX number                                      |
  |                                                                    |
  | PHASE 2: REPLACE "PENDING" WITH REAL TICKET NUMBER                 |
  |   In draft_response.body:                                          |
  |     "PENDING" -> "INC-0012345"                                     |
  |   (Resolution and Acknowledgment nodes write "PENDING"             |
  |    as a placeholder — Delivery replaces it with the real number)   |
  |                                                                    |
  | PHASE 3: SEND EMAIL VIA GRAPH API                                  |
  |   _send_email(state, ticket_number) -> bool                        |
  |   Calls: adapters/graph_api/ -> GraphAPIConnector.send_email()   |
  |   POST /users/{mailbox}/sendMail with:                             |
  |     toRecipients, subject, body (HTML), importance                 |
  |                                                                    |
  | PHASE 4: SET FINAL STATUS                                          |
  |   Path A (RESOLUTION):                                             |
  |     status = "RESOLVED"                                            |
  |     (ticket created for monitoring, answer already sent)           |
  |   Path B (ACKNOWLEDGMENT):                                         |
  |     status = "AWAITING_RESOLUTION"                                 |
  |     (ticket created for INVESTIGATION, team must solve it)         |
  |                                                                    |
  | WRITES TO STATE: ticket_info, delivery_status, status,             |
  |                  updated_at                                        |
  |                                                                    |
  | CALLS:                                                             |
  |   adapters/servicenow/ -> ServiceNowAdapter.create_ticket()      |
  |   adapters/graph_api/ -> GraphAPIConnector.send_email()          |
  +====================================================================+
                         |
                         v
                       DONE
  
  PATH A end state: RESOLVED       (vendor has answer, team monitors)
  PATH B end state: AWAITING_RESOLUTION (vendor has ack, team investigates)
```

---

## 7. CODE TRIGGER MAP — WHICH FILE, WHICH CLASS, WHICH FUNCTION

### Complete Call Chain: Email Arrives -> AI Decides Path

```
  TRIGGER: New email arrives at vendorsupport@company.com

  1. WEBHOOK (real-time)
     Microsoft sends HTTP POST to our webhook endpoint
     -> api/routes/webhooks.py -> handle_graph_notification()
        -> services/email_intake/ -> EmailIntakeService.process_email()

  2. POLLING (every 5 minutes, catches missed webhooks)
     -> services/polling.py -> poll_unread_emails()
        -> adapters/graph_api/ -> list_unread_messages()
        -> services/email_intake/ -> EmailIntakeService.process_email()

  3. EMAIL INTAKE (10 steps inside process_email)
     -> db/connection/ -> check_idempotency()           [Step E2.1]
     -> adapters/graph_api/ -> fetch_email()             [Step E1]
     -> _parse_email_fields()                              [Step E2.2]
     -> utils/helpers.py -> IdGenerator.generate_query_id()[Step E2.7]
     -> storage/s3_client.py -> upload_file()              [Step E2.3]
     -> _process_attachments() -> _extract_text()          [Step E2.4]
     -> adapters/salesforce/ -> identify_vendor()        [Step E2.5]
     -> _determine_thread_status()                         [Step E2.6]
     -> db/connection/ -> execute(INSERT email_messages)  [Step E2.8]
     -> db/connection/ -> execute(INSERT case_execution)  [Step E2.8]
     -> events/eventbridge.py -> publish_event("EmailParsed") [Step E2.9]
     -> queues/sqs.py -> send_message(queue, payload)      [Step E2.9]

  4. SQS CONSUMER (picks up message from queue)
     -> orchestration/sqs_consumer.py -> consume()
        -> orchestration/graph.py -> compiled_graph.invoke(state)

  5. AI PIPELINE NODES (executed by LangGraph in order)
     -> orchestration/nodes/context_loading.py
            ContextLoadingNode.execute(state)
              -> db/connection/ -> cache_read()
              -> adapters/salesforce/ -> find_vendor_by_id()
              -> db/connection/ -> fetch(episodic_memory)

     -> orchestration/nodes/query_analysis.py
            QueryAnalysisNode.execute(state)
              -> orchestration/prompts/prompt_manager.py -> render()
              -> adapters/llm_gateway.py -> llm_complete()
                  -> adapters/bedrock.py -> llm_complete()
                  -> [on fail] adapters/openai_llm.py -> llm_complete()
              -> _parse_json_from_response()
              -> models/workflow.py -> AnalysisResult(**parsed)

     -> orchestration/nodes/confidence_check.py
            ConfidenceCheckNode.execute(state)
              -> [if < 0.85] return path="C"

     -> orchestration/nodes/routing.py
            RoutingNode.execute(state)
              -> CATEGORY_TEAM_MAP lookup
              -> TIER_SLA_HOURS * URGENCY_MULTIPLIER calculation

     -> orchestration/nodes/kb_search.py
            KBSearchNode.execute(state)
              -> adapters/llm_gateway.py -> llm_embed()
                  -> adapters/bedrock.py -> llm_embed()
                  -> [on fail] adapters/openai_llm.py -> llm_embed()
              -> db/connection/ -> fetch(pgvector cosine similarity)

     -> orchestration/nodes/path_decision.py
            PathDecisionNode.execute(state)
              -> [if match >= 0.80 AND content >= 100 chars] path="A"
              -> [else] path="B"

     -> orchestration/nodes/path_decision.py  (conditional edge)
            route_after_path_decision(state):
              -> [if path == "A"] go to "resolution"
              -> [if path == "B"] go to "acknowledgment"

     -> orchestration/nodes/resolution.py  (PATH A ONLY)
            ResolutionNode.execute(state)
              -> orchestration/prompts/prompt_manager.py -> render("resolution_v1.j2")
              -> adapters/llm_gateway.py -> llm_complete(temperature=0.3)
                  -> adapters/bedrock.py -> llm_complete()
              -> _parse_json_from_response()
              -> _format_kb_articles()
              -> Returns draft_response with draft_type="RESOLUTION"

     -> orchestration/nodes/acknowledgment.py  (PATH B ONLY)
            AcknowledgmentNode.execute(state)
              -> orchestration/prompts/prompt_manager.py -> render("acknowledgment_v1.j2")
              -> adapters/llm_gateway.py -> llm_complete(temperature=0.3)
                  -> adapters/bedrock.py -> llm_complete()
              -> _parse_json_from_response()
              -> Returns draft_response with draft_type="ACKNOWLEDGMENT", sources=[]

     -> orchestration/nodes/quality_gate.py  (BOTH PATHS)
            QualityGateNode.execute(state)
              -> _check_ticket_number(body)       [Check 1: INC-XXXXXXX or PENDING]
              -> _check_sla_wording(body, tier)    [Check 2: correct SLA timeframe]
              -> _check_required_sections(body)    [Check 3: greeting/body/next/close]
              -> _check_restricted_terms(body)     [Check 4: 13 banned terms]
              -> word count check                  [Check 5: 50-500 words]
              -> source citations check            [Check 6: Path A only]
              -> _check_pii_stub(body)             [Check 7: PII scan placeholder]

     -> orchestration/nodes/delivery.py  (BOTH PATHS)
            DeliveryNode.execute(state)
              -> _create_ticket(state)
                  -> adapters/servicenow/ -> ServiceNowAdapter.create_ticket()
              -> replace "PENDING" with "INC-XXXXXXX" in draft body
              -> _send_email(state, ticket_number)
                  -> adapters/graph_api/ -> GraphAPIConnector.send_email()
              -> set final status:
                  Path A -> "RESOLVED"
                  Path B -> "AWAITING_RESOLUTION"
```

### Complete Call Chain: Portal Submission

```
  TRIGGER: Vendor clicks "Submit" on the portal

  1. HTTP REQUEST
     POST /queries with JWT Bearer token
     -> api/routes/queries.py -> submit_query_endpoint()
        -> api/middleware/auth_middleware.py validates JWT
        -> extract vendor_id from JWT claims

  2. PORTAL INTAKE
     -> services/portal_submission.py
            PortalIntakeService.submit_query(submission, vendor_id)
              -> SHA-256 idempotency hash
              -> db/connection/ -> check_idempotency()
              -> utils/helpers.py -> IdGenerator.generate_query_id()
              -> db/connection/ -> execute(INSERT case_execution)
              -> events/eventbridge.py -> publish_event("QueryReceived")
              -> queues/sqs.py -> send_message(queue, payload)
              -> return UnifiedQueryPayload

  3. SAME AI PIPELINE AS EMAIL PATH (Steps 7-12)
     (SQS consumer picks up the message and runs the graph)
```

### File-to-Phase Mapping

```
  +--------------------------------------------------+-------+---------+
  | FILE                                             | PHASE | STATUS  |
  +--------------------------------------------------+-------+---------+
  | config/settings.py                               |   1   | DONE    |
  | config/s3_paths.py                               |   1   | DONE    |
  | src/models/*.py (all 10 model files)             |   1   | DONE    |
  | src/db/connection/ (folder module)                |   1   | DONE    |
  | src/db/migrations/*.sql (10 files)               |   1   | DONE    |
  | src/utils/helpers.py                             |   1   | DONE    |
  | src/utils/exceptions.py                          |   1   | DONE    |
  | src/utils/decorators/ (folder module)             |   1   | DONE    |
  | src/utils/logger.py                              |   1   | DONE    |
  | src/cache/cache_client.py                        |   1   | DONE    |
  +--------------------------------------------------+-------+---------+
  | src/services/email_intake/ (folder module)        |   2   | DONE    |
  | src/services/portal_submission.py                |   2   | DONE    |
  | src/services/auth.py                             |   2   | DONE    |
  | src/services/polling.py                          |   2   | DONE    |
  | src/services/attachment_manifest.py              |   2   | DONE    |
  | src/adapters/graph_api/ (folder module)           |   2   | DONE    |
  | src/adapters/salesforce/ (folder module)          |   2   | DONE    |
  | src/storage/s3_client.py                         |   2   | DONE    |
  | src/queues/sqs.py                                |   2   | DONE    |
  | src/events/eventbridge.py                        |   2   | DONE    |
  | src/api/routes/*.py                              |   2   | DONE    |
  | src/api/middleware/auth_middleware.py             |   2   | DONE    |
  +--------------------------------------------------+-------+---------+
  | src/adapters/bedrock.py                          |   3   | DONE    |
  | src/adapters/openai_llm.py                       |   3   | DONE    |
  | src/adapters/llm_gateway.py                      |   3   | DONE    |
  | src/orchestration/nodes/context_loading.py       |   3   | DONE    |
  | src/orchestration/nodes/query_analysis.py        |   3   | DONE    |
  | src/orchestration/nodes/confidence_check.py      |   3   | DONE    |
  | src/orchestration/nodes/routing.py               |   3   | DONE    |
  | src/orchestration/nodes/kb_search.py             |   3   | DONE    |
  | src/orchestration/nodes/path_decision.py         |   3   | DONE    |
  | src/orchestration/graph.py                       |   3   | DONE    |
  | src/orchestration/prompts/query_analysis_v1.j2   |   3   | DONE    |
  | src/orchestration/prompts/prompt_manager.py      |   3   | DONE    |
  +--------------------------------------------------+-------+---------+
  | orchestration/nodes/resolution.py                |   4   | DONE    |
  | orchestration/nodes/acknowledgment.py            |   4   | DONE    |
  | orchestration/nodes/quality_gate.py              |   4   | DONE    |
  | orchestration/nodes/delivery.py                  |   4   | DONE    |
  | adapters/servicenow/ (folder module)              |   4   | DONE    |
  | orchestration/prompts/resolution_v1.j2           |   4   | DONE    |
  | orchestration/prompts/acknowledgment_v1.j2       |   4   | DONE    |
  +--------------------------------------------------+-------+---------+
  | orchestration/nodes/triage.py                    |   5   | PLANNED |
  | SLA monitoring module                            |   6   | PLANNED |
  +--------------------------------------------------+-------+---------+
  | frontend/src/app/ (Angular 17+ standalone)       |   7   | DONE    |
  | frontend/src/app/pages/portal/                   |   7   | DONE    |
  | frontend/src/app/pages/new-query-type/           |   7   | DONE    |
  | frontend/src/app/pages/new-query-review/         |   7   | DONE    |
  | frontend/src/app/pages/query-status/             |   7   | DONE    |
  | frontend/src/app/services/query.service.ts       |   7   | DONE    |
  +--------------------------------------------------+-------+---------+
```

---

*This document references real code at `vqm_ps/src/`.
Every class name, method name, file path, and SQL query is from the actual codebase.*

---

## 8. AUTHENTICATION SYSTEM — END-TO-END

```
  FILES:
    models/auth.py                    — Pydantic models (LoginRequest, LoginResponse, TokenPayload)
    services/auth.py                  — Business logic (login, JWT create/validate, blacklist, refresh)
    api/routes/auth.py                — API endpoints (POST /auth/login, POST /auth/logout)
    api/middleware/auth_middleware.py  — Middleware (intercepts every request, validates JWT)
    cache/cache_client.py             — PostgreSQL-backed cache (token blacklist storage)
    config/settings.py                — JWT settings (secret key, algorithm, timeouts)
    main.py                           — Startup wiring (init_auth_service, middleware registration)
```

### How to Explain to Your Manager

> "We built a complete login system. When a user logs in, they get
>  a digital pass (JWT token) that expires in 30 minutes. Every time
>  they make a request, our system checks that pass automatically.
>  If they log out, the pass is immediately invalidated. If their
>  pass is about to expire while they're still working, we silently
>  give them a new one so they're never kicked out mid-task."


### THE BIG PICTURE — How Auth Flows Through the System

```
  +------------------+
  |   User / Client  |        (Angular frontend, Swagger UI, Postman, etc.)
  |                  |
  |  Knows: username |
  |  Knows: password |
  +--------+---------+
           |
           |  POST /auth/login
           |  Body: {"username_or_email": "admin_user", "password": "admin123"}
           |
           v
  +--------+------------------------------------------+
  |                                                    |
  |              FASTAPI APPLICATION                   |
  |                                                    |
  |  +----------------------------------------------+  |
  |  |         AuthMiddleware (SKIPS /auth/login)    |  |
  |  |                                               |  |
  |  |  Checks path against SKIP_PATHS:              |  |
  |  |    /health, /auth/login, /docs, /openapi.json |  |
  |  |    /redoc, /webhooks/                          |  |
  |  |                                               |  |
  |  |  /auth/login is in skip list -> PASS THROUGH  |  |
  |  +----------------------------------------------+  |
  |                    |                                |
  |                    v                                |
  |  +----------------------------------------------+  |
  |  |       api/routes/auth.py -> login()           |  |
  |  |                                               |  |
  |  |  1. Generate correlation_id for tracing       |  |
  |  |  2. Call authenticate_user(username, password) |  |
  |  |  3. If AuthenticationError -> return 401      |  |
  |  |  4. If success -> return LoginResponse (JWT)  |  |
  |  +----------------------------------------------+  |
  |                    |                                |
  |                    v                                |
  |  +----------------------------------------------+  |
  |  |  services/auth.py -> authenticate_user()      |  |
  |  |                                               |  |
  |  |  Step 1: Query PostgreSQL for user            |  |
  |  |    SELECT ... FROM tbl_users                  |  |
  |  |    WHERE user_name = $1 OR email_id = $1      |  |
  |  |                                               |  |
  |  |  Step 2: Check account status                 |  |
  |  |    status must be "ACTIVE"                    |  |
  |  |                                               |  |
  |  |  Step 3: Verify password                      |  |
  |  |    werkzeug.check_password_hash()             |  |
  |  |    (runs in thread — CPU-bound, don't block)  |  |
  |  |                                               |  |
  |  |  Step 4: Look up user role                    |  |
  |  |    SELECT ... FROM tbl_user_roles             |  |
  |  |    WHERE user_name = $1                       |  |
  |  |                                               |  |
  |  |  Step 5: Create JWT token                     |  |
  |  |    create_access_token(user, role, tenant)     |  |
  |  |                                               |  |
  |  |  Step 6: Return LoginResponse                 |  |
  |  +----------------------------------------------+  |
  |                    |                                |
  |                    v                                |
  |              RESPONSE: 200 OK                      |
  |              {                                     |
  |                "token": "eyJhbG...",                |
  |                "user_name": "admin_user",           |
  |                "email": "admin@vqms.local",         |
  |                "role": "ADMIN",                     |
  |                "tenant": "hexaware",                |
  |                "vendor_id": null                    |
  |              }                                     |
  +----------------------------------------------------+
           |
           |  User saves the token
           |
           v
  +------------------+
  |   User / Client  |
  |                  |
  |  Now has: token  |
  +------------------+
```


### STEP-BY-STEP: LOGIN FLOW

```
  +=== STEP 1: USER SENDS CREDENTIALS ===============================+
  |                                                                   |
  |  ENDPOINT: POST /auth/login                                       |
  |  FILE:     api/routes/auth.py -> login()                          |
  |  MODEL:    models/auth.py -> LoginRequest                         |
  |                                                                   |
  |  REQUEST BODY (Pydantic-validated):                               |
  |    {                                                              |
  |      "username_or_email": "admin_user",                           |
  |      "password": "admin123"                                       |
  |    }                                                              |
  |                                                                   |
  |  WHAT HAPPENS:                                                    |
  |    1. FastAPI deserializes JSON into LoginRequest model            |
  |    2. Pydantic validates both fields are present and non-empty     |
  |    3. Route handler generates a correlation_id (UUID v4)           |
  |    4. Calls services/auth.py -> authenticate_user()               |
  |                                                                   |
  |  NOTE: /auth/login is in SKIP_PATHS so the AuthMiddleware         |
  |        does NOT check for a Bearer token on this endpoint.        |
  |        (You can't require auth to log in — that's circular.)     |
  +===================================================================+
  |
  v
  +=== STEP 2: FIND USER IN DATABASE ================================+
  |                                                                   |
  |  FILE:  services/auth.py -> authenticate_user()                   |
  |  DB:    public.tbl_users                                          |
  |                                                                   |
  |  SQL:                                                             |
  |    SELECT id, user_name, email_id, tenant, password, status,      |
  |           security_q1, security_a1, security_q2, security_a2,     |
  |           security_q3, security_a3                                |
  |    FROM public.tbl_users                                          |
  |    WHERE user_name = $1 OR email_id = $1                          |
  |    LIMIT 1                                                        |
  |                                                                   |
  |  WHY "OR email_id":                                               |
  |    Users can log in with either their username OR their email.     |
  |    Both are UNIQUE columns in tbl_users, so this is safe.         |
  |                                                                   |
  |  IF NOT FOUND:                                                    |
  |    -> Log warning: "Login failed — user not found"                |
  |    -> Raise AuthenticationError("Invalid credentials")            |
  |    -> Route returns 401                                           |
  |                                                                   |
  |  SECURITY NOTE:                                                   |
  |    The error says "Invalid credentials" — NOT "User not found".   |
  |    This prevents attackers from learning which usernames exist.    |
  +===================================================================+
  |
  v
  +=== STEP 3: CHECK ACCOUNT STATUS =================================+
  |                                                                   |
  |  FILE:  services/auth.py -> authenticate_user()                   |
  |                                                                   |
  |  CHECK: user_row["status"] must be "ACTIVE"                       |
  |                                                                   |
  |  IF INACTIVE:                                                     |
  |    -> Log warning: "Login failed — account inactive"              |
  |    -> Raise AuthenticationError("Account is inactive")            |
  |    -> Route returns 401                                           |
  |                                                                   |
  |  WHY THIS EXISTS:                                                 |
  |    Admins can deactivate accounts without deleting them.           |
  |    The user row still exists (for audit history), but they         |
  |    can no longer log in.                                           |
  +===================================================================+
  |
  v
  +=== STEP 4: VERIFY PASSWORD ======================================+
  |                                                                   |
  |  FILE:  services/auth.py -> authenticate_user()                   |
  |  LIB:   werkzeug.security.check_password_hash()                   |
  |                                                                   |
  |  HOW PASSWORD HASHING WORKS:                                      |
  |                                                                   |
  |    When user was created (by admin or seed script):                |
  |      password "admin123"                                          |
  |        -> werkzeug.generate_password_hash("admin123")             |
  |        -> "scrypt:32768:8:1$salt$longhashstring..."               |
  |        -> stored in tbl_users.password column                     |
  |                                                                   |
  |    When user logs in NOW:                                         |
  |      check_password_hash(stored_hash, "admin123")                 |
  |        -> rehashes "admin123" with same salt                      |
  |        -> compares: do they match?                                |
  |        -> returns True or False                                   |
  |                                                                   |
  |  WHY asyncio.to_thread():                                         |
  |    password_valid = await asyncio.to_thread(                      |
  |        check_password_hash, user_row["password"], password        |
  |    )                                                              |
  |                                                                   |
  |    Password hashing is CPU-intensive (intentionally slow to        |
  |    prevent brute force). If we ran it directly, it would block     |
  |    the async event loop and freeze ALL other requests. Running     |
  |    it in a thread lets other requests continue while the hash     |
  |    is being computed.                                              |
  |                                                                   |
  |  IF PASSWORD WRONG:                                               |
  |    -> Log warning: "Login failed — invalid password"              |
  |    -> Raise AuthenticationError("Invalid credentials")            |
  |    -> Same generic message as "user not found" (security)         |
  +===================================================================+
  |
  v
  +=== STEP 5: LOOK UP USER ROLE ====================================+
  |                                                                   |
  |  FILE:  services/auth.py -> authenticate_user()                   |
  |  DB:    public.tbl_user_roles                                     |
  |                                                                   |
  |  SQL:                                                             |
  |    SELECT slno, first_name, last_name, email_id,                  |
  |           user_name, tenant, role                                 |
  |    FROM public.tbl_user_roles                                     |
  |    WHERE user_name = $1                                           |
  |    LIMIT 1                                                        |
  |                                                                   |
  |  WHY A SEPARATE TABLE:                                            |
  |    tbl_users stores identity (who you are).                       |
  |    tbl_user_roles stores authorization (what you can do).          |
  |    Separating them means:                                         |
  |      - One user can have their role changed without touching       |
  |        their password or profile                                  |
  |      - Audit trail: tbl_user_roles has created_by, modified_by,   |
  |        deleted_by columns to track who changed permissions        |
  |      - Future: one user could have multiple roles                 |
  |                                                                   |
  |  POSSIBLE ROLES:                                                  |
  |    ADMIN    — Full system access, metrics, user management        |
  |    VENDOR   — Portal access, own queries only                     |
  |    REVIEWER — Triage queue, Path C human review                   |
  |                                                                   |
  |  IF NO ROLE FOUND:                                                |
  |    -> Log warning: "Login failed — no role assigned"              |
  |    -> Raise AuthenticationError("No role assigned to this user")  |
  |    -> This means someone created a user in tbl_users but          |
  |       forgot to add their role in tbl_user_roles                  |
  +===================================================================+
  |
  v
  +=== STEP 6: CREATE JWT TOKEN ======================================+
  |                                                                   |
  |  FILE:  services/auth.py -> create_access_token()                 |
  |  LIB:   python-jose (jwt.encode)                                  |
  |  ALGO:  HMAC-SHA256 (HS256)                                       |
  |                                                                   |
  |  WHAT IS A JWT (JSON Web Token)?                                  |
  |                                                                   |
  |    A JWT is a signed string with 3 parts separated by dots:       |
  |                                                                   |
  |    eyJhbGci...  .  eyJzdWIi...  .  EEsJma5d...                    |
  |    [HEADER]        [PAYLOAD]       [SIGNATURE]                    |
  |                                                                   |
  |    HEADER:  {"alg": "HS256", "typ": "JWT"}                        |
  |    PAYLOAD: (the claims — see below)                              |
  |    SIGNATURE: HMAC-SHA256(header + payload, SECRET_KEY)            |
  |                                                                   |
  |  CLAIMS WE PUT IN THE PAYLOAD:                                    |
  |    {                                                              |
  |      "sub": "admin_user",        <- who this token is for         |
  |      "role": "ADMIN",            <- what they can do              |
  |      "tenant": "hexaware",       <- which organization            |
  |      "exp": 1776143124.24,       <- when it expires (Unix time)   |
  |      "iat": 1776141324.24,       <- when it was issued            |
  |      "jti": "e11e49d2-c111..."   <- unique token ID (for logout)  |
  |    }                                                              |
  |                                                                   |
  |  WHY EACH CLAIM EXISTS:                                           |
  |    sub  — Identifies the user. Middleware reads this to set        |
  |           request.state.username for route handlers.               |
  |    role — Authorization. Routes can check "is this user an        |
  |           ADMIN?" without hitting the database.                   |
  |    tenant — Multi-tenancy. Isolates data between organizations.   |
  |    exp  — Auto-expiry. After 30 minutes, the token is invalid.    |
  |           No one needs to manually revoke it.                     |
  |    iat  — Audit trail. Know exactly when the session started.     |
  |    jti  — JWT ID (UUID). Unique identifier so we can blacklist    |
  |           ONE specific token without affecting all tokens for     |
  |           that user.                                              |
  |                                                                   |
  |  CONFIG (from config/settings.py):                                |
  |    jwt_secret_key:                env var JWT_SECRET_KEY           |
  |    jwt_algorithm:                 "HS256"                         |
  |    session_timeout_seconds:       1800 (30 minutes)               |
  |    token_refresh_threshold_seconds: 300 (5 minutes)               |
  |                                                                   |
  |  SECURITY:                                                        |
  |    The SECRET_KEY never leaves the server. Without it, nobody     |
  |    can forge a valid token. If the key leaks, ALL tokens are      |
  |    compromised — rotate immediately.                              |
  +===================================================================+
  |
  v
  +=== STEP 7: RETURN RESPONSE ======================================+
  |                                                                   |
  |  FILE:  services/auth.py -> authenticate_user()                   |
  |  MODEL: models/auth.py -> LoginResponse                          |
  |                                                                   |
  |  RESPONSE (200 OK):                                               |
  |    {                                                              |
  |      "token": "eyJhbGciOiJIUzI1NiIs...",                          |
  |      "user_name": "admin_user",                                   |
  |      "email": "admin@vqms.local",                                 |
  |      "role": "ADMIN",                                             |
  |      "tenant": "hexaware",                                        |
  |      "vendor_id": null                                            |
  |    }                                                              |
  |                                                                   |
  |  The client (Angular frontend, Swagger UI, etc.) saves the        |
  |  token and sends it with every subsequent request as:             |
  |    Authorization: Bearer eyJhbGciOiJIUzI1NiIs...                  |
  +===================================================================+
```


### WHAT HAPPENS ON EVERY SUBSEQUENT REQUEST (Middleware)

```
  User makes ANY request (e.g., GET /vendors)
  |
  |  Headers include: Authorization: Bearer eyJhbG...
  |
  v
  +================================================================+
  |                                                                 |
  |  api/middleware/auth_middleware.py -> AuthMiddleware.dispatch()  |
  |                                                                 |
  |  This middleware runs BEFORE every single route handler.         |
  |  It's registered in main.py with app.add_middleware().           |
  |  FastAPI calls dispatch() automatically on every request.       |
  |                                                                 |
  +================================================================+
  |
  v
  +=== CHECK 1: SHOULD WE SKIP AUTH? ================================+
  |                                                                   |
  |  FILE:  auth_middleware.py -> _should_skip_auth(path)             |
  |                                                                   |
  |  SKIP_PATHS = (                                                   |
  |    "/health",         <- health check (load balancers need this)  |
  |    "/auth/login",     <- can't require auth to log in             |
  |    "/docs",           <- Swagger UI page itself                   |
  |    "/openapi.json",   <- Swagger UI schema file                   |
  |    "/redoc",          <- ReDoc documentation                      |
  |    "/webhooks/",      <- external system callbacks (Graph API)    |
  |  )                                                                |
  |                                                                   |
  |  HOW MATCHING WORKS:                                              |
  |    for skip_path in SKIP_PATHS:                                   |
  |        if path == skip_path or path.startswith(skip_path):        |
  |            return True                                            |
  |                                                                   |
  |  WHY startswith():                                                |
  |    So "/webhooks/ms-graph" matches "/webhooks/"                   |
  |    Covers all sub-paths under that prefix.                        |
  |                                                                   |
  |  IF SKIPPED:                                                      |
  |    -> Set request.state.username = None                           |
  |    -> Set request.state.role = None                               |
  |    -> Set request.state.tenant = None                             |
  |    -> Set request.state.is_authenticated = False                  |
  |    -> Call the route handler (no auth check)                      |
  +===================================================================+
  |
  | (path is NOT in skip list — auth check required)
  v
  +=== CHECK 2: IS THERE A BEARER TOKEN? ============================+
  |                                                                   |
  |  CODE:                                                            |
  |    auth_header = request.headers.get("Authorization", "")         |
  |    if not auth_header.startswith("Bearer "):                      |
  |        return 401 {"detail": "Not authenticated"}                 |
  |                                                                   |
  |  WHAT THIS CHECKS:                                                |
  |    The Authorization header must exist AND start with "Bearer ".  |
  |    If the header is missing or uses a different scheme (e.g.,     |
  |    "Basic"), the request is rejected immediately.                 |
  |                                                                   |
  |  TOKEN EXTRACTION:                                                |
  |    token = auth_header[7:]                                        |
  |    Slices off "Bearer " (7 chars) to get the raw JWT string.     |
  +===================================================================+
  |
  v
  +=== CHECK 3: IS THE TOKEN VALID? =================================+
  |                                                                   |
  |  FILE:  services/auth.py -> validate_token(token)                 |
  |                                                                   |
  |  DOES 4 THINGS:                                                   |
  |                                                                   |
  |  (A) DECODE + SIGNATURE VERIFICATION:                             |
  |      jwt.decode(token, SECRET_KEY, algorithms=["HS256"])          |
  |      - Splits the token into header.payload.signature             |
  |      - Recomputes HMAC-SHA256(header+payload, SECRET_KEY)         |
  |      - If computed signature != token's signature -> INVALID      |
  |      - This catches: tampered tokens, forged tokens, wrong key    |
  |                                                                   |
  |  (B) EXPIRATION CHECK:                                            |
  |      jwt.decode() automatically checks the "exp" claim.           |
  |      If current time > exp -> JWTError -> return None             |
  |      - 30-minute session means exp = iat + 1800                   |
  |      - After 30 min, token is worthless even if not blacklisted   |
  |                                                                   |
  |  (C) REQUIRED CLAIMS CHECK:                                       |
  |      required = {"sub", "role", "tenant", "exp", "iat", "jti"}   |
  |      If any claim is missing -> return None                       |
  |      - Catches malformed tokens or tokens from other systems     |
  |                                                                   |
  |  (D) BLACKLIST CHECK (LOGOUT):                                    |
  |      key = "vqms:auth:blacklist:<jti>"                            |
  |      Query: SELECT 1 FROM cache.kv_store WHERE key = $1           |
  |             AND (expires_at IS NULL OR expires_at > now)           |
  |      If found -> token was logged out -> return None              |
  |      - This is how logout works: the token is valid               |
  |        cryptographically, but we've explicitly banned it          |
  |                                                                   |
  |  IF ANY CHECK FAILS:                                              |
  |    -> return 401 {"detail": "Invalid or expired token"}           |
  |                                                                   |
  |  GRACEFUL DEGRADATION:                                            |
  |    If the cache DB is down (can't check blacklist), the           |
  |    middleware ALLOWS the token rather than blocking everyone.      |
  |    Logs a warning so we know the blacklist isn't working.         |
  +===================================================================+
  |
  v
  +=== CHECK 4: POPULATE REQUEST STATE ==============================+
  |                                                                   |
  |  FILE:  auth_middleware.py -> dispatch()                          |
  |                                                                   |
  |  Once the token is validated, the middleware extracts the          |
  |  claims and attaches them to request.state:                       |
  |                                                                   |
  |    request.state.username = payload.sub        ("admin_user")     |
  |    request.state.role = payload.role            ("ADMIN")         |
  |    request.state.tenant = payload.tenant        ("hexaware")      |
  |    request.state.is_authenticated = True                          |
  |                                                                   |
  |  WHY request.state:                                               |
  |    FastAPI's request.state is a per-request storage that lives    |
  |    for the duration of that single HTTP request. Route handlers   |
  |    can read these values without needing to decode the JWT        |
  |    themselves. The middleware does it once, routes use it freely.  |
  |                                                                   |
  |  THEN: calls the actual route handler via call_next(request)      |
  +===================================================================+
  |
  v
  +=== CHECK 5: AUTO-REFRESH (AFTER ROUTE HANDLER) ==================+
  |                                                                   |
  |  FILE:  services/auth.py -> refresh_token_if_expiring()           |
  |                                                                   |
  |  AFTER the route handler has returned its response, the           |
  |  middleware checks: is this token about to expire?                |
  |                                                                   |
  |  HOW:                                                             |
  |    remaining = payload.exp - current_time                         |
  |    if remaining <= 300 seconds (5 minutes):                       |
  |      -> Create a brand-new JWT with fresh 30-min lifetime         |
  |      -> Blacklist the OLD token (prevent reuse)                   |
  |      -> Add header: X-New-Token: eyJhbG...                       |
  |                                                                   |
  |  WHY AUTO-REFRESH:                                                |
  |    Without it, users get kicked out after 30 minutes even if      |
  |    they're actively working. With it, active users silently       |
  |    get extended sessions. Inactive users still expire.            |
  |                                                                   |
  |  HOW THE CLIENT HANDLES IT:                                       |
  |    Angular frontend checks every response for X-New-Token         |
  |    header. If present, it replaces the stored token with the      |
  |    new one. All future requests use the new token.                |
  |                                                                   |
  |  TIMELINE EXAMPLE:                                                |
  |    00:00  Login, token issued (exp = 00:30)                       |
  |    00:15  Request -> 25 min left -> no refresh                    |
  |    00:26  Request ->  4 min left -> REFRESH! New token issued     |
  |    00:26  New token (exp = 00:56), old token blacklisted          |
  |    00:40  Request with new token -> 16 min left -> no refresh     |
  |    01:10  If no requests for 30 min -> token expires naturally    |
  +===================================================================+
```


### LOGOUT FLOW

```
  User clicks "Log Out" in the frontend
  |
  |  POST /auth/logout
  |  Headers: Authorization: Bearer eyJhbG...
  |
  v
  +=== STEP 1: EXTRACT TOKEN ========================================+
  |                                                                   |
  |  FILE:  api/routes/auth.py -> logout()                            |
  |                                                                   |
  |  Reads the Authorization header, extracts the raw JWT.            |
  |  If no Bearer token -> return 401.                                |
  +===================================================================+
  |
  v
  +=== STEP 2: BLACKLIST THE TOKEN ===================================+
  |                                                                   |
  |  FILE:  services/auth.py -> blacklist_token(token)                |
  |                                                                   |
  |  WHAT HAPPENS:                                                    |
  |    1. Decode the JWT (without verifying expiry — we want to       |
  |       blacklist even expired tokens for consistency)              |
  |    2. Extract the JTI (unique token ID)                           |
  |    3. Build cache key: "vqms:auth:blacklist:<jti>"                |
  |    4. Insert into PostgreSQL cache:                               |
  |                                                                   |
  |  SQL:                                                             |
  |    INSERT INTO cache.kv_store (key, value, cached_at, expires_at) |
  |    VALUES ($1, 'blacklisted', $2, $3)                             |
  |    ON CONFLICT (key) DO UPDATE SET value = $2, expires_at = $3    |
  |                                                                   |
  |  TTL: 1800 seconds (matches JWT lifetime)                         |
  |  After 30 min, the token would have expired anyway, so the        |
  |  blacklist entry auto-cleans up.                                  |
  |                                                                   |
  |  FILE:  cache/cache_client.py -> set_with_ttl()                   |
  |  FILE:  cache/cache_client.py -> auth_blacklist_key()             |
  +===================================================================+
  |
  v
  +=== STEP 3: RESPOND ===============================================+
  |                                                                   |
  |  RESPONSE (200 OK):                                               |
  |    {"message": "Logged out successfully"}                         |
  |                                                                   |
  |  From this point, if anyone tries to use the old token:           |
  |    -> Middleware calls validate_token()                            |
  |    -> Blacklist check finds the JTI in cache.kv_store             |
  |    -> validate_token() returns None                               |
  |    -> Middleware returns 401 "Invalid or expired token"           |
  +===================================================================+
```


### WHY POSTGRESQL FOR TOKEN BLACKLIST (NOT REDIS)?

```
  +------------------------------------------------------------------+
  |  DESIGN DECISION: PostgreSQL cache instead of Redis               |
  |                                                                   |
  |  TYPICAL APPROACH:                                                |
  |    Most systems use Redis for token blacklists because it's       |
  |    fast and has built-in TTL (key expiry). But Redis adds:        |
  |      - Another server to manage                                   |
  |      - Another connection to monitor                              |
  |      - Another point of failure                                   |
  |      - Another cost line item                                     |
  |                                                                   |
  |  OUR APPROACH:                                                    |
  |    Table: cache.kv_store                                          |
  |    Columns: key (VARCHAR 512, UNIQUE), value (TEXT),               |
  |             cached_at (TIMESTAMP), expires_at (TIMESTAMP)         |
  |                                                                   |
  |    - INSERT with ON CONFLICT for atomic upsert                    |
  |    - SELECT with "expires_at > NOW()" check for TTL               |
  |    - Background cleanup job deletes expired rows every 15 min     |
  |                                                                   |
  |  TRADEOFF:                                                        |
  |    - Slightly slower than Redis (~2ms vs ~0.2ms per lookup)       |
  |    - But we already have PostgreSQL running — zero extra infra    |
  |    - For our traffic volume (hundreds of requests/min, not        |
  |      millions), the difference is negligible                     |
  |    - Simplifies deployment and monitoring                         |
  |                                                                   |
  |  HOW TO EXPLAIN TO YOUR MANAGER:                                  |
  |    "Instead of adding another server (Redis) just for login       |
  |     tracking, we reuse the database we already have. It's a       |
  |     little slower but saves us infrastructure cost and            |
  |     complexity. We can switch to Redis later if we need to."     |
  +------------------------------------------------------------------+
```


### DATABASE TABLES USED BY AUTH

```
  +=== TABLE: public.tbl_users ======================================+
  |                                                                   |
  |  PURPOSE: Stores user identity and credentials                    |
  |                                                                   |
  |  COLUMNS:                                                         |
  |    id             SERIAL PRIMARY KEY                              |
  |    user_name      VARCHAR UNIQUE        "admin_user"              |
  |    email_id       VARCHAR UNIQUE        "admin@vqms.local"        |
  |    tenant         VARCHAR               "hexaware"                |
  |    password       TEXT                  "scrypt:32768:8:1$..."     |
  |    status         VARCHAR               "ACTIVE" / "INACTIVE"     |
  |    security_q1    TEXT (nullable)        Security question 1       |
  |    security_a1    TEXT (nullable)        Answer 1                  |
  |    security_q2    TEXT (nullable)        Security question 2       |
  |    security_a2    TEXT (nullable)        Answer 2                  |
  |    security_q3    TEXT (nullable)        Security question 3       |
  |    security_a3    TEXT (nullable)        Answer 3                  |
  |                                                                   |
  |  NOTE: password column stores werkzeug scrypt hash, NOT plain     |
  |        text. The hash is ~100 chars long and includes the salt.   |
  +===================================================================+

  +=== TABLE: public.tbl_user_roles =================================+
  |                                                                   |
  |  PURPOSE: Maps users to their roles (authorization)               |
  |                                                                   |
  |  COLUMNS:                                                         |
  |    slno           SERIAL PRIMARY KEY                              |
  |    first_name     VARCHAR               "Admin"                   |
  |    last_name      VARCHAR               "User"                    |
  |    email_id       VARCHAR               "admin@vqms.local"        |
  |    user_name      VARCHAR               "admin_user"              |
  |    tenant         VARCHAR               "hexaware"                |
  |    role           VARCHAR               "ADMIN"                   |
  |    created_by     VARCHAR (nullable)     who created this role     |
  |    created_date   TIMESTAMP (nullable)   when                     |
  |    modified_by    VARCHAR (nullable)     who changed it            |
  |    modified_date  TIMESTAMP (nullable)   when                     |
  |    deleted_by     VARCHAR (nullable)     soft delete by whom       |
  |    deleted_date   TIMESTAMP (nullable)   soft delete when          |
  +===================================================================+

  +=== TABLE: cache.kv_store =========================================+
  |                                                                   |
  |  PURPOSE: General key-value cache (used by auth for blacklist)    |
  |                                                                   |
  |  COLUMNS:                                                         |
  |    key            VARCHAR(512) UNIQUE    cache key                 |
  |    value          TEXT                   cached value              |
  |    cached_at      TIMESTAMP             when the entry was set    |
  |    expires_at     TIMESTAMP (nullable)   when it should expire    |
  |                                                                   |
  |  AUTH BLACKLIST EXAMPLE:                                          |
  |    key:        "vqms:auth:blacklist:e11e49d2-c111-4651-..."       |
  |    value:      "blacklisted"                                      |
  |    cached_at:  2026-04-14 10:05:24 IST                            |
  |    expires_at: 2026-04-14 10:35:24 IST (30 min TTL)              |
  +===================================================================+
```


### STARTUP WIRING — HOW AUTH GETS INITIALIZED

```
  +=================================================================+
  |  FILE:  main.py -> lifespan()                                    |
  |                                                                   |
  |  The auth service needs the PostgresConnector to query            |
  |  tbl_users and tbl_user_roles. But the connector is only         |
  |  created at startup. Here's how the wiring works:                |
  |                                                                   |
  |  STARTUP SEQUENCE:                                                |
  |                                                                   |
  |  1. FastAPI app starts, lifespan() is called                      |
  |  2. PostgresConnector is created and connected:                   |
  |       postgres = PostgresConnector(settings)                      |
  |       await postgres.connect()                                    |
  |       app.state.postgres = postgres                               |
  |                                                                   |
  |  3. Auth service is initialized with the connector:               |
  |       from services.auth import init_auth_service                 |
  |       init_auth_service(postgres)                                 |
  |       # This sets module-level _pg = postgres                     |
  |       # Now all auth functions can access the database            |
  |                                                                   |
  |  4. AuthMiddleware is registered:                                 |
  |       app.add_middleware(AuthMiddleware)                           |
  |       # Now every request passes through the JWT check            |
  |                                                                   |
  |  WHY MODULE-LEVEL _pg (NOT dependency injection):                 |
  |    The auth functions (validate_token, authenticate_user) are     |
  |    called from the middleware, which doesn't have access to       |
  |    FastAPI's dependency injection system. A module-level          |
  |    variable is the simplest way to give the middleware access     |
  |    to the database. init_auth_service() makes this explicit.     |
  |                                                                   |
  |  IF POSTGRES IS DOWN AT STARTUP:                                  |
  |    -> init_auth_service() is never called                         |
  |    -> _pg stays None                                              |
  |    -> authenticate_user() raises RuntimeError                     |
  |    -> Login returns 500 Internal Server Error                     |
  |    -> This is correct: can't log in without a database            |
  +=================================================================+
```


### SWAGGER UI AUTHORIZE BUTTON

```
  +=================================================================+
  |  FILE:  main.py -> custom_openapi()                              |
  |                                                                   |
  |  HOW THE AUTHORIZE BUTTON WORKS:                                  |
  |                                                                   |
  |  1. main.py defines a custom OpenAPI schema that includes:        |
  |       securitySchemes:                                            |
  |         BearerAuth:                                               |
  |           type: http                                              |
  |           scheme: bearer                                          |
  |           bearerFormat: JWT                                       |
  |                                                                   |
  |  2. This tells Swagger UI: "there's a Bearer auth scheme"        |
  |     -> Swagger renders the "Authorize" button (top-right)        |
  |                                                                   |
  |  3. User workflow in Swagger:                                     |
  |     a. Call POST /auth/login -> get token in response             |
  |     b. Click "Authorize" button                                   |
  |     c. Paste the token value (no "Bearer " prefix needed)         |
  |     d. Click "Authorize" -> "Close"                               |
  |     e. Now every request automatically includes:                  |
  |          Authorization: Bearer <pasted-token>                     |
  |     f. All protected endpoints work (GET /vendors, etc.)          |
  |                                                                   |
  |  4. The lock icon next to each endpoint shows it requires auth.   |
  |     Open lock = public. Closed lock = needs JWT.                  |
  +=================================================================+
```


### COMPLETE AUTH FILE MAP

```
  +------------------------------------------------------+-----------+
  |  File                                                |  Purpose  |
  +------------------------------------------------------+-----------+
  |                                                                   |
  |  models/auth.py                                                   |
  |    LoginRequest              Pydantic: username + password        |
  |    LoginResponse             Pydantic: token + user info          |
  |    TokenPayload              Pydantic: decoded JWT claims         |
  |    UserRecord                Pydantic: tbl_users row (no pwd)     |
  |    UserRoleRecord            Pydantic: tbl_user_roles row         |
  |                                                                   |
  |  services/auth.py                                                 |
  |    init_auth_service(pg)     Set module-level DB connector        |
  |    authenticate_user()       Full login: DB lookup + hash + JWT   |
  |    create_access_token()     Build JWT with claims + sign         |
  |    validate_token()          Decode + verify + blacklist check    |
  |    blacklist_token()         Logout: add JTI to cache blacklist   |
  |    refresh_token_if_expiring()  Auto-refresh near-expiry tokens  |
  |                                                                   |
  |  api/routes/auth.py                                               |
  |    POST /auth/login          Endpoint: credentials -> JWT         |
  |    POST /auth/logout         Endpoint: blacklist current token    |
  |                                                                   |
  |  api/middleware/auth_middleware.py                                 |
  |    AuthMiddleware.dispatch() Intercepts EVERY request             |
  |    _should_skip_auth()      Check if path bypasses auth           |
  |                                                                   |
  |  cache/cache_client.py                                            |
  |    auth_blacklist_key()      Build cache key for blacklist        |
  |    set_with_ttl()            Insert key-value with expiry         |
  |    exists_key()              Check if key exists (not expired)    |
  |    cleanup_expired()         Delete expired cache rows            |
  |                                                                   |
  |  config/settings.py                                               |
  |    jwt_secret_key            HMAC signing secret (from .env)      |
  |    jwt_algorithm             "HS256"                              |
  |    session_timeout_seconds   1800 (30 min token lifetime)         |
  |    token_refresh_threshold   300 (refresh within 5 min of exp)    |
  |                                                                   |
  |  main.py                                                          |
  |    lifespan()                Calls init_auth_service(postgres)    |
  |    custom_openapi()          Adds Authorize button to Swagger     |
  |    app.add_middleware()      Registers AuthMiddleware             |
  +------------------------------------------------------+-----------+
```


### SECURITY SUMMARY

```
  +------------------------------------------------------------------+
  |  WHAT WE PROTECT AGAINST:                                         |
  |                                                                   |
  |  1. CREDENTIAL STUFFING                                           |
  |     -> Passwords are scrypt-hashed (CPU-intensive to brute force)|
  |     -> Generic "Invalid credentials" error (no username leak)    |
  |                                                                   |
  |  2. TOKEN THEFT                                                   |
  |     -> 30-minute expiry limits damage window                     |
  |     -> Logout immediately blacklists the stolen token            |
  |                                                                   |
  |  3. TOKEN TAMPERING                                               |
  |     -> HMAC-SHA256 signature verification on every request        |
  |     -> Any modification invalidates the signature                |
  |                                                                   |
  |  4. REPLAY ATTACKS                                                |
  |     -> JTI (unique token ID) allows per-token blacklisting       |
  |     -> Refreshed tokens blacklist the old one                    |
  |                                                                   |
  |  5. SESSION HIJACKING                                             |
  |     -> Short TTL (30 min) limits exposure                        |
  |     -> Auto-refresh only for active users                        |
  |                                                                   |
  |  6. INACTIVE ACCOUNTS                                             |
  |     -> Status check at login (ACTIVE required)                   |
  |     -> Admin can deactivate without deleting                     |
  |                                                                   |
  |  WHAT WE DO NOT YET PROTECT AGAINST (production TODO):           |
  |     -> Rate limiting on /auth/login (brute force)                |
  |     -> Account lockout after N failed attempts                   |
  |     -> HTTPS enforcement (handled by API Gateway in prod)        |
  |     -> Refresh token rotation (separate long-lived refresh flow)  |
  |     -> CORS tightening (currently allows localhost origins)       |
  +------------------------------------------------------------------+
```

---

## 9. API DOCUMENTATION — COMPLETE ENDPOINT REFERENCE

```
  FILES:
    api/routes/auth.py               — POST /auth/login, POST /auth/logout
    api/routes/vendors.py            — GET /vendors, POST /vendors, PUT /vendors/{id}, DELETE /vendors/{id}
    api/routes/queries.py            — POST /queries, GET /queries/{query_id}
    api/routes/emails.py             — GET /emails, GET /emails/stats, GET /emails/{qid}, GET .../download
    api/routes/webhooks.py           — POST /webhooks/ms-graph
    api/routes/health.py             — GET /health
    api/middleware/auth_middleware.py — JWT validation on every request
    services/auth.py                 — Login logic, JWT, blacklist
    services/portal_submission.py    — Query submission pipeline
    services/email_dashboard/        — Email listing & stats (folder module)
    adapters/salesforce/             — Vendor CRUD (Salesforce, folder module)
    adapters/graph_api/              — Email webhook processing (folder module)
```

### How to Explain to Your Manager

> "Our system has 14 API endpoints that handle everything: logging in,
>  managing vendors, submitting queries, viewing emails, and receiving
>  webhook notifications. Every endpoint is secured with JWT tokens
>  except health checks and the login page itself. Admin endpoints
>  (vendor management) require the ADMIN role."


### MASTER ENDPOINT TABLE

```
  +------+---------------------------------------------------+-----------+-----------+------------------+
  | #    | Endpoint                                          | Auth      | Role      | Purpose          |
  +------+---------------------------------------------------+-----------+-----------+------------------+
  |  1   | POST   /auth/login                                | None      | Any       | Get JWT token    |
  |  2   | POST   /auth/logout                               | Bearer    | Any       | Invalidate token |
  |  3   | GET    /vendors                                   | Bearer    | ADMIN     | List vendors     |
  |  4   | POST   /vendors                                   | Bearer    | ADMIN     | Create vendor    |
  |  5   | PUT    /vendors/{vendor_id}                       | Bearer    | ADMIN     | Update vendor    |
  |  6   | DELETE /vendors/{vendor_id}                       | Bearer    | ADMIN     | Delete vendor    |
  |  7   | POST   /queries                                   | Bearer    | Any       | Submit query     |
  |  8   | GET    /queries/{query_id}                        | Bearer    | Any       | Query status     |
  |  9   | GET    /emails                                    | Bearer    | Any       | Email list       |
  | 10   | GET    /emails/stats                              | Bearer    | Any       | Email stats      |
  | 11   | GET    /emails/{query_id}                         | Bearer    | Any       | Email detail     |
  | 12   | GET    /emails/{qid}/attachments/{aid}/download   | Bearer    | Any       | Download file    |
  | 13   | POST   /webhooks/ms-graph                         | None*     | —         | Email webhook    |
  | 14   | GET    /health                                    | None      | —         | Health check     |
  +------+---------------------------------------------------+-----------+-----------+------------------+

  * Webhooks use MS Graph validation tokens, not JWT
  ADMIN = Only users with role "ADMIN" in tbl_user_roles
  Any   = Any authenticated user (ADMIN, VENDOR, or REVIEWER)
```


### REQUEST FLOW — HOW EVERY API CALL WORKS

```
  Client (Angular / Swagger / Postman)
      |
      |  HTTP Request + Authorization: Bearer <jwt>
      |
      v
  +------------------------------------------------------------------+
  | FASTAPI APPLICATION                                               |
  |                                                                   |
  |  STEP 1: AuthMiddleware.dispatch()                                |
  |    api/middleware/auth_middleware.py                                |
  |                                                                   |
  |    Is path in SKIP_PATHS?                                         |
  |      /health, /auth/login, /docs, /openapi.json, /redoc,         |
  |      /webhooks/*                                                  |
  |        YES -> pass through to route handler                       |
  |        NO  -> validate JWT token:                                 |
  |               1. Extract "Bearer <token>" from header             |
  |               2. Decode JWT (check signature + expiry)            |
  |               3. Check blacklist (cache.kv_store lookup)          |
  |               4. Set request.state.user = TokenPayload            |
  |               5. If token expires in < 5 min:                     |
  |                  -> create new JWT                                |
  |                  -> add X-New-Token response header               |
  |               6. If token invalid/expired/blacklisted:            |
  |                  -> return 401 Unauthorized                       |
  |                                                                   |
  |  STEP 2: Route handler executes                                   |
  |    (GET /vendors, POST /queries, etc.)                            |
  |                                                                   |
  |  STEP 3: Security headers added to response                      |
  |    Content-Security-Policy, X-Content-Type-Options,               |
  |    X-XSS-Protection, X-Frame-Options, HSTS,                      |
  |    Referrer-Policy, Permissions-Policy, Cache-Control             |
  |                                                                   |
  +------------------------------------------------------------------+
```


### 9.1 POST /auth/login

```
  PURPOSE: Authenticate user and get JWT token
  FILE:    api/routes/auth.py -> login()
  MODEL:   models/auth.py -> LoginRequest, LoginResponse
  AUTH:    None (public endpoint)

  REQUEST:
    POST /auth/login
    Content-Type: application/json
    {
      "username_or_email": "admin_user",
      "password": "admin123"
    }

  INTERNAL FLOW:
    1. Pydantic validates LoginRequest
    2. services/auth.py -> authenticate_user()
       a. SELECT from tbl_users (match username OR email)
       b. Check status == "ACTIVE"
       c. werkzeug.check_password_hash() (in background thread)
       d. SELECT role from tbl_user_roles
       e. Create JWT (sub, role, tenant, exp, iat, jti)
    3. Return LoginResponse

  SUCCESS (200):
    {
      "token": "eyJhbGciOiJIUzI1NiIs...",
      "user_name": "admin_user",
      "email": "admin@vqms.local",
      "role": "ADMIN",
      "tenant": "hexaware",
      "vendor_id": null
    }

  ERRORS:
    401 "Invalid credentials"      — wrong username or password
    401 "Account is inactive"      — user status != ACTIVE
    422 validation error           — missing required fields
```


### 9.2 POST /auth/logout

```
  PURPOSE: Invalidate current JWT token
  FILE:    api/routes/auth.py -> logout()
  AUTH:    Bearer token required

  REQUEST:
    POST /auth/logout
    Authorization: Bearer eyJhbG...

  INTERNAL FLOW:
    1. Extract token from Authorization header
    2. Decode JWT to get jti (unique token ID)
    3. Save to blacklist: cache.kv_store
       key = "vqms:auth:blacklist:<jti>"
       TTL = remaining token lifetime
    4. Return success

  SUCCESS (200):
    { "message": "Logged out successfully" }

  ERRORS:
    401 "No token provided"        — missing Authorization header
    400 decode error               — malformed token
```


### 9.3 GET /vendors

```
  PURPOSE: List all active vendors from Salesforce
  FILE:    api/routes/vendors.py -> get_all_vendors()
  AUTH:    Bearer token, ADMIN role required (403 for VENDOR/REVIEWER)

  REQUEST:
    GET /vendors
    Authorization: Bearer eyJhbG...

  INTERNAL FLOW:
    1. AuthMiddleware validates JWT
    2. _require_admin() checks role == "ADMIN"
    3. adapters/salesforce/ -> get_all_active_vendors()
       SOQL: SELECT Id, Name, Vendor_ID__c, ...
             FROM Vendor_Account__c
             WHERE Vendor_Status__c = 'Active'
             ORDER BY Vendor_ID__c ASC
    4. Map Salesforce field names to Python snake_case
    5. Return list of VendorAccountData objects

  SUCCESS (200):
    [
      {
        "id": "001al00002Ie1zjAAB",
        "name": "TechNova Solutions",
        "vendor_id": "V-001",
        "vendor_tier": "Platinum",
        "category": "IT Services",
        "billing_city": "Mumbai",
        ...
      }
    ]

  ERRORS:
    401 "Not authenticated"        — missing/invalid token
    403 "Admin access required"    — user is not ADMIN
    502 "Salesforce query failed"  — Salesforce API down
```


### 9.4 POST /vendors (Create)

```
  PURPOSE: Create new Vendor_Account__c in Salesforce
  FILE:    api/routes/vendors.py -> create_vendor()
  AUTH:    Bearer token, ADMIN role required

  REQUEST:
    POST /vendors
    Authorization: Bearer eyJhbG...
    Content-Type: application/json
    {
      "name": "NewVendor Corp",          <-- REQUIRED
      "vendor_tier": "Silver",           <-- optional
      "billing_city": "Pune",            <-- optional
      ...
    }

  INTERNAL FLOW:
    1. AuthMiddleware + _require_admin()
    2. Pydantic validates VendorCreateRequest (name required)
    3. Convert Python fields to Salesforce API names
    4. get_next_vendor_id():
       Query all Vendor_ID__c -> find max -> V-{max+1}
    5. Salesforce Vendor_Account__c.create(data)
    6. Fetch full record back
    7. Return success + full vendor record

  VENDOR ID AUTO-GENERATION:
    Existing: V-001, V-002, ..., V-025
    Next:     V-026 (max + 1, zero-padded to 3 digits)

  SUCCESS (201):
    {
      "success": true,
      "salesforce_id": "a02al00000oA5XXAA0",
      "vendor_id": "V-026",
      "name": "NewVendor Corp",
      "message": "Vendor 'NewVendor Corp' created with ID V-026",
      "vendor": { ... full record ... }
    }

  ERRORS:
    401 / 403 / 422 / 502 (same patterns as GET /vendors)
```


### 9.5 PUT /vendors/{vendor_id}

```
  PURPOSE: Update fields of a Vendor_Account__c record
  FILE:    api/routes/vendors.py -> update_vendor()
  AUTH:    Bearer token, ADMIN role required

  REQUEST:
    PUT /vendors/V-001        (or PUT /vendors/a02al00000oA5JOAA0)
    Authorization: Bearer eyJhbG...
    Content-Type: application/json
    {
      "vendor_tier": "Gold",
      "payment_terms": "Net 45"
    }

  VENDOR ID FORMATS (both accepted):
    Format 1: Salesforce Record ID  (a02al00000oA5JOAA0) — used directly
    Format 2: Custom Vendor Code    (V-001) — SOQL lookup to resolve

  UPDATABLE FIELDS:
    website, vendor_tier, category, payment_terms,
    annual_revenue, sla_response_hours, sla_resolution_days,
    vendor_status, onboarded_date, billing_city,
    billing_state, billing_country

  SUCCESS (200):
    {
      "success": true,
      "vendor_id": "V-001",
      "updated_fields": ["Vendor_Tier__c", "Payment_Terms__c"],
      "message": "Updated 2 field(s) for vendor V-001",
      "vendor": { ... full record after update ... }
    }

  ERRORS:
    422 "At least one field must be provided" — empty body
```


### 9.6 DELETE /vendors/{vendor_id}

```
  PURPOSE: Permanently delete Vendor_Account__c from Salesforce
  FILE:    api/routes/vendors.py -> delete_vendor()
  AUTH:    Bearer token, ADMIN role required
  WARNING: Permanent deletion — no undo!

  REQUEST:
    DELETE /vendors/V-025
    Authorization: Bearer eyJhbG...

  INTERNAL FLOW:
    1. AuthMiddleware + _require_admin()
    2. Detect vendor_id format (Record ID or Vendor Code)
    3. If Vendor Code: SOQL lookup to resolve to Record ID
    4. Vendor_Account__c.delete(record_id)
    5. Return success

  SUCCESS (200):
    {
      "success": true,
      "vendor_id": "V-025",
      "message": "Vendor V-025 deleted successfully"
    }
```


### 9.7 POST /queries

```
  PURPOSE: Submit a new vendor query from the portal
  FILE:    api/routes/queries.py -> submit_query_endpoint()
  SERVICE: services/portal_submission.py -> PortalIntakeService
  AUTH:    Bearer token required

  REQUEST:
    POST /queries
    Authorization: Bearer eyJhbG...
    X-Vendor-ID: 001al00002Ie1zsAAB      <-- REQUIRED header
    Content-Type: application/json
    {
      "query_type": "invoice",
      "subject": "Invoice INV-2026-1234 payment status",
      "description": "We submitted invoice INV-2026-1234 on March 15...",
      "priority": "HIGH",
      "reference_number": "INV-2026-1234"
    }

  INPUT VALIDATION:
    query_type:       required, any string
    subject:          required, 5-500 characters
    description:      required, 10-5000 characters
    priority:         optional, LOW/MEDIUM/HIGH/CRITICAL (default MEDIUM)
    reference_number: optional

  INTERNAL FLOW:
    1. AuthMiddleware validates JWT
    2. Pydantic validates QuerySubmission
    3. PortalIntakeService.submit_query():
       a. Generate SHA-256 idempotency hash(vendor_id + subject + description)
       b. INSERT INTO cache.idempotency_keys ON CONFLICT DO NOTHING
          -> if already exists: 409 Duplicate
       c. Generate IDs: query_id (VQ-2026-XXXX), correlation_id, execution_id
       d. Create UnifiedQueryPayload
       e. INSERT into workflow.case_execution
       f. Publish "QueryReceived" to EventBridge
       g. Enqueue to SQS (vqms-query-intake queue)
       h. Return query_id + status

  SUCCESS (201):
    {
      "query_id": "VQ-2026-0042",
      "status": "RECEIVED"
    }

  WHAT HAPPENS NEXT:
    SQS consumer picks up the message
    -> LangGraph pipeline runs (Steps 7-12)
    -> AI analyzes, routes, drafts, validates, delivers

  ERRORS:
    401 "Not authenticated"
    409 "Duplicate query: <hash>"
    422 validation error (subject < 5 chars, etc.)
    503 "Portal Intake Service unavailable"
```


### 9.8 GET /queries/{query_id}

```
  PURPOSE: Check the status of a submitted query
  FILE:    api/routes/queries.py -> get_query_status()
  AUTH:    Bearer token required

  REQUEST:
    GET /queries/VQ-2026-0042
    Authorization: Bearer eyJhbG...
    X-Vendor-ID: 001al00002Ie1zsAAB      <-- ownership check

  INTERNAL FLOW:
    SELECT query_id, status, source, processing_path,
           created_at, updated_at
    FROM workflow.case_execution
    WHERE query_id = $1 AND vendor_id = $2

  STATUS VALUES:
    RECEIVED           — query entered the system
    ANALYZING          — AI pipeline is processing
    ROUTING            — being routed to correct team
    DRAFTING           — generating email draft
    QUALITY_CHECK      — quality gate validating draft
    VALIDATED          — draft passed quality gate
    RESOLVED           — answer sent (Path A complete)
    AWAITING_RESOLUTION— ack sent, team investigating (Path B)
    PAUSED             — waiting for human review (Path C)
    CLOSED             — fully resolved and closed

  SUCCESS (200):
    {
      "query_id": "VQ-2026-0042",
      "status": "RECEIVED",
      "source": "portal",
      "processing_path": null,
      "created_at": "2026-04-14 14:30:00",
      "updated_at": "2026-04-14 14:30:00"
    }

  ERRORS:
    401 / 404 "Query not found" (wrong ID or wrong vendor)
```


### 9.9 GET /emails

```
  PURPOSE: Paginated list of email chains for the dashboard
  FILE:    api/routes/emails.py -> list_emails()
  SERVICE: services/email_dashboard/ -> EmailDashboardService
  AUTH:    Bearer token required

  REQUEST:
    GET /emails?page=1&page_size=20&status=New&priority=High&search=invoice&sort_by=timestamp&sort_order=desc

  QUERY PARAMETERS:
    page       — integer, default 1 (>= 1)
    page_size  — integer, default 20 (1-100)
    status     — "New", "Reopened", "Resolved" (optional)
    priority   — "High", "Medium", "Low" (optional)
    search     — searches subject + sender email (optional)
    sort_by    — "timestamp", "status", "priority" (default timestamp)
    sort_order — "asc", "desc" (default desc)

  INTERNAL FLOW (4-query pattern):
    Query 1: COUNT — total matching records
    Query 2: PAGE KEYS — 20 thread keys for this page
    Query 3: EMAILS — all emails for those 20 threads
    Query 4: ATTACHMENTS — all attachments for those emails
    Group by conversation_id into chains

  SUCCESS (200):
    {
      "total": 47,
      "page": 1,
      "page_size": 20,
      "mail_chains": [
        {
          "conversation_id": "AAQkADY3...",
          "mail_items": [
            {
              "query_id": "VQ-2026-0001",
              "sender": {"name": "Rajesh Kumar", "email": "rajesh@technova.com"},
              "subject": "Invoice INV-2026-001 payment query",
              "body": "Dear Team...",
              "timestamp": "2026-04-10T09:30:00+05:30",
              "attachments": [...],
              "thread_status": "NEW"
            }
          ],
          "status": "New",
          "priority": "High"
        }
      ]
    }
```


### 9.10 GET /emails/stats

```
  PURPOSE: Aggregate statistics for the email dashboard
  FILE:    api/routes/emails.py -> get_email_stats()
  SERVICE: services/email_dashboard/ -> EmailDashboardService
  AUTH:    Bearer token required

  REQUEST:
    GET /emails/stats
    Authorization: Bearer eyJhbG...

  INTERNAL FLOW:
    Single SQL query using COUNT with FILTER clauses:
    SELECT
      COUNT(*) AS total_emails,
      COUNT(*) FILTER (WHERE status IN (...)) AS new_count,
      COUNT(*) FILTER (WHERE status = 'REOPENED') AS reopened,
      COUNT(*) FILTER (WHERE status IN (...)) AS resolved,
      COUNT(*) FILTER (WHERE priority = 'HIGH') AS high,
      COUNT(*) FILTER (WHERE priority = 'MEDIUM') AS medium,
      COUNT(*) FILTER (WHERE priority = 'LOW') AS low,
      COUNT(*) FILTER (WHERE created_at >= today) AS today,
      COUNT(*) FILTER (WHERE created_at >= 7_days_ago) AS week
    FROM intake.email_messages em
    JOIN workflow.case_execution ce ON ...
    WHERE ce.source = 'email'

    One query, one round-trip, all stats.

  SUCCESS (200):
    {
      "total_emails": 156,
      "new_count": 23,
      "reopened_count": 5,
      "resolved_count": 128,
      "priority_breakdown": {"High": 34, "Medium": 89, "Low": 33},
      "today_count": 7,
      "this_week_count": 42
    }
```


### 9.11 GET /emails/{query_id}

```
  PURPOSE: Single email chain with full thread detail
  FILE:    api/routes/emails.py -> get_email_detail()
  AUTH:    Bearer token required

  REQUEST:
    GET /emails/VQ-2026-0001
    Authorization: Bearer eyJhbG...

  INTERNAL FLOW:
    1. Look up email by query_id
    2. If has conversation_id: fetch ALL emails in thread
    3. If no conversation_id: return single email as chain
    4. Fetch attachments for all emails in chain
    5. Return MailChainResponse

  SUCCESS (200):
    {
      "conversation_id": "AAQkADY3...",
      "mail_items": [
        {
          "query_id": "VQ-2026-0001",
          "sender": {"name": "Rajesh Kumar", "email": "rajesh@technova.com"},
          "subject": "Invoice query",
          "body": "Dear Team...",
          "timestamp": "2026-04-10T09:30:00+05:30",
          "attachments": [],
          "thread_status": "NEW"
        },
        {
          "query_id": "VQ-2026-0003",
          "subject": "Re: Invoice query",
          "thread_status": "EXISTING_OPEN"
        }
      ],
      "status": "New",
      "priority": "High"
    }

  ERRORS:
    404 "Email chain not found for query_id: VQ-2026-9999"
```


### 9.12 GET /emails/{query_id}/attachments/{attachment_id}/download

```
  PURPOSE: Get temporary download URL for an email attachment
  FILE:    api/routes/emails.py -> download_attachment()
  AUTH:    Bearer token required

  REQUEST:
    GET /emails/VQ-2026-0001/attachments/att-001/download
    Authorization: Bearer eyJhbG...

  INTERNAL FLOW:
    1. Look up attachment in intake.email_attachments
    2. If not found: 404
    3. If no s3_key: 404
    4. Generate presigned URL from S3 (valid 1 hour)
    5. Return URL + metadata

  SUCCESS (200):
    {
      "attachment_id": "att-001",
      "filename": "invoice.pdf",
      "download_url": "https://vqms-data-store.s3.amazonaws.com/attachments/...",
      "expires_in_seconds": 3600
    }
```


### 9.13 POST /webhooks/ms-graph

```
  PURPOSE: Receive email notifications from Microsoft Graph API
  FILE:    api/routes/webhooks.py -> handle_graph_notification()
  AUTH:    None (MS Graph validation tokens, not JWT)

  TWO SCENARIOS:

  SCENARIO 1: VALIDATION HANDSHAKE
    When we subscribe, Microsoft sends a validation request.
    POST /webhooks/ms-graph?validationToken=abc123xyz
    Response: 200 OK with body "abc123xyz" (plain text)

  SCENARIO 2: EMAIL NOTIFICATION
    When a new email arrives:
    POST /webhooks/ms-graph
    { "value": [{ "resource": "Users/.../Messages/AAMk123..." }] }

    Internal flow:
      1. Parse notification body
      2. Extract message_id from resource path
      3. Call services/email_intake/ -> process_email()
      4. Results: Success (log) / Duplicate (skip) / Error (log)
      5. Return {"status": "accepted"}

  NOTE: Always returns 200 — Microsoft retries on non-200,
  which would flood us with duplicate notifications.
```


### 9.14 GET /health

```
  PURPOSE: Application health check (load balancers, monitoring)
  FILE:    api/routes/health.py -> health_check()
  AUTH:    None (public endpoint)

  REQUEST:
    GET /health

  INTERNAL FLOW:
    1. Check if app.state.postgres exists
    2. Run postgres.health_check() (SELECT 1)
    3. Return status

  SUCCESS (200):
    {
      "status": "healthy",
      "app": "vqms",
      "version": "0.1.0",
      "database": "connected"       (or "disconnected")
    }
```


### SECURITY HEADERS ON EVERY RESPONSE

```
  +-------------------------------+-------------------------------------------+
  | Header                        | What It Protects Against                  |
  +-------------------------------+-------------------------------------------+
  | Content-Security-Policy       | XSS — only allows scripts from our domain |
  | Server: hidden                | Hides server identity (uvicorn)           |
  | X-Content-Type-Options:       | Prevents MIME sniffing attacks             |
  |   nosniff                     |                                           |
  | X-XSS-Protection: 1;mode=block| Legacy XSS filter for older browsers      |
  | X-Frame-Options: DENY         | Prevents clickjacking (no iframes)        |
  | Strict-Transport-Security     | Forces HTTPS for 1 year                   |
  | Referrer-Policy: no-referrer  | Don't leak URLs to external sites         |
  | Permissions-Policy            | Blocks unused browser APIs                |
  | Cache-Control: no-store       | Never cache API responses                 |
  +-------------------------------+-------------------------------------------+
```


### ERROR CODE QUICK REFERENCE

```
  +------+-------------------------+-------------------------------------------+
  | Code | Meaning                 | When You'll See It                        |
  +------+-------------------------+-------------------------------------------+
  | 200  | OK                      | Successful GET, logout, update, delete    |
  | 201  | Created                 | POST /queries or POST /vendors succeeded  |
  | 400  | Bad Request             | Malformed logout request                  |
  | 401  | Unauthorized            | No/expired/blacklisted/invalid token      |
  | 403  | Forbidden               | Not ADMIN for vendor CRUD endpoints       |
  | 404  | Not Found               | Query/attachment/email not found           |
  | 409  | Conflict                | Duplicate query (same vendor+subject+desc)|
  | 422  | Unprocessable Entity    | Validation failed (short subject, etc.)   |
  | 502  | Bad Gateway             | Salesforce API call failed                |
  | 503  | Service Unavailable     | DB or service not connected at startup    |
  +------+-------------------------+-------------------------------------------+
```


### QUICK START: TESTING ALL APIs IN ORDER

```
  STEP  1: GET  /health                              (no auth)
  STEP  2: POST /auth/login                          (get token)
            Body: {"username_or_email":"admin_user","password":"admin123"}
            --> Save the "token" from response

  STEP  3: Set header for ALL remaining requests:
            Authorization: Bearer <token>

  STEP  4: GET  /vendors                             (list vendors, ADMIN)
  STEP  5: POST /vendors                             (create vendor, ADMIN)
            Body: {"name":"Test Corp","vendor_tier":"Silver"}
            --> Save "vendor_id" (V-026)

  STEP  6: PUT  /vendors/V-026                       (update vendor, ADMIN)
            Body: {"vendor_tier":"Gold"}

  STEP  7: DELETE /vendors/V-026                     (delete vendor, ADMIN)

  STEP  8: POST /queries                             (submit query)
            Headers: X-Vendor-ID: 001al00002Ie1zsAAB
            Body: {"query_type":"invoice","subject":"Test query",
                   "description":"Testing the query API","priority":"LOW"}
            --> Save "query_id" (VQ-2026-XXXX)

  STEP  9: GET  /queries/VQ-2026-XXXX                (check status)
            Headers: X-Vendor-ID: 001al00002Ie1zsAAB

  STEP 10: GET  /emails                              (email dashboard)
  STEP 11: GET  /emails/stats                        (dashboard stats)
  STEP 12: POST /auth/logout                         (invalidate token)
            --> Token is now blacklisted
```


### SWAGGER UI USAGE

```
  +-----------------------------------------------------------+
  |                                                           |
  |  1. Open http://localhost:8001/docs                       |
  |                                                           |
  |  2. POST /auth/login -> "Try it out" ->                   |
  |     {"username_or_email":"admin_user","password":"admin123"}|
  |     -> Execute -> Copy "token" from response              |
  |                                                           |
  |  3. Click green "Authorize" button (top-right)            |
  |     Paste token (without quotes) -> Authorize -> Close    |
  |                                                           |
  |  4. ALL endpoints now include your token automatically    |
  |     Try any endpoint!                                     |
  |                                                           |
  +-----------------------------------------------------------+
```


### API-TO-PIPELINE CONNECTION MAP

This shows how API endpoints connect to the AI pipeline:

```
  POST /queries (portal submission)
      |
      v
  PortalIntakeService.submit_query()
      |
      |  1. Idempotency check (PostgreSQL)
      |  2. Generate IDs (VQ-2026-XXXX)
      |  3. INSERT case_execution
      |  4. EventBridge: "QueryReceived"
      |  5. SQS: enqueue payload
      |
      v
  SQS Consumer picks up message
      |
      v
  LangGraph Pipeline (Steps 7-12)
      |
      +-- Step 7:  Context Loading (vendor profile + history)
      +-- Step 8:  Query Analysis (LLM Call #1)
      +-- Decision Point 1: Confidence >= 0.85?
      |     NO  -> Path C (PAUSED, triage queue)
      |     YES -> continue
      +-- Step 9A: Routing (team + SLA)
      +-- Step 9B: KB Search (pgvector similarity)
      +-- Decision Point 2: KB match >= 0.80?
      |     YES -> Path A: Resolution (LLM Call #2, full answer)
      |     NO  -> Path B: Acknowledgment (LLM Call #2, receipt only)
      +-- Step 11: Quality Gate (7 checks)
      +-- Step 12: Delivery (ServiceNow ticket + email send)
      |
      v
  GET /queries/{query_id} (vendor checks status)
      |
      v
  Status progresses: RECEIVED -> ANALYZING -> ROUTING ->
    DRAFTING -> QUALITY_CHECK -> VALIDATED -> RESOLVED (or AWAITING_RESOLUTION)
```

---

*This document references real code at `vqm_ps/src/`.
Every class name, method name, file path, and SQL query is from the actual codebase.
For full API details with every field and edge case, see `docs/api_documentation.md`.*

---

*Generated for VQMS v0.1.0 — Hexaware Technologies*
*Last updated: 2026-04-16*
