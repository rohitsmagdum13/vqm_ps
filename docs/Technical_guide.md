# VQMS — Technical Guide (Email to End of Pipeline)

A walk-through of every step a vendor email goes through, in plain English, with the actual file/class/entry, what each step does, the tools used, the strategy, the logic, and a real example.

---

## Big Picture (one paragraph)

A vendor sends an email. We fetch it, dedupe it, parse it, identify the vendor, filter out spam/auto-replies, store it, identify the thread, write everything to the database, and drop a message on a queue. A consumer picks that message up and runs it through an AI pipeline (8 nodes). The AI either answers it (Path A), sends a "we got it" reply and lets a human team investigate (Path B), or pauses for a human reviewer (Path C). Every outbound email passes 7 quality checks before it leaves.

---

## Tools and Services Used (one place)

| Tool / Service | What we use it for |
|---|---|
| **Microsoft Graph API** | Read shared mailbox, fetch emails, send replies |
| **MSAL** | Authenticate with Microsoft (OAuth2 client credentials) |
| **Amazon SQS** | Queue between intake and AI pipeline (with DLQ) |
| **Amazon S3** | Store raw email JSON + attachment binaries |
| **PostgreSQL (RDS)** | All metadata, idempotency, cache, vector search, audit |
| **pgvector** | Vector similarity search inside Postgres (no separate vector DB) |
| **Amazon Bedrock — Claude Sonnet 3.5** | LLM Calls #1 (analysis) and #2 (drafting) |
| **Amazon Bedrock — Titan Embed v2** | Turn text into 1536-d embedding vectors |
| **LangGraph** | State machine that wires the 8 AI pipeline nodes |
| **Salesforce CRM** | Look up the vendor record from the sender email |
| **ServiceNow ITSM** | Create the ticket (INC-XXXXXXX) |
| **Amazon EventBridge** | Audit/event log (20 event types) |
| **SSH tunnel (sshtunnel)** | Connect from app to RDS via bastion |
| **structlog** | JSON structured logs with correlation_id on every line |
| **pdfplumber / openpyxl / python-docx** | Extract text from PDF / Excel / Word attachments |

---

# 1. EMAIL INGESTION SERVICE

```
+======================================================================+
|                       EMAIL INGESTION SERVICE                          |
+======================================================================+
|                                                                        |
|  FILE:    src/services/email_intake/service.py                         |
|  CLASS:   EmailIntakeService                                           |
|  ENTRY:   await service.process_email(message_id, correlation_id)      |
|                                                                        |
|  HELPERS COMPOSED INSIDE THE SERVICE:                                  |
|    - EmailParser                  (parser.py)                          |
|    - VendorIdentifier             (vendor_identifier.py)               |
|    - EmailRelevanceFilter         (relevance_filter.py)                |
|    - AttachmentProcessor          (attachment_processor.py)            |
|    - ThreadCorrelator             (thread_correlator.py)               |
|    - EmailStorage                 (storage.py)                         |
|                                                                        |
|  EXTERNAL CONNECTORS USED:                                             |
|    - GraphAPIConnector            (read + send mail)                   |
|    - PostgresConnector            (idempotency, DB writes)             |
|    - S3Connector                  (raw email + attachment storage)     |
|    - SQSConnector                 (enqueue to AI pipeline)             |
|    - EventBridgeConnector         (publish EmailParsed event)          |
|    - SalesforceConnector          (vendor identification)              |
|    - BedrockConnector             (only for Layer 4 LLM relevance)     |
|                                                                        |
|  WHAT HAPPENS — ALL 10 STEPS                                           |
|     E2.1   Idempotency claim                                           |
|     E1     Fetch email from Graph API                                  |
|     E2.2   Parse email fields                                          |
|     E2.5   Vendor identification                                       |
|     E2.1b  Relevance filter (4 layers)                                 |
|     E2.7   Generate IDs (query_id, execution_id)                       |
|     E2.3   Store raw email in S3                                       |
|     E2.4   Process attachments                                         |
|     E2.6   Thread correlation                                          |
|     E2.8   Atomic DB write (4 tables in 1 transaction)                 |
|     E2.9a  Publish EmailParsed event                                   |
|     E2.9b  Publish to SQS (outbox pattern)                             |
+======================================================================+
```

### How to explain to your manager
"We do not process the same email twice. We claim it in the database, fetch it, decide if it is real, store it, write everything in one atomic transaction, and only then put a message on the queue. If anything breaks before commit, the claim is released and the next poll tries again — no email is ever silently dropped."

---

## STEP E2.1 — Idempotency claim

```
+=== STEP E2.1: IDEMPOTENCY CLAIM ===================================+
|                                                                    |
|  PURPOSE: Don't process the same email twice.                      |
|                                                                    |
|  PROBLEM: Both webhook AND 5-minute polling can detect the same    |
|           email. Without a guard, vendor would get two replies     |
|           and we would create two tickets.                         |
|                                                                    |
|  HOW IT WORKS (claim-check pattern):                               |
|    1. Take Microsoft's message_id (unique).                        |
|    2. INSERT into cache.idempotency_keys with status=PROCESSING    |
|       and a 10-minute TTL (so a crashed worker eventually frees    |
|       its claim).                                                  |
|    3. UNIQUE constraint on `key` makes the INSERT atomic.          |
|    4. INSERT succeeds  -> we own the work, continue.               |
|       INSERT conflicts -> someone else owns it OR it is done.      |
|                          A reclaim function looks at the row:      |
|                          if PROCESSING and older than 10 min,      |
|                          we steal it (the previous worker died).   |
|                          Otherwise we skip.                        |
|    5. On success at the end, status flips to COMPLETED (permanent  |
|       duplicate guard, 7-day cleanup job purges later).            |
|    6. On failure, release_idempotency_claim deletes the row so     |
|       the next poll cycle retries — no waiting for the TTL.        |
|                                                                    |
|  SQL (simplified):                                                 |
|    INSERT INTO cache.idempotency_keys                              |
|      (key, source, correlation_id, status, expires_at)             |
|    VALUES ($1, 'email', $2, 'PROCESSING', now() + interval '10 m') |
|    ON CONFLICT (key) DO NOTHING                                    |
|                                                                    |
|  WHY ON CONFLICT (not SELECT then INSERT):                         |
|    Two workers SELECTing at the same time both see "not found",    |
|    both INSERT, both process. ON CONFLICT is atomic - only one     |
|    wins. PostgreSQL gives us this for free.                        |
|                                                                    |
|  CODE: db/connection -> PostgresConnector.check_idempotency()      |
|        Returns: True (claimed) | False (duplicate or in-flight)    |
|                                                                    |
|  TOOLS:    PostgreSQL (table cache.idempotency_keys)               |
|  STRATEGY: Claim-check pattern with TTL reclaim + outer try/except |
|            that releases claim on any failure (no stuck rows).     |
|                                                                    |
|  CLASSIFICATION: CRITICAL                                          |
|  (failure here means message stays in SQS, which retries)          |
|                                                                    |
|  EXAMPLE:                                                          |
|    Webhook fires for "AAMkAGI2..." at 10:00:01 -> claim succeeds.  |
|    Poller sees same email at 10:05:00 -> claim conflicts, returns  |
|    False, polling skips it. Vendor never sees a double reply.      |
+====================================================================+
```

---

## STEP E1 — Fetch email from Graph API

```
+=== STEP E1: FETCH EMAIL =============================================+
|                                                                       |
|  PURPOSE: Get the actual email content from Microsoft.                |
|                                                                       |
|  WHAT WE GET BACK: A JSON document with sender, recipients, subject,  |
|    body (HTML + plain), conversation_id, internetMessageHeaders       |
|    (In-Reply-To, References, Message-ID), and inline attachments      |
|    (base64) up to ~3 MB.                                              |
|                                                                       |
|  HOW IT WORKS:                                                        |
|    1. MSAL gets an OAuth2 access token using client_credentials       |
|       (tenant_id + client_id + client_secret from .env).              |
|    2. We call:                                                        |
|         GET /users/{mailbox}/messages/{message_id}                    |
|              ?$expand=attachments                                     |
|    3. Token is cached in memory until ~5 minutes before expiry.       |
|    4. We retry on 429 (throttle) and 5xx with exponential backoff     |
|       via tenacity.                                                   |
|                                                                       |
|  CODE: adapters/graph_api/email_fetch.py ->                           |
|         EmailFetchMixin.fetch_email(message_id)                       |
|                                                                       |
|  TOOLS:    Microsoft Graph API, MSAL, httpx (async), tenacity         |
|  STRATEGY: OAuth2 client_credentials (no user login). Token cache.    |
|            Retry on transient errors only. Never retry on 4xx — a     |
|            404 means the email is gone, retrying won't bring it back. |
|                                                                       |
|  CLASSIFICATION: CRITICAL                                             |
|                                                                       |
|  EXAMPLE:                                                             |
|    message_id = "AAMkAGI2..."                                         |
|    -> raw_email = {                                                   |
|         "from": {"emailAddress":                                      |
|                    {"address":"rajesh@technova.com",                  |
|                     "name":"Rajesh Kumar"}},                          |
|         "subject": "Invoice #INV-9921 not paid",                      |
|         "body": {"content": "<p>Hi team, please check...</p>"},       |
|         "conversationId": "AAQkAGI2...",                              |
|         "internetMessageHeaders": [...]                               |
|       }                                                               |
+=======================================================================+
```

---

## STEP E2.2 — Parse email fields

```
+=== STEP E2.2: PARSE EMAIL FIELDS =====================================+
|                                                                       |
|  PURPOSE: Turn Microsoft's raw JSON into a clean dict our code uses.  |
|                                                                       |
|  WHAT WE EXTRACT:                                                     |
|    sender_email, sender_name                                          |
|    to_recipients, cc_recipients, bcc_recipients, reply_to             |
|    subject, body_html, body_text (HTML stripped)                      |
|    conversation_id, in_reply_to, references[], internet_message_id    |
|    importance, has_attachments, web_link                              |
|                                                                       |
|  HOW IT WORKS:                                                        |
|    1. Pull the structured fields from Graph's response shape.         |
|    2. Convert HTML body to plain text using BeautifulSoup:            |
|         - drop <script>, <style>, <head>, <title>, <meta>             |
|         - decode HTML entities (&amp; -> &)                           |
|         - collapse whitespace                                         |
|    3. Walk internetMessageHeaders to find In-Reply-To, References,    |
|       and Message-ID (these drive thread correlation later).          |
|                                                                       |
|  WHY STRIP <script> AND <style>:                                      |
|    Vendors sometimes paste signatures that include tracking pixels    |
|    or inline JS. We don't want that text leaking into the LLM         |
|    prompt. It also reduces token count, saving money.                 |
|                                                                       |
|  CODE: services/email_intake/parser.py ->                             |
|         EmailParser.parse_email_fields(raw_email)                     |
|                                                                       |
|  TOOLS:    BeautifulSoup (with regex fallback if not installed)       |
|  STRATEGY: Stateless static methods. Defensive defaults on every      |
|            field (missing subject -> ""), so a malformed email never  |
|            crashes the parser.                                        |
|                                                                       |
|  CLASSIFICATION: CRITICAL                                             |
|                                                                       |
|  EXAMPLE:                                                             |
|    body_html = "<p>Hi <b>team</b>, &nbsp;please pay INV-9921.</p>"    |
|    body_text = "Hi team,  please pay INV-9921."                       |
+=======================================================================+
```

---

## STEP E2.5 — Vendor identification

```
+=== STEP E2.5: VENDOR IDENTIFICATION ==================================+
|                                                                       |
|  PURPOSE: Match the sender to a known vendor in Salesforce so the     |
|           AI knows who is asking.                                     |
|                                                                       |
|  3-STEP FALLBACK CHAIN (cheap to expensive):                          |
|    1. EXACT EMAIL MATCH                                               |
|         SELECT Vendor_Account__c WHERE Contact.Email = sender_email   |
|       Hits ~80% of vendors.                                           |
|                                                                       |
|    2. BODY EXTRACTION                                                 |
|       Run regex on body_text to find a known                          |
|       vendor_id pattern (e.g., "VND-12345"). Match against            |
|       Salesforce. Catches vendors who write from a personal email     |
|       but quote their account number.                                 |
|                                                                       |
|    3. FUZZY NAME MATCH                                                |
|       Use sender_name against Vendor_Account__c.Name                  |
|       with similarity scoring. Only accepts if score > 0.85.          |
|                                                                       |
|  RETURN: (vendor_id, match_method)                                    |
|    match_method in {"exact_email", "body_extraction",                 |
|                     "fuzzy_name", "unresolved"}                       |
|                                                                       |
|  CODE: services/email_intake/vendor_identifier.py ->                  |
|         VendorIdentifier.identify_vendor()                            |
|         (delegates to adapters/salesforce/vendor_lookup.py)           |
|                                                                       |
|  TOOLS:    simple-salesforce (Salesforce REST), rapidfuzz             |
|  STRATEGY: Try the cheapest method first. Stop as soon as one         |
|            succeeds. Never crash — return (None, "unresolved") on     |
|            error. Unknown senders are still allowed past this step    |
|            because the relevance filter checks them in E2.1b.         |
|                                                                       |
|  CLASSIFICATION: NON-CRITICAL                                         |
|  (vendor_id can be None — pipeline still runs)                        |
|                                                                       |
|  EXAMPLE:                                                             |
|    sender = "rajesh@technova.com"                                     |
|    -> Salesforce: Contact match found, account = "TechNova Pvt Ltd"   |
|    -> vendor_id = "VND-1042", match_method = "exact_email"            |
+=======================================================================+
```

---

## STEP E2.1b — Relevance filter (drop noise before Bedrock)

```
+=== STEP E2.1b: RELEVANCE FILTER (4 LAYERS) ==========================+
|                                                                       |
|  PURPOSE: Drop hello-only emails, auto-replies, newsletters, and      |
|           unknown senders BEFORE we waste tokens on Claude.           |
|                                                                       |
|  LAYER 1 (already done before E1):                                    |
|    Graph API $filter on the fetch query — drops "out of office",     |
|    "delivery failure" subjects at the API call.                       |
|                                                                       |
|  LAYER 2 — SENDER ALLOWLIST                                           |
|    If vendor was identified -> pass.                                  |
|    Else if sender domain in ops-managed allowlist -> pass.            |
|    Else -> reject with action="auto_reply_ask_details".               |
|                                                                       |
|  LAYER 3 — DETERMINISTIC CONTENT SANITY                               |
|    Reject if any of these is true:                                    |
|      - Auto-Submitted header set, or X-Auto-Response-Suppress,        |
|        or List-Unsubscribe, or List-ID, or Precedence: bulk           |
|      - Subject starts with "Automatic reply", "Auto:",                |
|        "Out of office", "Undeliverable", etc.                         |
|      - Body matches noise regex (just "hi", "thanks", "test")         |
|      - Combined subject+body length below threshold                   |
|                                                                       |
|  LAYER 4 — OPTIONAL LLM CLASSIFIER (Claude Haiku, temp 0)             |
|    Only runs when:                                                    |
|      email_filter_use_llm_classifier is true AND                      |
|      content is borderline (passed Layers 2-3 but still suspicious).  |
|    Returns {"is_query": true|false, "reason": "..."}                  |
|    Cost: < 1¢ per call.                                               |
|                                                                       |
|  ACTIONS WHEN REJECTED:                                               |
|    "drop"                  - silently drop                            |
|    "auto_reply_ask_details"- reply asking for details                 |
|    "thread_only"           - keep in DB but don't enqueue             |
|                                                                       |
|  CODE: services/email_intake/relevance_filter.py ->                   |
|         EmailRelevanceFilter.evaluate()                               |
|                                                                       |
|  TOOLS:    BedrockConnector (Haiku), regex, header inspection         |
|  STRATEGY: Tiered filter — cheapest checks first. LLM only for        |
|            borderline cases. Saves >95% of bogus Bedrock calls.       |
|                                                                       |
|  CLASSIFICATION: CRITICAL (decision must be made before SQS)          |
|                                                                       |
|  EXAMPLE:                                                             |
|    Subject: "Out of Office: Re: Invoice"                              |
|    -> Layer 3 rejects on subject prefix.                              |
|    -> action="drop"; idempotency claim is marked COMPLETED so we      |
|       never re-evaluate; mailbox marked read.                         |
+=======================================================================+
```

---

## STEP E2.7 — Generate IDs

```
+=== STEP E2.7: GENERATE IDS ==========================================+
|                                                                       |
|  PURPOSE: Stamp the query with stable IDs that flow through the       |
|           whole pipeline and audit trail.                             |
|                                                                       |
|  IDS GENERATED:                                                       |
|    query_id      = "VQ-2026-0042"   <- year + sequence (human-friendly)|
|    execution_id  = UUID v4          <- one per pipeline run           |
|    correlation_id= UUID v4          <- one per request, set at intake |
|    received_at   = IST timestamp                                      |
|                                                                       |
|  WHY 3 IDS:                                                           |
|    - query_id is what vendors and humans see (in the email subject).  |
|    - execution_id is one per pipeline run (a retry creates a new one).|
|    - correlation_id binds ALL log lines for one request together so   |
|      you can grep "correlation_id=abc-123" across services.           |
|                                                                       |
|  CODE: utils/helpers.py ->                                            |
|         IdGenerator.generate_query_id() / .generate_execution_id()    |
|         IdGenerator.generate_correlation_id()                         |
|         TimeHelper.ist_now()                                          |
|                                                                       |
|  TOOLS:    uuid (stdlib), zoneinfo for IST                            |
|  STRATEGY: query_id is sequenced via a small DB sequence so it stays  |
|            human-readable. correlation_id is bound to structlog       |
|            contextvars at the very top of process_email() so EVERY    |
|            log line downstream gets it for free.                      |
|                                                                       |
|  CLASSIFICATION: CRITICAL                                             |
|                                                                       |
|  EXAMPLE:                                                             |
|    query_id     = "VQ-2026-0042"                                      |
|    execution_id = "8b3a-..."                                          |
|    correlation_id = "f9c7-..."                                        |
|    received_at = "2026-04-26T10:00:01+05:30"                          |
+=======================================================================+
```

---

## STEP E2.3 — Store raw email in S3

```
+=== STEP E2.3: STORE RAW EMAIL IN S3 ================================+
|                                                                      |
|  PURPOSE: Keep a permanent original copy for audit / replay /        |
|           future re-processing if the pipeline changes.              |
|                                                                      |
|  WHERE: s3://vqms-data-store/inbound-emails/VQ-2026-0042/raw_email.json |
|                                                                      |
|  HOW IT WORKS:                                                       |
|    1. Serialize raw_email dict with orjson (fast).                   |
|    2. Build S3 key via config/s3_paths.py -> build_s3_key().         |
|       Centralized helper -> no hardcoded S3 paths anywhere.          |
|    3. Upload with Content-Type=application/json.                     |
|                                                                      |
|  WHY orjson:                                                         |
|    Standard json is slow and can't handle bytes/datetimes well.      |
|    orjson is ~5x faster and has sane defaults.                       |
|                                                                      |
|  CODE: services/email_intake/storage.py ->                           |
|         EmailStorage.store_raw_email()                               |
|                                                                      |
|  TOOLS:    boto3 (aioboto3 wrapper), orjson                          |
|  STRATEGY: Single bucket, prefix-organized by VQ-ID. Failure here    |
|            is logged as a warning - we keep going (the parsed data   |
|            is still in PostgreSQL). The raw archive is "nice to      |
|            have", not "must have" for processing.                    |
|                                                                      |
|  CLASSIFICATION: NON-CRITICAL                                        |
|                                                                      |
|  EXAMPLE:                                                            |
|    Returns: "inbound-emails/VQ-2026-0042/raw_email.json"             |
+======================================================================+
```

---

## STEP E2.4 — Process attachments

```
+=== STEP E2.4: PROCESS ATTACHMENTS ====================================+
|                                                                       |
|  PURPOSE: Pull text out of PDFs/Excel/Word/CSV/images so the AI       |
|           can read what is in the invoice, PO, or screenshot.        |
|                                                                       |
|  PIPELINE PER ATTACHMENT:                                            |
|    1. SAFETY CHECKS                                                  |
|         - Block .exe .bat .cmd .ps1 .sh .js extensions (security)    |
|         - Reject any single file > 10 MB                             |
|         - Stop accumulating once total size > 50 MB                  |
|         - Cap at 10 attachments per email                            |
|                                                                       |
|    2. RESOLVE BYTES                                                   |
|         - If contentBytes is inline (Base64) -> decode               |
|         - Else (file > 3 MB) -> GET                                  |
|             /messages/{id}/attachments/{att_id}/$value               |
|           (Graph's separate large-attachment endpoint)               |
|                                                                       |
|    3. STORE BINARY TO S3                                             |
|         attachments/VQ-2026-0042/{att_id}_{filename}                 |
|                                                                       |
|    4. EXTRACT TEXT (run in a thread, don't block the event loop)     |
|         .pdf  -> pdfplumber                                          |
|         .xlsx -> openpyxl (read_only=True, data_only=True)           |
|         .docx -> python-docx                                         |
|         .csv .txt -> direct utf-8 decode                             |
|         (else)    -> skip extraction                                 |
|                                                                       |
|    5. TRUNCATE extracted text to 5,000 chars (~1,250 tokens) so      |
|       the LLM prompt stays under the budget.                         |
|                                                                       |
|    6. STORE _manifest.json under attachments/VQ-.../_manifest.json   |
|                                                                       |
|  CODE: services/email_intake/attachment_processor.py ->              |
|         AttachmentProcessor.process_attachments()                    |
|                                                                       |
|  TOOLS:    boto3 (S3), pdfplumber, openpyxl, python-docx,            |
|            asyncio.to_thread (CPU-bound work off the event loop)    |
|  STRATEGY: Block executables outright (security), cap sizes (memory),|
|            extract per-type (the right library for each file),      |
|            truncate aggressively (token budget). One bad file does  |
|            not poison the rest — each is wrapped in try/except.     |
|                                                                       |
|  CLASSIFICATION: NON-CRITICAL                                        |
|                                                                       |
|  EXAMPLE:                                                            |
|    invoice.pdf (1.2 MB)                                              |
|    -> pdfplumber extracts:                                           |
|       "Invoice INV-9921, due 2026-04-15, amount 45,000 INR..."       |
|    -> stored at attachments/VQ-2026-0042/ATT-001_invoice.pdf         |
|    -> extracted_text saved on intake.email_attachments row           |
+=======================================================================+
```

---

## STEP E2.6 — Thread correlation

```
+=== STEP E2.6: THREAD CORRELATION ====================================+
|                                                                       |
|  PURPOSE: Decide if this email is a brand-new query or a reply on    |
|           an existing case (so we don't open a duplicate ticket).    |
|                                                                       |
|  THREE OUTCOMES:                                                     |
|    NEW             -> first email in this conversation               |
|    EXISTING_OPEN   -> reply on a case still in progress              |
|    REPLY_TO_CLOSED -> reply on a case already CLOSED/RESOLVED        |
|                                                                       |
|  HOW IT WORKS:                                                       |
|    1. Use raw_email.conversationId (Microsoft's stable thread ID).   |
|    2. Run a single SQL JOIN:                                         |
|         SELECT ce.query_id, ce.status                                |
|         FROM workflow.case_execution ce                              |
|         JOIN intake.email_messages em ON em.query_id = ce.query_id   |
|         WHERE em.conversation_id = $1                                |
|         ORDER BY ce.created_at DESC LIMIT 1                          |
|    3. No row -> NEW                                                  |
|       Status in (CLOSED, RESOLVED) -> REPLY_TO_CLOSED                |
|       Else -> EXISTING_OPEN                                          |
|                                                                       |
|  WHY conversationId AND NOT In-Reply-To:                             |
|    Outlook splits long threads sometimes, breaking References. But   |
|    conversationId is sticky across the whole thread on Microsoft's   |
|    side. We keep In-Reply-To around as a backup signal.              |
|                                                                       |
|  WHAT HAPPENS DOWNSTREAM:                                            |
|    EXISTING_OPEN  -> ClosureService checks for "thanks" / "resolved" |
|                      keywords -> may close the prior case            |
|    REPLY_TO_CLOSED -> ClosureService runs reopen logic               |
|                                                                       |
|  CODE: services/email_intake/thread_correlator.py ->                 |
|         ThreadCorrelator.determine_thread_status()                   |
|                                                                       |
|  TOOLS:    PostgreSQL (asyncpg)                                      |
|  STRATEGY: Trust Microsoft's conversationId. Single JOIN, indexed    |
|            on intake.email_messages.conversation_id. On any DB       |
|            error, default to NEW (worst case is a duplicate ticket   |
|            which a human can merge — vs blocking the pipeline).      |
|                                                                       |
|  CLASSIFICATION: NON-CRITICAL                                        |
|                                                                       |
|  EXAMPLE:                                                            |
|    Vendor replied to "Re: VQ-2026-0042 - Invoice received".          |
|    conversationId already exists; latest case is status="DRAFTING".  |
|    -> thread_status = "EXISTING_OPEN"                                |
+=======================================================================+
```

---

## STEP E2.8 — Atomic DB write (the most important step)

```
+=== STEP E2.8: ATOMIC DB WRITE =======================================+
|                                                                       |
|  PURPOSE: Write 4 things in ONE transaction so we never end up with  |
|           half-saved state if SQS or Postgres blips.                 |
|                                                                       |
|  4 INSERTS IN ONE TRANSACTION:                                       |
|    1. intake.email_messages    - all parsed fields                   |
|    2. intake.email_attachments - one row per attachment              |
|    3. workflow.case_execution  - case state row, status='RECEIVED'   |
|    4. cache.outbox_events      - the SQS payload, staged             |
|                                                                       |
|  THE OUTBOX PATTERN (KEY IDEA):                                      |
|    Old way:   write DB  -> send SQS                                  |
|       Risk:   DB succeeds, SQS down -> message lost forever.        |
|    New way:   write DB + outbox row in ONE transaction               |
|               -> commit                                              |
|               -> try to publish to SQS                               |
|                  - success: mark outbox row sent                     |
|                  - failure: leave it; drainer will re-publish        |
|       Result: either everything is durable, or nothing is.           |
|                                                                       |
|  WHY ONE TRANSACTION:                                                |
|    If attachment INSERT fails halfway, the email_messages row,       |
|    case_execution row, and outbox row all roll back together.        |
|    The next retry starts from a clean slate.                         |
|                                                                       |
|  CODE: services/email_intake/storage.py ->                           |
|         EmailStorage.persist_email_atomically()                      |
|                                                                       |
|  TOOLS:    PostgreSQL (asyncpg.transaction()), orjson for JSONB      |
|  STRATEGY: Transactional outbox - the textbook pattern for           |
|            "I need to write to DB AND publish a message" without     |
|            distributed transactions. This is the single most         |
|            important reliability decision in the ingestion service. |
|                                                                       |
|  CLASSIFICATION: CRITICAL                                            |
|                                                                       |
|  EXAMPLE:                                                            |
|    BEGIN;                                                            |
|      INSERT INTO intake.email_messages (...) VALUES (...);           |
|      INSERT INTO intake.email_attachments (...) VALUES (...);   x N  |
|      INSERT INTO workflow.case_execution (...) VALUES (...);         |
|      INSERT INTO cache.outbox_events (event_key, queue_url,          |
|                                      payload) VALUES (...);          |
|    COMMIT;                                                           |
+=======================================================================+
```

---

## STEP E2.9a — Publish EmailParsed event

```
+=== STEP E2.9a: PUBLISH EmailParsed EVENT ===========================+
|                                                                      |
|  PURPOSE: Tell other systems (audit, dashboards, Phase 6 SLA timer)  |
|           that an email is now in the system.                       |
|                                                                      |
|  EVENT BUS: vqms-event-bus (EventBridge)                            |
|  EVENT NAME: EmailParsed                                             |
|  PAYLOAD: { query_id, message_id, sender_email, vendor_id }          |
|                                                                      |
|  CODE: events/eventbridge.py ->                                      |
|         EventBridgeConnector.publish_event(...)                      |
|                                                                      |
|  TOOLS:    boto3 (events client)                                     |
|  STRATEGY: Fire-and-forget. We log a warning if it fails but never   |
|            block the pipeline — the audit trail is rebuildable from  |
|            postgres anyway.                                          |
|                                                                      |
|  CLASSIFICATION: NON-CRITICAL                                        |
+======================================================================+
```

---

## STEP E2.9b — Publish to SQS (immediate + drainer fallback)

```
+=== STEP E2.9b: PUBLISH TO SQS =======================================+
|                                                                       |
|  PURPOSE: Hand the email off to the AI pipeline.                     |
|                                                                       |
|  HOW IT WORKS (outbox publisher):                                    |
|    1. The payload is already in cache.outbox_events (committed).     |
|    2. Try sqs.send_message() right away (the happy path).           |
|    3. On success -> UPDATE outbox row SET sent_at=now().            |
|    4. On failure -> log warning, store error on outbox row.         |
|       A background drainer scans for sent_at IS NULL every minute    |
|       and re-publishes them. Our work is done.                       |
|                                                                       |
|  WHY DUPLICATES ARE SAFE:                                            |
|    The downstream AI pipeline keys idempotency on query_id. Even if |
|    drainer re-sends after a flaky network, the consumer sees the    |
|    same query_id and skips the duplicate work.                      |
|                                                                       |
|  AFTER SUCCESS:                                                      |
|    - Mark idempotency_keys row COMPLETED (permanent guard).         |
|    - Mark Outlook mail as read (so poller skips it next cycle).      |
|                                                                       |
|  PAYLOAD (UnifiedQueryPayload):                                      |
|    { query_id, correlation_id, execution_id,                         |
|      source: "email", vendor_id,                                     |
|      subject, body, priority: "MEDIUM",                              |
|      received_at, attachments[], thread_status,                      |
|      metadata: {message_id, sender_email, sender_name,               |
|                 vendor_match_method, conversation_id} }              |
|                                                                       |
|  CODE: services/email_intake/service.py ->                           |
|         EmailIntakeService._publish_from_outbox()                    |
|                                                                       |
|  TOOLS:    boto3 (sqs client), background outbox drainer task        |
|  STRATEGY: Outbox + drainer = at-least-once delivery with no extra   |
|            infrastructure. Idempotent consumer downstream makes the  |
|            duplicates safe.                                          |
|                                                                       |
|  CLASSIFICATION: Non-blocking (outbox already committed)             |
+=======================================================================+
```

---

# 2. AI PIPELINE — LANGGRAPH ORCHESTRATOR

```
+======================================================================+
|                          AI PIPELINE                                  |
+======================================================================+
|                                                                       |
|  FILE:    src/orchestration/graph.py                                  |
|  ENTRY:   build_pipeline_graph(...).invoke(initial_state)             |
|  CONSUMER:src/orchestration/sqs_consumer.py -> PipelineConsumer       |
|                                                                       |
|  STATE:   models/workflow.py -> PipelineState (TypedDict)             |
|  STORES:  unified_payload, vendor_context, analysis_result,           |
|           routing_decision, kb_search_result, draft_response,         |
|           quality_gate_result, ticket_info, processing_path,          |
|           status, correlation_id, query_id                            |
|                                                                       |
|  GRAPH SHAPE:                                                         |
|    START -> entry switch                                              |
|       (resume?) -> resolution_from_notes -> quality_gate -> delivery  |
|       (else)    -> context_loading -> query_analysis                  |
|                    -> confidence_check                                |
|                       (C) -> triage -> END                            |
|                       (else) -> routing -> kb_search -> path_decision |
|                                  (A) -> resolution                    |
|                                  (B) -> acknowledgment                |
|                                  -> quality_gate -> delivery -> END   |
+======================================================================+
```

---

## STEP 7 — Context Loading

```
+=== STEP 7: CONTEXT LOADING ==========================================+
|                                                                       |
|  FILE:    src/orchestration/nodes/context_loading.py                 |
|  CLASS:   ContextLoadingNode                                          |
|  ENTRY:   await node.execute(state)                                   |
|                                                                       |
|  PURPOSE: Tell Claude WHO is asking. Without this, every vendor      |
|           looks the same and tier-based SLAs / past history are     |
|           ignored.                                                   |
|                                                                       |
|  WHAT WE LOAD:                                                       |
|    1. Vendor profile (name, tier, primary_contact_email,            |
|       account_manager)                                               |
|         - First check cache.vendor_cache (1-hour TTL)               |
|         - On cache miss, hit Salesforce, then write to cache         |
|         - On both fail, return default BRONZE profile so the         |
|           pipeline never crashes                                     |
|    2. Last 5 interactions from memory.episodic_memory                |
|         - Gives Claude the vendor's history at a glance              |
|    3. Set status = "ANALYZING"                                       |
|                                                                       |
|  TOOLS:    PostgresConnector (cache + memory), SalesforceConnector  |
|  STRATEGY: Cache-aside pattern. Cache hit is ~5ms; Salesforce hit   |
|            is ~500ms. Default profile guarantees the pipeline       |
|            never blocks on a vendor lookup failure.                 |
|                                                                       |
|  EXAMPLE:                                                            |
|    vendor_id = "VND-1042"                                            |
|    -> vendor_profile = {                                             |
|         name: "TechNova Pvt Ltd",                                    |
|         tier: SILVER (16h SLA),                                      |
|         primary_contact_email: "rajesh@technova.com"                 |
|       }                                                              |
|    -> recent_interactions = [VQ-2026-0033 (resolved), VQ-2025-0901..]|
+=======================================================================+
```

---

## STEP 8 — Query Analysis (LLM Call #1) — 8-LAYER DEFENSE

```
+=== STEP 8: QUERY ANALYSIS (LLM CALL #1) =============================+
|                                                                       |
|  FILE:    src/orchestration/nodes/query_analysis.py                  |
|  CLASS:   QueryAnalysisNode                                           |
|  ENTRY:   await node.execute(state)                                   |
|                                                                       |
|  PURPOSE: Read the vendor's question and produce a structured        |
|           AnalysisResult: intent, entities, urgency, sentiment,      |
|           confidence_score (0..1).                                   |
|                                                                       |
|  THIS IS THE MOST DEFENSIVE NODE IN THE SYSTEM. 8 LAYERS:           |
|                                                                       |
|  LAYER 1 - INPUT VALIDATION                                          |
|    Empty body AND empty subject -> safe fallback (route to Path C). |
|    Truncate body > 10,000 chars and attachment text > 5,000 chars.  |
|                                                                       |
|  LAYER 2 - PROMPT ENGINEERING                                        |
|    Render Jinja2 template (query_analysis_v1.j2) with vendor name,  |
|    tier, query, attachments, recent_interactions, source.           |
|    Prompt explicitly demands JSON-only output with named fields.    |
|                                                                       |
|  LAYER 3 - LLM CALL (with retry inside connector)                    |
|    bedrock.llm_complete(prompt, system_prompt, temperature=0.1)     |
|    Connector retries on Throttling/ServiceUnavailable.              |
|    Failure here -> safe fallback.                                   |
|                                                                       |
|  LAYER 4 - OUTPUT PARSING (3 strategies in order)                    |
|    a) json.loads(text)                                              |
|    b) extract from ```json ... ``` markdown fence                   |
|    c) extract first { ... } block via regex                         |
|    All fail -> Layer 6 self-correct.                                |
|                                                                       |
|  LAYER 5 - PYDANTIC VALIDATION                                       |
|    AnalysisResult model enforces:                                   |
|      - urgency_level in {LOW,MEDIUM,HIGH,CRITICAL}                  |
|      - sentiment in {POSITIVE,NEUTRAL,NEGATIVE,FRUSTRATED}          |
|      - confidence_score in [0.0, 1.0]                               |
|    Validation error -> Layer 6 self-correct.                        |
|                                                                       |
|  LAYER 6 - SELF-CORRECTION                                           |
|    Send raw response + error back to Claude with                    |
|    "Fix this and return ONLY valid JSON". One retry.                |
|                                                                       |
|  LAYER 7 - SAFE FALLBACK                                             |
|    All else fails -> AnalysisResult(intent="UNKNOWN",               |
|                                     confidence_score=0.3, ...).     |
|    Confidence 0.3 < threshold 0.85 -> auto-routes to Path C.        |
|                                                                       |
|  LAYER 8 - AUDIT LOGGING                                             |
|    Log layer name, tokens_in/out, model_id, duration_ms, raw        |
|    response. Feeds the LLM audit trail.                             |
|                                                                       |
|  TOOLS:    BedrockConnector (Claude Sonnet 3.5, temp 0.1),          |
|            PromptManager (Jinja2 template loader)                   |
|  STRATEGY: NEVER let the pipeline crash. The 8 layers turn every    |
|            possible failure mode into "low confidence" and route   |
|            to a human reviewer. Defensive on purpose.               |
|                                                                       |
|  EXAMPLE OUTPUT:                                                     |
|    AnalysisResult(                                                  |
|      intent_classification = "INVOICE_PAYMENT_DELAY",               |
|      extracted_entities = {                                         |
|        "invoice_number": "INV-9921",                                |
|        "amount": "45000",                                           |
|        "due_date": "2026-04-15"                                     |
|      },                                                             |
|      urgency_level = "HIGH",                                        |
|      sentiment = "FRUSTRATED",                                      |
|      confidence_score = 0.92,                                       |
|      multi_issue_detected = False,                                  |
|      suggested_category = "INVOICE_PAYMENT"                         |
|    )                                                                |
+=======================================================================+
```

---

## DECISION POINT 1 — Confidence Check

```
+=== DECISION 1: CONFIDENCE CHECK =====================================+
|                                                                       |
|  FILE:    src/orchestration/nodes/confidence_check.py                |
|  CLASS:   ConfidenceCheckNode                                         |
|                                                                       |
|  RULE:                                                                |
|    confidence >= 0.85 -> continue to routing                         |
|    confidence <  0.85 -> processing_path = "C", status = "PAUSED"    |
|                                                                       |
|  WHY 0.85:                                                            |
|    Empirically chosen as the level where Claude is "almost           |
|    certainly right". Below this, sending an automated reply has a    |
|    real chance of embarrassing us. The threshold is configurable     |
|    in .env via AGENT_CONFIDENCE_THRESHOLD - never hardcoded.         |
|                                                                       |
|  EXAMPLE:                                                             |
|    confidence_score = 0.92 -> continue                                |
|    confidence_score = 0.62 -> route to Path C (human triage)         |
+=======================================================================+
```

---

## STEP 9A — Routing (deterministic rules — no LLM)

```
+=== STEP 9A: ROUTING ================================================+
|                                                                      |
|  FILE:    src/orchestration/nodes/routing.py                        |
|  CLASS:   RoutingNode                                                |
|                                                                      |
|  PURPOSE: Decide which team should handle this and what the SLA is. |
|                                                                      |
|  THE RULES (no AI - pure business logic):                           |
|                                                                      |
|  TEAM = QUERY_TYPE_TEAM_MAP[suggested_category.upper()]              |
|         or CATEGORY_TEAM_MAP[suggested_category.lower()]             |
|         or "general-support"                                         |
|                                                                      |
|    INVOICE/PAYMENT  -> finance-ops                                  |
|    SHIPPING/DELIVERY-> supply-chain                                 |
|    CONTRACT/LEGAL   -> legal-compliance                             |
|    API/INTEGRATION  -> tech-support                                 |
|    PRICING/CATALOG  -> procurement                                  |
|    QUALITY/DEFECT   -> quality-assurance                            |
|    (else)           -> general-support                              |
|                                                                      |
|  SLA_HOURS = TIER_SLA_HOURS[vendor_tier] * URGENCY_MULTIPLIER       |
|                                                                      |
|    PLATINUM  4h    *  CRITICAL 0.25  ->   1h                        |
|    GOLD      8h    *  HIGH     0.5   ->   4h                        |
|    SILVER   16h    *  MEDIUM   1.0   ->  16h                        |
|    BRONZE   24h    *  LOW      1.5   ->  36h                        |
|                                                                      |
|  ALSO INSERTS A ROW into workflow.sla_checkpoints so the SLA        |
|  monitor can fire the 70/85/95% warnings later.                     |
|                                                                      |
|  TOOLS:    PostgresConnector (sla_checkpoints insert)               |
|  STRATEGY: Deterministic. Easy to audit. No prompt drift. No LLM    |
|            cost. Configurable via .env.                             |
|                                                                      |
|  EXAMPLE:                                                            |
|    SILVER + HIGH + INVOICE_PAYMENT                                   |
|    -> assigned_team = "finance-ops"                                 |
|    -> SLA = 16 * 0.5 = 8 hours                                      |
|    -> warning at 70% (5.6h), L1 escalation at 85% (6.8h),           |
|       L2 escalation at 95% (7.6h)                                   |
+======================================================================+
```

---

## STEP 9B — KB Search (vector similarity)

```
+=== STEP 9B: KB SEARCH ==============================================+
|                                                                      |
|  FILE:    src/orchestration/nodes/kb_search.py                      |
|  CLASS:   KBSearchNode                                               |
|                                                                      |
|  PURPOSE: Find KB articles that answer this question - so we can    |
|           decide Path A (we have the answer) vs Path B (we don't).  |
|                                                                      |
|  HOW IT WORKS (3 sub-steps):                                        |
|                                                                      |
|  9B.1  BUILD SEARCH TEXT                                            |
|        text = subject + " " + body  (truncated to 2000 chars)       |
|                                                                      |
|  9B.2  EMBED VIA TITAN EMBED V2                                     |
|        bedrock.llm_embed(text)                                      |
|        -> vector(1536)  (a list of 1536 floats)                     |
|        Cost: tiny, ~$0.0001 per call.                               |
|                                                                      |
|  9B.3  COSINE SIMILARITY SEARCH IN POSTGRES                         |
|        SELECT article_id, title, content_text, category,            |
|               1 - (embedding <=> $1::vector) AS similarity_score    |
|        FROM memory.embedding_index                                  |
|        ORDER BY embedding <=> $1::vector                            |
|        LIMIT 5                                                       |
|                                                                      |
|        <=> is the pgvector cosine-distance operator. Smaller = closer.|
|        We convert distance to a 0..1 similarity for clarity.        |
|                                                                      |
|  RESULT:                                                             |
|    KBSearchResult(                                                   |
|      matches = [KBArticleMatch, ...],                               |
|      best_match_score = 0.91,                                       |
|      has_sufficient_match = best >= 0.80                            |
|    )                                                                |
|                                                                      |
|  WHY pgvector AND NOT A SEPARATE VECTOR DB:                          |
|    One database to operate. Joins and filters are trivial. We        |
|    never have a sync problem because there is nothing to sync.      |
|                                                                      |
|  TOOLS:    BedrockConnector (Titan Embed v2), pgvector extension,   |
|            HNSW index for sub-50ms queries                          |
|  STRATEGY: Single embedding model for KB and queries. Cosine         |
|            similarity (industry standard for text). Cap top-K at 5  |
|            so the resolution prompt doesn't blow the token budget.  |
|                                                                      |
|  EXAMPLE:                                                            |
|    Query: "Invoice INV-9921 not paid"                                |
|    -> embedding [0.0123, -0.0456, ...] (1536 floats)                |
|    -> top match: "Late Payment Procedure" similarity 0.91            |
|       2nd:       "Invoice Status Lookup"   similarity 0.88           |
|       3rd:       "Vendor Payment Terms"    similarity 0.84           |
|    -> has_sufficient_match = True                                    |
+======================================================================+
```

---

## DECISION POINT 2 — Path A vs Path B

```
+=== DECISION 2: PATH A vs PATH B ====================================+
|                                                                      |
|  FILE:    src/orchestration/nodes/path_decision.py                  |
|  CLASS:   PathDecisionNode                                           |
|                                                                      |
|  RULE:                                                                |
|    has_sufficient_match (best >= 0.80)                              |
|      AND content_length(top_match) >= 100 chars                     |
|         -> processing_path = "A"  (AI drafts the answer)            |
|    Otherwise                                                         |
|         -> processing_path = "B"  (human team investigates;         |
|            also flips routing_decision.requires_human_investigation |
|            = True so the team's queue gets the case)                |
|                                                                      |
|  WHY THE 100-CHAR FLOOR:                                             |
|    A high similarity score on a 20-character snippet usually means  |
|    the article is just a title or stub - no real facts to ground a  |
|    response on. Demanding 100+ chars cuts down on confident-but-    |
|    empty drafts.                                                     |
|                                                                      |
|  EXAMPLE:                                                            |
|    best_score = 0.91, content = 1,243 chars -> Path A               |
|    best_score = 0.65 -> Path B                                       |
|    best_score = 0.92, content = 35 chars   -> Path B (too thin)     |
+======================================================================+
```

---

## STEP 10A — Resolution (Path A, LLM Call #2)

```
+=== STEP 10A: RESOLUTION (PATH A) ===================================+
|                                                                      |
|  FILE:    src/orchestration/nodes/resolution.py                     |
|  CLASS:   ResolutionNode                                             |
|                                                                      |
|  PURPOSE: Draft the actual reply with the answer, using KB          |
|           articles as the source of facts.                          |
|                                                                      |
|  HOW IT WORKS:                                                       |
|    1. Render resolution_v1.j2 with:                                 |
|         vendor_name, vendor_tier, original_query, intent,            |
|         entities, kb_articles[], ticket_number="PENDING",            |
|         sla_statement (tier-specific)                                |
|    2. Call Claude Sonnet 3.5 with temperature=0.3 (slightly         |
|       creative for natural-sounding email language).                |
|    3. Parse JSON output (subject, body_html, confidence, sources). |
|    4. Build DraftResponse(draft_type="RESOLUTION", ...).            |
|                                                                      |
|  WHY "PENDING" PLACEHOLDER FOR TICKET:                              |
|    We don't have the ServiceNow INC number yet (delivery node       |
|    creates it). The Quality Gate accepts "PENDING" or a real INC   |
|    number; delivery node string-replaces "PENDING" with the actual |
|    number after ticket creation.                                     |
|                                                                      |
|  TOOLS:    LLMGateway (Bedrock primary, OpenAI fallback),           |
|            PromptManager                                             |
|  STRATEGY: Force the model to cite sources (article_ids) in the    |
|            sources[] array - the Quality Gate rejects Path A       |
|            drafts with no citations.                                 |
|                                                                      |
|  EXAMPLE OUTPUT:                                                     |
|    DraftResponse(                                                   |
|      draft_type = "RESOLUTION",                                     |
|      subject = "Re: Invoice INV-9921 - Payment status [PENDING]",  |
|      body = "Dear Rajesh, Thank you for reaching out about         |
|              invoice INV-9921 for INR 45,000 due 2026-04-15...     |
|              Per our late-payment procedure (KB-LP-014), the       |
|              payment is being processed and you should receive...  |
|              Your reference is PENDING.... Best regards,            |
|              Vendor Support",                                       |
|      confidence = 0.88,                                             |
|      sources = ["KB-LP-014", "KB-IP-023"]                           |
|    )                                                                |
+======================================================================+
```

---

## STEP 10B — Acknowledgment (Path B, LLM Call #2)

```
+=== STEP 10B: ACKNOWLEDGMENT (PATH B) ===============================+
|                                                                      |
|  FILE:    src/orchestration/nodes/acknowledgment.py                 |
|  CLASS:   AcknowledgmentNode                                         |
|                                                                      |
|  PURPOSE: Draft a "we got it, ticket is X, team is reviewing" email |
|           - WITHOUT trying to answer the question (because the KB    |
|           does not have specific facts).                             |
|                                                                      |
|  CRITICAL DIFFERENCE FROM RESOLUTION:                                |
|    The system prompt says: "Do NOT answer the query".               |
|    The acknowledgment template ONLY references the ticket number,   |
|    SLA statement, and assigned_team. It NEVER pretends to have an   |
|    answer.                                                            |
|                                                                      |
|  WHY THIS MATTERS:                                                    |
|    A confident-sounding generic email ("we are reviewing your        |
|    refund request") is worse than no email if the KB lacked the     |
|    facts to make a real promise. Path B is honest: we say "the      |
|    finance team is investigating, expect a reply within 8 hours".  |
|                                                                      |
|  TOOLS:    LLMGateway, PromptManager                                |
|  STRATEGY: Strict separation of concerns - acknowledgment is        |
|            tone + ticket + SLA only. No claim about the answer.     |
|                                                                      |
|  EXAMPLE OUTPUT:                                                     |
|    DraftResponse(                                                   |
|      draft_type = "ACKNOWLEDGMENT",                                 |
|      subject = "Re: Refund request - Ticket PENDING",              |
|      body = "Dear Rajesh, Thank you for your message about the     |
|              refund. We have logged your request as ticket          |
|              PENDING. Our finance-ops team is reviewing your case   |
|              and will respond within 8 hours. Best regards...",     |
|      confidence = 0.95,                                             |
|      sources = []  <- always empty for Path B                       |
|    )                                                                |
+======================================================================+
```

---

## STEP 11 — Quality Gate (7 deterministic checks)

```
+=== STEP 11: QUALITY GATE ===========================================+
|                                                                      |
|  FILE:    src/orchestration/nodes/quality_gate.py                   |
|  CLASS:   QualityGateNode                                            |
|                                                                      |
|  PURPOSE: No email leaves the building unless it passes all 7      |
|           checks. This is our "professionalism guardrail".           |
|                                                                      |
|  CHECK 1 - TICKET NUMBER                                             |
|    "PENDING" placeholder OR real INC-?\d{7,} present in body.       |
|                                                                      |
|  CHECK 2 - SLA WORDING                                               |
|    Body mentions "priority" / "service agreement" / "response time" |
|    / "being processed" etc.                                          |
|                                                                      |
|  CHECK 3 - REQUIRED SECTIONS                                         |
|    greeting (Dear/Hello/Hi)                                         |
|    next_steps ("next step", "if you", "please", "you can")          |
|    closing (regards/sincerely/thank you)                            |
|                                                                      |
|  CHECK 4 - RESTRICTED TERMS                                          |
|    Reject if any of: "internal only", "do not share", "confidential"|
|    "jira", "slack channel", "standup", "sprint", "backlog",         |
|    "tech debt", "workaround", "hack", "TODO", "FIXME", "competitor".|
|                                                                      |
|  CHECK 5 - LENGTH                                                    |
|    50 <= word_count <= 500.                                         |
|    Too short = unhelpful; too long = hard to read.                  |
|                                                                      |
|  CHECK 6 - SOURCE CITATIONS  (Path A only)                          |
|    sources[] must be non-empty (KB article IDs).                    |
|                                                                      |
|  CHECK 7 - PII SCAN                                                  |
|    Regex for SSN (XXX-XX-XXXX) and credit-card patterns.            |
|    Phase 8 will swap this for Amazon Comprehend.                    |
|                                                                      |
|  RESULT:                                                             |
|    All 7 pass -> status = DELIVERING                                |
|    Any fail   -> status = DRAFT_REJECTED                            |
|                  (orchestrator decides re-draft vs human review;    |
|                   max 2 re-drafts before escalation)                |
|                                                                      |
|  TOOLS:    Plain Python regex + string checks (no LLM)              |
|  STRATEGY: Deterministic. Fast (<5ms). Easy to audit and add to.    |
|                                                                      |
|  EXAMPLE FAILURES:                                                   |
|    Path A draft says "we're working on it" but sources=[]           |
|      -> failed_checks = ["no_source_citations"]                     |
|    Body contains "Will discuss in standup tomorrow"                 |
|      -> failed_checks = ["restricted_terms:standup"]                |
+======================================================================+
```

---

## STEP 12 — Delivery (ServiceNow ticket + email send)

```
+=== STEP 12: DELIVERY ================================================+
|                                                                       |
|  FILE:    src/orchestration/nodes/delivery.py                        |
|  CLASS:   DeliveryNode                                                |
|                                                                       |
|  PURPOSE: Create the actual ticket and send the actual email.       |
|                                                                       |
|  PHASE 1 - CREATE SERVICENOW TICKET                                  |
|    POST /api/now/table/incident with subject, description,         |
|    priority, assignment_group, sla_due_at, vendor_id, query_id      |
|    -> returns ticket_id (e.g., INC0010001) + sys_id                |
|                                                                       |
|  PHASE 2 - REPLACE PLACEHOLDER                                       |
|    final_body = body.replace("PENDING", "INC0010001")              |
|    final_subject = subject.replace("PENDING", "INC0010001")        |
|                                                                       |
|  PHASE 3 - PATH-SPECIFIC BEHAVIOR                                    |
|                                                                       |
|    PATH A (resolution):                                              |
|      Persist the finalised draft + ticket info to                   |
|      workflow.case_execution with status=PENDING_APPROVAL.          |
|      Ticket_link row added with status=AwaitingApproval.            |
|      STOPS HERE. An admin must review the draft in the              |
|      draft-approval queue and trigger the actual send via           |
|      DraftApprovalService. (Belt and suspenders - we created the    |
|      ticket but won't email the vendor without human signoff.)     |
|                                                                       |
|    PATH B (acknowledgment):                                          |
|      Send via Graph API /sendMail right now.                        |
|      reply_to_message_id is set so the email lands inside the       |
|      original Outlook thread.                                       |
|      Status -> AWAITING_RESOLUTION.                                 |
|                                                                       |
|    RESOLUTION-MODE (Step 15, Path B back-fill):                      |
|      ServiceNow webhook re-enters the graph at this node with       |
|      resolution_mode=True. Reuse the existing ticket; do not        |
|      create a new one. Send the resolution email. Update            |
|      ServiceNow status to AWAITING_VENDOR_CONFIRMATION. Publish    |
|      ResolutionPrepared event. Register with ClosureService so      |
|      the auto-close timer starts (5 business days).                |
|                                                                       |
|  TOOLS:    ServiceNowConnector (httpx), GraphAPIConnector,         |
|            EventBridgeConnector, PostgresConnector, ClosureService  |
|  STRATEGY: Ticket BEFORE email so the email always carries a real  |
|            INC number. Path A inserts a human checkpoint before the |
|            send - we can audit-trail every AI-drafted email an     |
|            admin approved.                                          |
|                                                                       |
|  EXAMPLE (Path B):                                                   |
|    Ticket created -> INC0010001                                     |
|    Email sent to rajesh@technova.com:                               |
|      Subject: "Re: Invoice INV-9921 - Ticket INC0010001"           |
|      Body:    "Dear Rajesh, We have logged your query as          |
|                INC0010001 ... finance-ops team will respond       |
|                within 8 hours ..."                                  |
|    case_execution.status = "AWAITING_RESOLUTION"                    |
+=======================================================================+
```

---

## PATH C — Triage (the "AI is unsure" path)

```
+=== PATH C: TRIAGE ===================================================+
|                                                                       |
|  FILE:    src/orchestration/nodes/triage.py                          |
|  CLASS:   TriageNode                                                  |
|                                                                       |
|  TRIGGER: ConfidenceCheckNode set processing_path = "C" because     |
|           confidence_score < 0.85.                                   |
|                                                                       |
|  WHAT IT DOES:                                                       |
|    1. Build TriagePackage:                                          |
|       { query_id, correlation_id, callback_token (UUID),            |
|         original_query, analysis_result, confidence_breakdown,      |
|         suggested_routing, suggested_draft, created_at }            |
|    2. INSERT into workflow.triage_packages with status=PENDING.    |
|       ON CONFLICT (query_id) DO NOTHING (idempotent).               |
|    3. UPDATE workflow.case_execution set status=PAUSED,             |
|       processing_path='C'. Workflow stops here.                    |
|    4. Publish HumanReviewRequired event (non-critical).            |
|                                                                       |
|  HOW IT RESUMES:                                                     |
|    Reviewer logs into the Angular triage portal -> sees the        |
|    package -> corrects intent / vendor / routing -> POSTs to       |
|    /triage/{id}/review with the callback_token.                     |
|    The TriageService then re-enqueues the case to SQS with the     |
|    corrected analysis, and the pipeline runs again from Step 9     |
|    with high confidence. SLA clock starts AFTER the review (not    |
|    before) so reviewer wait time is excluded.                       |
|                                                                       |
|  CONFIDENCE BREAKDOWN (helps the reviewer):                          |
|    overall            = 0.62                                        |
|    intent_classification = 0.62                                     |
|    entity_extraction   = 0.42  <- entities missing                  |
|    single_issue_detection = 0.47 <- multi-issue detected           |
|    threshold = 0.85                                                  |
|                                                                       |
|  TOOLS:    PostgresConnector, EventBridgeConnector                  |
|  STRATEGY: Pause-and-wait via callback_token. The token is the      |
|            "key" the reviewer needs to resume - stops anyone from  |
|            replaying random query_ids.                              |
+=======================================================================+
```

---

## STEP 15 — Resolution from Notes (Path B back-fill)

```
+=== STEP 15: RESOLUTION FROM NOTES ===================================+
|                                                                       |
|  FILE:    src/orchestration/nodes/resolution_from_notes.py          |
|  CLASS:   ResolutionFromNotesNode                                    |
|                                                                       |
|  TRIGGER: ServiceNow webhook fires when a Path B ticket is          |
|           resolved (the team marks it RESOLVED with work notes).    |
|           api/routes/webhooks.py -> servicenow_webhook re-enqueues  |
|           the case with resume_context.action="prepare_resolution". |
|                                                                       |
|  ENTRY:   The graph's top-level switch detects the resume_context   |
|           and routes directly here, skipping context_loading and    |
|           query_analysis (already done earlier).                    |
|                                                                       |
|  WHAT IT DOES:                                                       |
|    1. Pull the team's work_notes from ServiceNow.                  |
|    2. Render resolution_from_notes_v1.j2 prompt with vendor name,  |
|       original query, work notes, ticket_id, SLA statement.        |
|    3. Call Claude Sonnet 3.5 (LLM Call #3 for Path B). Output:     |
|       polished resolution email grounded in the team's findings.   |
|    4. Hand off to quality_gate -> delivery (resolution_mode=True). |
|                                                                       |
|  WHY THIS EXISTS:                                                    |
|    The team writes "found duplicate payment, refund issued today"  |
|    in ServiceNow. We don't want them also writing the customer-    |
|    facing email - that's a polish task Claude is great at. The    |
|    team types facts, the LLM types the customer-friendly version. |
|                                                                       |
|  TOOLS:    LLMGateway, PromptManager, ServiceNowConnector          |
|  STRATEGY: Reuse the existing ticket (no new INC). The same        |
|            quality_gate + delivery nodes - one pipeline tail used  |
|            by all 3 entry points.                                   |
+=======================================================================+
```

---

# 3. END-TO-END EXAMPLE (Rajesh from TechNova)

```
+======================================================================+
|        REAL EXAMPLE: PATH A, ~11 SECONDS, ~$0.033 LLM COST            |
+======================================================================+

T+0ms     Vendor sends email:
          From:    rajesh@technova.com
          Subject: Invoice INV-9921 not paid
          Body:    "Hi team, the invoice INV-9921 for INR 45,000
                    due 2026-04-15 is still unpaid..."

T+50ms    Outlook delivers to vendor-support@company.com.
          Webhook (or polling) -> EmailIntakeService.process_email()

T+100ms   E2.1  Idempotency claim: INSERT ON CONFLICT -> True.

T+250ms   E1    GET /messages/{id} -> raw_email JSON

T+260ms   E2.2  EmailParser.parse_email_fields -> sender, subject, body...

T+450ms   E2.5  VendorIdentifier: exact email match in Salesforce ->
                vendor_id="VND-1042", method="exact_email"

T+460ms   E2.1b RelevanceFilter: Layer 2 pass (vendor known),
                Layer 3 pass (no auto-reply headers), Layer 4 skipped.

T+465ms   E2.7  IDs: query_id="VQ-2026-0042", execution_id, correlation_id

T+520ms   E2.3  S3 upload: inbound-emails/VQ-2026-0042/raw_email.json

T+800ms   E2.4  Attachment: invoice.pdf -> pdfplumber ->
                "Invoice INV-9921, INR 45,000, due 2026-04-15..."
                S3: attachments/VQ-2026-0042/ATT-001_invoice.pdf

T+820ms   E2.6  ThreadCorrelator: no match -> NEW

T+900ms   E2.8  Atomic transaction commits 4 inserts.

T+910ms   E2.9a EmailParsed event published.

T+950ms   E2.9b SQS send_message -> outbox marked sent.
                Idempotency claim COMPLETED. Outlook mail marked read.

--- AI Pipeline picks up the message ---

T+1.0s    Step 7  ContextLoading: vendor profile from cache (5ms),
                  recent_interactions (3 prior queries).

T+3.5s    Step 8  QueryAnalysis (Claude Sonnet, 1500 tokens in,
                  500 tokens out, ~$0.012):
                  intent="INVOICE_PAYMENT_DELAY",
                  entities={invoice_number:"INV-9921", amount:"45000",
                            due_date:"2026-04-15"},
                  urgency="HIGH", sentiment="FRUSTRATED",
                  confidence=0.92

T+3.6s    Decision 1: 0.92 >= 0.85 -> continue.

T+3.7s    Step 9A Routing: SILVER tier + HIGH urgency + INVOICE_PAYMENT
                  -> team="finance-ops", SLA=8h.

T+4.2s    Step 9B KBSearch: Titan embed (200ms),
                  pgvector top-5 (50ms), best_score=0.91.

T+4.3s    Decision 2: best=0.91 >= 0.80, content=1243 chars -> Path A.

T+9.5s    Step 10A Resolution (Claude Sonnet, 3000 tokens in,
                   800 tokens out, ~$0.021):
                   subject "Re: Invoice INV-9921 - Payment status [PENDING]"
                   body cites KB-LP-014, KB-IP-023.

T+9.55s   Step 11 Quality Gate: all 7 checks pass.

T+10.5s   Step 12 Delivery:
                  - ServiceNow create_ticket -> INC0010001
                  - Replace "PENDING" with "INC0010001"
                  - Path A pause: persist draft + ticket info,
                    status=PENDING_APPROVAL.
                  - Admin reviews and approves the draft.
                  - send_email via Graph /sendMail.
                  - status=AWAITING_VENDOR_CONFIRMATION.

T+11.0s   Email lands in Rajesh's inbox.

TOTAL: ~11 seconds, 2 LLM calls (~$0.033), zero engineer time.
+======================================================================+
```

---

# 4. CROSS-CUTTING STRATEGIES (the "why" behind everything)

```
+======================================================================+
|                  STRATEGY 1: CRITICAL vs NON-CRITICAL                  |
+======================================================================+
|  Every step is tagged.                                                |
|  CRITICAL steps - failure raises, SQS retries the message.            |
|  NON-CRITICAL steps - failure is logged as warning, pipeline keeps    |
|                       going with safe defaults.                       |
|  Example: vendor lookup failing is non-critical (we use vendor_id=    |
|  None). Atomic DB write failing is critical (no half-saved state).    |
+======================================================================+

+======================================================================+
|              STRATEGY 2: TRANSACTIONAL OUTBOX (DB + SQS)               |
+======================================================================+
|  Write outbox row inside the same DB transaction as the case row.    |
|  Publish to SQS AFTER commit. If publish fails, a drainer retries.   |
|  Result: at-least-once delivery without distributed transactions.    |
+======================================================================+

+======================================================================+
|                STRATEGY 3: 8-LAYER DEFENSE FOR LLM CALLS              |
+======================================================================+
|  Validate -> prompt -> retry -> parse -> validate -> self-correct -> |
|  fallback -> log. The pipeline ALWAYS produces a result. Safe        |
|  fallback (confidence 0.3) auto-routes to Path C.                    |
+======================================================================+

+======================================================================+
|              STRATEGY 4: 3 PATHS (A, B, C) FROM THE START             |
+======================================================================+
|  We never assumed the AI would always be right. Path A handles the   |
|  90% case (clear KB hit). Path B handles "we know who but not what" |
|  (acknowledgment now, real reply later). Path C handles "we don't    |
|  know what they're asking" (human reviewer corrects, then resume).  |
+======================================================================+

+======================================================================+
|             STRATEGY 5: CORRELATION_ID ON EVERY LOG LINE              |
+======================================================================+
|  Bound to structlog contextvars at the top of process_email().      |
|  Every log line in every adapter, node, and helper picks it up      |
|  automatically. Grepping by correlation_id lets you reconstruct an   |
|  entire request across services.                                     |
+======================================================================+

+======================================================================+
|                STRATEGY 6: NO REDIS (Postgres for everything)         |
+======================================================================+
|  Idempotency: cache.idempotency_keys with UNIQUE + ON CONFLICT.     |
|  Caching:     cache.vendor_cache, cache.workflow_state_cache with    |
|               expires_at + a 15-min cleanup job.                     |
|  Vector DB:   pgvector inside the same Postgres.                     |
|  Why: one database to operate, no sync, fewer moving parts.         |
+======================================================================+

+======================================================================+
|              STRATEGY 7: 7-CHECK QUALITY GATE (DETERMINISTIC)        |
+======================================================================+
|  No "the LLM said it's fine". Plain regex + string checks. Easy to   |
|  audit. Easy to add new checks. Catches real-world failures (PII,   |
|  internal jargon) the LLM happily emits otherwise.                  |
+======================================================================+

+======================================================================+
|                STRATEGY 8: TIERED FILTERING (cheap -> expensive)      |
+======================================================================+
|  Relevance filter runs cheap rules first (regex, headers), only      |
|  hits the LLM classifier for borderline content. Saves >95% of      |
|  bogus Bedrock calls.                                                |
+======================================================================+
```

---

# 5. MENTAL MODEL FOR YOUR MANAGER (one slide)

```
+======================================================================+
|                          ONE-SLIDE STORY                              |
+======================================================================+
|                                                                       |
|  Email arrives -> we claim it (no duplicates) -> fetch -> parse ->   |
|  identify vendor -> filter spam -> store in S3 + Postgres + outbox   |
|  -> SQS.                                                              |
|                                                                       |
|  Pipeline: load context -> Claude reads it -> high confidence?        |
|    NO  -> human reviewer fixes it (Path C, workflow pauses)           |
|    YES -> route by team & SLA -> search KB -> KB has facts?           |
|             YES -> Claude drafts the answer (Path A, admin approves) |
|             NO  -> send "we got it" reply, team investigates         |
|                    (Path B, team finishes, Claude drafts the         |
|                    polished reply from their notes)                  |
|                                                                       |
|  Every outbound email passes 7 checks before sending. Every step is  |
|  logged with one correlation_id you can grep across services.        |
|                                                                       |
|  Reliability comes from: idempotency claims, atomic DB writes,       |
|  outbox publishing, critical/non-critical step tagging, and an       |
|  8-layer defense around the LLM call.                                |
+======================================================================+
```
