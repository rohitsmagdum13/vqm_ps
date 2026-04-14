# VQMS — Complete ASCII Flow Diagrams (Updated with All Three Paths)

## Real Example Used Throughout

```
WHO:    Rajesh Mehta, TechNova Solutions Pvt. Ltd. (VN-30892)
WHAT:   Payment status inquiry for Invoice #INV-2026-0451 (Rs.4,75,000)
RESULT: AI resolved in ~11 seconds, cost ~$0.033, ticket INC0019847
```

---

# ══════════════════════════════════════════════════════════════════
# OUTPUT 1: DETAILED TECHNICAL ASCII FLOW
# ══════════════════════════════════════════════════════════════════

```
╔══════════════════════════════════════════════════════════════════════════════╗
║        VQMS FULL END-TO-END TECHNICAL FLOW — Rajesh's Query Journey        ║
║        VQ-2026-0108 | Invoice #INV-2026-0451 | TechNova Solutions          ║
║                                                                              ║
║        ★ NOW SHOWS ALL THREE PATHS: A (AI-Resolved), B (Human-Team),    ║
║          and C (Low-Confidence → Human Review → Resume)                  ║
╚══════════════════════════════════════════════════════════════════════════════╝


┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 1: VENDOR LOGIN                                                        │
│                                                                              │
│ Input:   Rajesh's email (rajesh.mehta@technovasolutions.in) + password       │
│          OR Company SSO redirect                                             │
│                                                                              │
│ What happens:                                                                │
│   1. Rajesh enters credentials on the VQMS portal login page                 │
│   2. Credentials sent to authentication service                              │
│   3. Identity verified against user pool                                     │
│   4. Secure session token (JWT) created with claims:                         │
│        vendor_id = "VN-30892", role = "VENDOR"                               │
│        scopes = ["queries.own", "kb.read", "prefs.own"]                      │
│        expires in 8 hours                                                    │
│   5. Session cached for fast re-validation                                   │
│                                                                              │
│ Services used:                                                               │
│   - AWS Cognito (vqms-agent-portal-users): Validates email+password or       │
│     federated SSO, creates JWT with vendor claims and role scopes            │
│   - Redis (vqms:session:<token>): Stores session state with 8-hour TTL      │
│     for fast subsequent request validation                                   │
│   - Company SSO (Okta / Azure AD): If SSO path, handles password check      │
│     and returns SAML/OIDC assertion back to Cognito                          │
│                                                                              │
│ Output:  JWT session token with vendor_id=VN-30892, role=VENDOR              │
│          Rajesh can only see TechNova's data — enforced server-side          │
│                                                                              │
│ Time: < 800ms | Cost: $0.00 | LLM: No                                       │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 2: PORTAL DASHBOARD LOADS                                               │
│                                                                              │
│ Input:   JWT token from Step 1, vendor_id = VN-30892                         │
│                                                                              │
│ What happens:                                                                │
│   1. Browser sends GET /vendor/queries?vendor_id=INF with JWT                │
│   2. API Gateway validates the JWT via Cognito Authorizer                    │
│   3. Backend checks Redis cache for pre-computed KPIs                        │
│      - CACHE HIT (< 5 min old): use cached numbers, skip database           │
│      - CACHE MISS: query PostgreSQL for counts, compute KPIs,               │
│        write fresh cache entry with 5-min TTL                                │
│   4. Fetch 10 most recent queries for this vendor from PostgreSQL            │
│   5. Return dashboard payload to browser                                     │
│                                                                              │
│ Services used:                                                               │
│   - API Gateway + Cognito Authorizer: Validates JWT, extracts vendor_id,     │
│     rejects invalid/expired tokens with 401                                  │
│   - Redis (vqms:vendor:VN-30892:kpis): Fast KPI cache with 5-min TTL        │
│     Returns: open=3, resolved=11, avg_response=3.1h                          │
│   - PostgreSQL (workflow.case_execution): Source of truth for query           │
│     counts and recent queries when cache is expired                           │
│                                                                              │
│ Output:  Dashboard data: 3 open, 11 resolved, 3.1h avg, 4 recent queries    │
│          Rajesh sees: "Welcome back, Rajesh | TechNova Solutions"            │
│                                                                              │
│ Time: < 400ms (cache hit) / < 1200ms (cache miss) | Cost: $0.00 | LLM: No  │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 3: WIZARD — PICK QUERY TYPE                                             │
│                                                                              │
│ Input:   Rajesh clicks "+ New Query" on dashboard                            │
│                                                                              │
│ What happens:                                                                │
│   1. Browser displays 6 query type cards:                                    │
│      Contract | Invoice | Delivery | Tech Support | SLA | Other              │
│   2. Rajesh selects "Invoice Issue"                                          │
│   3. Selection saved in browser memory ONLY (JavaScript variable)            │
│      WD.type = "invoice"                                                     │
│   4. NO server call is made — zero network traffic                           │
│                                                                              │
│ Services used:                                                               │
│   - Browser only (client-side React state): Stores selection locally         │
│     No backend, no Redis, no PostgreSQL, no API call                         │
│                                                                              │
│ Output:  WD.type = "invoice" stored in browser memory                        │
│          This becomes a classification HINT for the AI in Step 8             │
│          (AI still makes its own independent classification)                  │
│                                                                              │
│ Time: 0ms (instant) | Cost: $0.00 | LLM: No                                 │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 4: WIZARD — FILL IN DETAILS                                             │
│                                                                              │
│ Input:   Query type "invoice" selected in Step 3                             │
│                                                                              │
│ What happens:                                                                │
│   1. Rajesh fills in subject:                                                │
│      "Payment Status Inquiry - Invoice #INV-2026-0451"                       │
│   2. Rajesh fills in description (478 chars):                                │
│      "I am writing on behalf of TechNova Solutions Pvt. Ltd.                 │
│       (Vendor Code: VN-30892) to inquire about the payment status..."        │
│   3. Selects priority: HIGH (portal shows "Expected response: 4 hours")      │
│   4. Enters reference: PO-HEX-78412                                         │
│   5. All data saved in browser memory ONLY — still no server call            │
│                                                                              │
│ Services used:                                                               │
│   - Browser only (client-side React state): Accumulates wizard data          │
│     WD = { type:"invoice", subject:"...", desc:"...",                        │
│            priority:"High", ref:"PO-HEX-78412" }                            │
│                                                                              │
│ Output:  Complete WD object in browser memory, ready for review              │
│          Subject+description = PRIMARY input to AI analysis (Step 8)         │
│          Priority = determines SLA deadline (High = 4 hours)                 │
│          Reference = used by routing to check Salesforce for existing PO     │
│                                                                              │
│ Time: 0ms (vendor's typing time) | Cost: $0.00 | LLM: No                    │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 5: WIZARD — REVIEW & CONFIRM                                            │
│                                                                              │
│ Input:   Complete WD object from Steps 3-4                                   │
│                                                                              │
│ What happens:                                                                │
│   1. Browser renders summary card showing all entered data:                  │
│      Type: Invoice Issue | Subject: Payment Status...                        │
│      Priority: High | Reference: PO-HEX-78412                               │
│      Company: TechNova Solutions | Expected SLA: 4 hours                     │
│   2. "Assigned to: Auto (QueryAnalysisAgent)" shown — AI handles first       │
│   3. Rajesh can click "Back" to change any field                             │
│   4. Still NO server call — last chance to edit before submission             │
│                                                                              │
│ Services used:                                                               │
│   - Browser only (client-side rendering): Displays confirmation view         │
│                                                                              │
│ Output:  Rajesh confirms and clicks "Submit Query"                           │
│          Browser builds POST payload with WD fields + vendor_id from JWT     │
│                                                                              │
│ Time: 0ms (vendor's review time) | Cost: $0.00 | LLM: No                    │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 6: SUBMIT QUERY — FIRST SERVER CONTACT                                  │
│                                                                              │
│ Input:   POST /queries with JWT + payload:                                   │
│          { type:"invoice", subject:"Payment Status Inquiry -                 │
│            Invoice #INV-2026-0451", description:"I am writing on             │
│            behalf of TechNova...", priority:"High",                           │
│            reference:"PO-HEX-78412" }                                        │
│          NOTE: vendor_id is NOT in payload — extracted from JWT              │
│                                                                              │
│ What happens:                                                                │
│                                                                              │
│   SUB-STEP 6.1: API GATEWAY + COGNITO AUTHORIZER                            │
│     - Receives HTTPS request, passes JWT to Cognito                          │
│     - Cognito validates: signature OK, not expired, role=VENDOR              │
│     - Extracts vendor_id=VN-30892 and attaches to request context            │
│     - Forwards enriched request to Query API Service                         │
│                                                                              │
│   SUB-STEP 6.2: QUERY API SERVICE — VALIDATE                                │
│     - Pydantic model (QuerySubmission) validates all fields                  │
│     - type: "invoice" -> valid | subject: present -> valid                   │
│     - description: 478 chars -> valid | priority: "High" -> valid            │
│                                                                              │
│   SUB-STEP 6.3: GENERATE IDENTIFIERS                                        │
│     - query_id:       VQ-2026-0108 (sequential, human-readable)              │
│     - execution_id:   b2c4d6e8-... (UUID v4, internal tracking)              │
│     - correlation_id: f1a2b3c4-... (UUID v4, cross-system linking)           │
│                                                                              │
│   SUB-STEP 6.4: IDEMPOTENCY CHECK                                           │
│     - Redis GET vqms:idempotency:<sha256(subject+desc+vendor)>               │
│     - Result: NOT FOUND -> new query, proceed                                │
│     - If FOUND: would return existing query_id (prevents double-submit)      │
│                                                                              │
│   SUB-STEP 6.5: SAVE TO DATABASE                                            │
│     - INSERT INTO workflow.case_execution with all fields                    │
│     - status = 'OPEN', created_at = 2026-04-02T08:14:00Z                    │
│                                                                              │
│   SUB-STEP 6.6: SET IDEMPOTENCY GUARD                                       │
│     - Redis SET vqms:idempotency:<hash> "VQ-2026-0108" EX 604800 (7 days)   │
│                                                                              │
│   SUB-STEP 6.7: PUBLISH EVENT                                               │
│     - EventBridge: QueryReceived on vqms-event-bus                           │
│     - Payload: { query_id, vendor_id, priority, timestamp }                  │
│                                                                              │
│   SUB-STEP 6.8: QUEUE FOR AI PIPELINE                                       │
│     - SQS: Push full query payload to vqms-query-intake-queue                │
│     - DLQ: vqms-dlq configured (3 retries before dead-letter)                │
│                                                                              │
│   SUB-STEP 6.9: RETURN RESPONSE TO BROWSER                                  │
│     - HTTP 201 Created                                                       │
│     - { query_id:"VQ-2026-0108", status:"Open",                             │
│         sla_deadline:"2026-04-02T12:14:00Z" }                                │
│                                                                              │
│ Services used:                                                               │
│   - API Gateway + Cognito Authorizer: JWT validation, vendor_id extraction   │
│   - Query API Service (Pydantic): Payload validation, ID generation          │
│   - Redis: Idempotency check (GET) + guard (SET with 7-day TTL)             │
│   - PostgreSQL (workflow.case_execution): Persist query record               │
│   - EventBridge (vqms-event-bus): Publish QueryReceived event                │
│   - SQS (vqms-query-intake-queue): Queue message for async AI pipeline       │
│                                                                              │
│ Output:  Rajesh gets VQ-2026-0108 in ~400ms. Browser shows success screen.   │
│          Writes: PostgreSQL(1), Redis(2), SQS(1), EventBridge(1)             │
│                                                                              │
│ Time: < 500ms | Cost: $0.00 | LLM: No                                       │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
          ═════════════════════════════════════════════════════
           ★ ASYNC BOUNDARY — Rajesh gets his response HERE.
             Everything below runs in the background.
             Rajesh does NOT wait. He can close his browser.
          ═════════════════════════════════════════════════════
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 7: LANGGRAPH ORCHESTRATOR — CONTEXT LOADING                             │
│                                                                              │
│ Input:   SQS message from vqms-query-intake-queue containing full query      │
│          payload (execution_id, query_id, vendor_id, type, subject,          │
│          description, priority, reference, created_at)                        │
│                                                                              │
│ What happens:                                                                │
│                                                                              │
│   SUB-STEP 7.1: UPDATE STATUS                                               │
│     - PostgreSQL: UPDATE case_execution SET status='ANALYZING'               │
│                                                                              │
│   SUB-STEP 7.2: CACHE WORKFLOW STATE                                         │
│     - Redis SET vqms:workflow:b2c4d6e8-...                                   │
│       { status:"ANALYZING", query_id:"VQ-2026-0108",                         │
│         vendor_id:"VN-30892", step:"INIT" }                                  │
│       TTL = 24 hours                                                         │
│                                                                              │
│   SUB-STEP 7.3: LOAD VENDOR PROFILE                                         │
│     - Redis GET vqms:vendor:VN-30892                                         │
│     - Result: CACHE MISS (TechNova profile expired > 1 hour ago)             │
│     - Fallback to Salesforce CRM API:                                        │
│       SELECT Account WHERE Vendor_Id__c = 'VN-30892'                         │
│     - Result: tier=SILVER, risk_flags=["OVERDUE_INVOICE_HISTORY"],           │
│       account_manager="Anil Kapoor", payment_terms="Net 30"                  │
│     - Cache result: Redis SET vqms:vendor:VN-30892 <json> EX 3600 (1 hour)  │
│                                                                              │
│   SUB-STEP 7.4: LOAD VENDOR HISTORY (EPISODIC MEMORY)                       │
│     - PostgreSQL SELECT FROM memory.episodic_memory                          │
│       WHERE vendor_id='VN-30892' ORDER BY created_at DESC LIMIT 5            │
│     - Result: 3 prior queries in 90 days:                                    │
│       1. "Invoice INV-2026-0203 payment delay" resolved 2.8h                 │
│       2. "PO mismatch on PO-HEX-71234" resolved 4.1h                        │
│       3. "GST credit note request" resolved 6.2h                             │
│                                                                              │
│ Services used:                                                               │
│   - LangGraph Orchestrator: SQS consumer, workflow initialization            │
│   - SQS (vqms-query-intake-queue): Source of trigger message                 │
│   - PostgreSQL (workflow.case_execution): Status update                       │
│   - Redis (vqms:workflow:*): Workflow state cache (24h TTL)                   │
│   - Redis (vqms:vendor:VN-30892): Vendor profile cache check (MISS)         │
│   - Salesforce CRM API: Vendor master lookup (tier, risk, contacts)          │
│   - Redis (vqms:vendor:VN-30892): Cache Salesforce result (1h TTL)           │
│   - PostgreSQL (memory.episodic_memory): Historical vendor interactions      │
│                                                                              │
│ Output:  Full context package assembled:                                     │
│          { query, vendor_profile (Silver, risk flags),                        │
│            vendor_history (3 prior queries), execution_metadata }             │
│          Ready for AI analysis                                               │
│                                                                              │
│ Time: ~800ms (Salesforce miss adds ~200ms) | Cost: $0.00 | LLM: No          │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 8: QUERY ANALYSIS AGENT — LLM CALL #1                                  │
│                                                                              │
│ Input:   Full context package from Step 7:                                   │
│          - Query: type, subject, description, reference                      │
│          - Vendor profile: TechNova, Silver tier, OVERDUE_INVOICE_HISTORY    │
│          - History: 3 prior queries (payment patterns)                        │
│                                                                              │
│ What happens:                                                                │
│                                                                              │
│   SUB-STEP 8.1: LOAD PROMPT TEMPLATE                                        │
│     - S3 GET from vqms-knowledge-artifacts-prod                              │
│       templates/query-analysis/v2.json                                       │
│                                                                              │
│   SUB-STEP 8.2: BUILD PROMPT                                                │
│     - System: "You are a query analysis agent for VQMS. Return JSON:         │
│       intent_classification, extracted_entities, urgency_level,               │
│       sentiment, confidence_score, multi_issue_detected,                      │
│       suggested_category"                                                    │
│     - User: query fields + vendor profile + history                          │
│                                                                              │
│   SUB-STEP 8.3: CALL BEDROCK (Claude Sonnet 3.5)                            │
│     - Temperature: 0.1 (low for classification precision)                    │
│     - Max tokens: 500 | Input: ~1,500 tokens | Output: ~500 tokens           │
│                                                                              │
│   SUB-STEP 8.4: PARSE RESPONSE (Pydantic: AnalysisResult)                   │
│     - intent: PAYMENT_QUERY (not INVOICE_DISPUTE — he's asking where         │
│       his money is, not arguing about the amount)                             │
│     - entities: INV-2026-0451, 2026-02-15, Rs.475000, PO-HEX-78412,         │
│       due 2026-03-17, VN-30892, TechNova, Rajesh Mehta                       │
│     - urgency: HIGH (16 days overdue)                                        │
│     - sentiment: POLITE_CONCERNED                                            │
│     - confidence: 0.96 (very clear intent, structured message)               │
│     - multi_issue: false                                                     │
│                                                                              │
│   SUB-STEP 8.5: CONFIDENCE BRANCH                                           │
│     - 0.96 >= 0.85 threshold -> PATH: FULL_AUTOMATION                        │
│     - If < 0.85: would route to human review (LOW_CONFIDENCE path)           │
│                                                                              │
│   SUB-STEP 8.6: SAVE & PUBLISH                                              │
│     - S3: prompt snapshot for audit trail                                     │
│     - PostgreSQL: UPDATE case_execution with analysis_result                  │
│     - Redis: workflow state -> ANALYSIS_COMPLETE                              │
│     - PostgreSQL: INSERT audit.action_log (ANALYSIS_COMPLETED)               │
│     - EventBridge: AnalysisCompleted event                                   │
│                                                                              │
│ Services used:                                                               │
│   - S3 (vqms-knowledge-artifacts-prod): Load versioned prompt template       │
│   - Amazon Bedrock (Claude Sonnet 3.5): LLM inference for classification     │
│     via Bedrock Integration Service (single LLM gateway)                     │
│   - S3 (vqms-knowledge-artifacts-prod): Store prompt snapshot for audit      │
│   - PostgreSQL (workflow.case_execution): Store analysis result (JSONB)       │
│   - PostgreSQL (audit.action_log): Immutable audit record                    │
│   - Redis (vqms:workflow:*): Update workflow state cache                      │
│   - EventBridge (vqms-event-bus): Publish AnalysisCompleted event            │
│                                                                              │
│ Output:  AnalysisResult: { intent:PAYMENT_QUERY, confidence:0.96,            │
│          urgency:HIGH, sentiment:POLITE_CONCERNED, multi_issue:false }        │
│          Decision: FULL_AUTOMATION (high confidence, clear intent)            │
│                                                                              │
│ Time: ~3 seconds | Cost: ~$0.012 | LLM: YES (Bedrock Claude Sonnet 3.5)     │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║  ★★★ CONFIDENCE DECISION POINT (at Step 8.5) ★★★                           ║
║                                                                              ║
║  AI returned confidence score. What happens next?                           ║
║                                                                              ║
║    confidence >= 0.85  →  Continue to Step 9 (then PATH A or B)             ║
║                           ★ Rajesh's case: 0.96 → goes here                ║
║                                                                              ║
║    confidence < 0.85   →  PATH C: Low-Confidence Human Review               ║
║                           AI is NOT sure enough. A human must verify         ║
║                           before the system proceeds.                        ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
                           │                           │
                  ┌────────┘                           └────────┐
                  │                                             │
          confidence >= 0.85                            confidence < 0.85
          (Rajesh's case)                               (PATH C)
                  │                                             │
                  │                                             ▼
                  │
                  │    ═══════════════════════════════════════════════════════
                  │    PATH C: LOW-CONFIDENCE → HUMAN REVIEW → RESUME
                  │    ═══════════════════════════════════════════════════════
                  │
                  │    ┌─────────────────────────────────────────────────────────────┐
                  │    │ STEP 8C.1: TRIAGE PACKAGE CREATED                           │
                  │    │                                                              │
                  │    │ Input:   AnalysisResult with low confidence (e.g., 0.62)     │
                  │    │          + VendorMatch (possibly UNRESOLVED)                  │
                  │    │          + Multi-issue detected with ambiguous priority       │
                  │    │                                                              │
                  │    │ What happens:                                                │
                  │    │   The AI is NOT confident enough to proceed automatically.   │
                  │    │   Possible reasons:                                          │
                  │    │     - Vague or unclear query (multiple possible intents)      │
                  │    │     - Vendor not found in Salesforce (UNRESOLVED)             │
                  │    │     - Multiple issues in one email (ambiguous priority)       │
                  │    │     - Unusual request that doesn't match known patterns       │
                  │    │                                                              │
                  │    │   System creates a TriagePackage containing:                 │
                  │    │     - Original query                                         │
                  │    │     - AI's analysis result (with low scores)                  │
                  │    │     - Vendor match (or lack thereof)                          │
                  │    │     - Suggested routing (AI's best guess)                    │
                  │    │     - Suggested draft (AI's best attempt)                    │
                  │    │     - Confidence breakdown per dimension                      │
                  │    │     - Reasons for low confidence                              │
                  │    │                                                              │
                  │    │ Services used:                                               │
                  │    │   - SQS (vqms-human-review-queue): TriagePackage pushed      │
                  │    │   - AWS Step Functions: Workflow PAUSES using callback        │
                  │    │     token pattern — a task token is generated and stored      │
                  │    │     with the triage package. The workflow will NOT proceed    │
                  │    │     until a human sends the callback.                        │
                  │    │   - PostgreSQL: case_execution status = PAUSED_HUMAN_REVIEW  │
                  │    │   - EventBridge: HumanReviewRequired event published         │
                  │    │                                                              │
                  │    │ Output:  TriagePackage in human review queue.                │
                  │    │          Workflow PAUSED — nothing else happens until         │
                  │    │          a human reviewer acts.                              │
                  │    │                                                              │
                  │    │ Time: < 500ms | Cost: $0.00 | LLM: No                       │
                  │    └─────────────────────────────────────────────────────────────┘
                  │                                             │
                  │                                             ▼
                  │    ┌─────────────────────────────────────────────────────────────┐
                  │    │ STEP 8C.2: HUMAN REVIEWER REVIEWS AND CORRECTS              │
                  │    │                                                              │
                  │    │ Input:   TriagePackage in human review portal                │
                  │    │                                                              │
                  │    │ What happens:                                                │
                  │    │   1. Human reviewer gets notification (email/portal alert)   │
                  │    │   2. Reviewer logs into triage portal (authenticated via     │
                  │    │      Cognito: vqms-agent-portal-users)                       │
                  │    │   3. Reviewer sees the full TriagePackage:                   │
                  │    │      - Original vendor query                                 │
                  │    │      - AI's best-guess classification                        │
                  │    │      - AI's confidence scores per dimension                  │
                  │    │      - Suggested routing and draft                           │
                  │    │   4. Reviewer validates or corrects:                         │
                  │    │      - Issue classification (e.g., fix intent from           │
                  │    │        GENERAL_INQUIRY to PAYMENT_QUERY)                     │
                  │    │      - Vendor match (manually identify the vendor)           │
                  │    │      - Routing decision (confirm or change team)             │
                  │    │      - Draft suggestion (approve or edit)                    │
                  │    │   5. Reviewer submits corrections                            │
                  │    │                                                              │
                  │    │ Services used:                                               │
                  │    │   - Cognito (vqms-agent-portal-users): Reviewer auth         │
                  │    │   - Human review portal (web UI): Displays triage package,   │
                  │    │     allows corrections                                       │
                  │    │   - PostgreSQL: case_execution updated with reviewer          │
                  │    │     corrections (corrected intent, vendor, routing)           │
                  │    │   - Memory & Context Service: Corrections fed back for       │
                  │    │     future learning (improves AI over time)                  │
                  │    │   - PostgreSQL (audit.action_log): Records review action,    │
                  │    │     reviewer identity, corrections made, time taken           │
                  │    │                                                              │
                  │    │ Output:  Corrected analysis with human-validated data:       │
                  │    │          { corrected_intent, corrected_vendor,                │
                  │    │            corrected_routing, reviewer_id, review_time }      │
                  │    │                                                              │
                  │    │ Time: Minutes to hours (depends on reviewer availability)    │
                  │    │ Cost: $0.00 (human labor, no LLM) | LLM: No                 │
                  │    └─────────────────────────────────────────────────────────────┘
                  │                                             │
                  │                                             ▼
                  │    ┌─────────────────────────────────────────────────────────────┐
                  │    │ STEP 8C.3: WORKFLOW RESUMES WITH CORRECTED DATA             │
                  │    │                                                              │
                  │    │ Input:   Reviewer's corrections via callback                 │
                  │    │                                                              │
                  │    │ What happens:                                                │
                  │    │   1. Reviewer's submission calls Step Functions               │
                  │    │      SendTaskSuccess with the callback token                 │
                  │    │   2. Workflow RESUMES with corrected data                    │
                  │    │   3. PostgreSQL: case_execution updated with                 │
                  │    │      reviewer-validated analysis_result                       │
                  │    │   4. status changes from PAUSED_HUMAN_REVIEW to ANALYZING   │
                  │    │                                                              │
                  │    │   The corrected data now has HIGH confidence because          │
                  │    │   a human verified it. The flow continues to Step 9           │
                  │    │   (Routing + KB Search) with the corrected data.             │
                  │    │                                                              │
                  │    │ Services used:                                               │
                  │    │   - Step Functions: SendTaskSuccess resumes workflow          │
                  │    │   - PostgreSQL: Updated with corrected analysis              │
                  │    │   - Redis: Workflow state updated                             │
                  │    │   - EventBridge: HumanReviewCompleted event                  │
                  │    │                                                              │
                  │    │ Output:  Corrected, human-validated data ready for routing   │
                  │    │          Flow continues to Step 9 (same as high-confidence)  │
                  │    │                                                              │
                  │    │ Time: < 500ms (resume) | Cost: $0.00 | LLM: No              │
                  │    └─────────────────────────────────────────────────────────────┘
                  │                                             │
                  │         PATH C rejoins main flow here       │
                  │                ┌────────────────────────────┘
                  │                │
                  ▼                ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 9: ROUTING + KB SEARCH — PARALLEL EXECUTION (NO LLM)                    │
│                                                                              │
│ Input:   AnalysisResult + VendorProfile + TicketCorrelation                  │
│                                                                              │
│ ┌────────────────────────────────┐ ┌────────────────────────────────────┐    │
│ │ 9A: ROUTING SERVICE            │ │ 9B: KB SEARCH SERVICE              │    │
│ │ (deterministic rules engine)   │ │ (embedding + pgvector search)      │    │
│ │                                │ │                                    │    │
│ │ Rules evaluated:               │ │ 1. Embed query text:               │    │
│ │  confidence >= 0.85? YES(0.96) │ │    Bedrock Titan v2 -> vector(1536)│    │
│ │  urgency == CRITICAL? NO(HIGH) │ │                                    │    │
│ │  existing ticket? NO           │ │ 2. pgvector cosine similarity:     │    │
│ │  BLOCK_AUTOMATION flag? NO     │ │    SELECT FROM embedding_index     │    │
│ │                                │ │    WHERE category='invoice_payment'│    │
│ │ Decision: FULL_AUTOMATION      │ │    ORDER BY similarity DESC        │    │
│ │ Team: Finance Team             │ │    LIMIT 5                         │    │
│ │ SLA: 4 hours (High + Silver)   │ │                                    │    │
│ │ Risk: OVERDUE_INVOICE_HISTORY  │ │ 3. Results:                        │    │
│ │  -> logged, not blocking       │ │    KB#1203 "Invoice Payment        │    │
│ │                                │ │     Status Check Procedure"  96%   │    │
│ │ PostgreSQL INSERT              │ │    KB#891  "Overdue Invoice         │    │
│ │  routing_decision              │ │     Escalation Policy"       89%   │    │
│ │                                │ │    KB#1456 "AP Payment Timeline     │    │
│ │ Time: <50ms | Cost: $0.00     │ │     by Vendor Tier"          82%   │    │
│ │                                │ │    KB#672  "Three-Way Match         │    │
│ │                                │ │     Failure Resolution"      71%   │    │
│ │                                │ │                                    │    │
│ │                                │ │ Time: <200ms | Cost: ~$0.0001     │    │
│ └────────────────────────────────┘ └────────────────────────────────────┘    │
│                                                                              │
│ Services used:                                                               │
│   - RoutingService (rules engine): Deterministic routing based on            │
│     intent + vendor tier + urgency + risk flags + policy matrix              │
│   - PostgreSQL (workflow.routing_decision): Persist routing decision          │
│   - Amazon Bedrock (Titan Embed v2): Embed query text to vector(1536)       │
│   - PostgreSQL + pgvector (memory.embedding_index): Cosine similarity        │
│     search across knowledge base articles                                    │
│                                                                              │
│ Output:  Routing: FULL_AUTOMATION, Finance Team, 4h SLA                      │
│          KB matches: 4 articles (96%, 89%, 82%, 71% similarity)              │
│                                                                              │
│ Time: < 200ms (parallel) | Cost: ~$0.0001 | LLM: No (embedding only)        │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║  ★★★ CRITICAL DECISION POINT: CAN THE AI ANSWER FROM THE KB? ★★★           ║
║                                                                              ║
║  (Only reached if confidence >= 0.85 — PATH C queries already diverted)     ║
║                                                                              ║
║  The system checks: Do the KB articles contain enough factual information   ║
║  to give the vendor a CONCRETE answer?                                      ║
║                                                                              ║
║    KB match >= 80% AND answer contains specific facts (dates, amounts,      ║
║    procedures) AND ResolutionAgent confidence >= 0.85                        ║
║                                                                              ║
║    YES → PATH A: AI drafts RESOLUTION email (full answer)                   ║
║    NO  → PATH B: AI drafts ACKNOWLEDGMENT email only (no answer yet)        ║
║                  Human team investigates and provides the real answer         ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
                           │                           │
                  ┌────────┘                           └────────┐
                  │                                             │
                  ▼                                             ▼
  ╔═══════════════════════════════╗          ╔═══════════════════════════════╗
  ║  PATH A: AI HAS THE ANSWER   ║          ║  PATH B: AI DOES NOT HAVE    ║
  ║  (KB articles are enough)     ║          ║  THE ANSWER (needs human     ║
  ║                               ║          ║  team to investigate)         ║
  ║  Example: "When is my         ║          ║                               ║
  ║  payment?" — KB has payment   ║          ║  Example: "Why was my         ║
  ║  cycle dates and policies     ║          ║  payment rejected?" — KB      ║
  ║                               ║          ║  does not have Rajesh's       ║
  ║  ★ Rajesh's case follows      ║          ║  specific payment details     ║
  ║    this path ★                ║          ║                               ║
  ╚═══════════════════════════════╝          ╚═══════════════════════════════╝
                  │                                             │
                  ▼                                             ▼

═══════════════════════════════════════════════════════════════════════════════
PATH A: AI-RESOLVED FLOW (KB has the answer)
═══════════════════════════════════════════════════════════════════════════════

┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 10A: RESOLUTION AGENT — LLM CALL #2 (FULL ANSWER)                      │
│                                                                              │
│ Input:   AnalysisResult + KB articles (3 full texts) + VendorProfile +       │
│          SLA (4h) + Vendor history (3 prior queries)                         │
│                                                                              │
│ What happens:                                                                │
│   The AI has real facts from the KB to work with:                            │
│     - KB#1203 says: payment cycle runs on 1st and 5th of each month          │
│     - KB#891 says: overdue invoices with 3-way match go to next cycle        │
│     - KB#1456 says: Silver tier = standard processing, 3-5 day credit        │
│                                                                              │
│   Using these FACTS, the AI writes a RESOLUTION email:                       │
│     "Dear Rajesh, Invoice #INV-2026-0451 passed three-way match on           │
│      Feb 28. Payment approved, scheduled for April 5 processing.             │
│      Expected credit by April 10. If you need expedited payment,             │
│      let us know."                                                           │
│                                                                              │
│   The AI is NOT making this up. It found the answer in company records.      │
│                                                                              │
│   SUB-STEP 10A.1: LOAD PROMPT TEMPLATE from S3                              │
│   SUB-STEP 10A.2: ASSEMBLE FULL CONTEXT (query + KB + vendor + SLA)         │
│   SUB-STEP 10A.3: CALL BEDROCK (Claude Sonnet 3.5, temp 0.3, ~3000 in)     │
│   SUB-STEP 10A.4: PARSE RESPONSE (Pydantic: DraftResponse)                  │
│     - confidence: 0.93 | sources: KB#1203, KB#891                            │
│   SUB-STEP 10A.5: SAVE & PUBLISH (PG, S3, Redis, EventBridge)               │
│                                                                              │
│ Services used:                                                               │
│   - S3 (vqms-knowledge-artifacts-prod): Load resolution prompt template      │
│   - Amazon Bedrock (Claude Sonnet 3.5): Generate RESOLUTION draft            │
│   - PostgreSQL (workflow.case_execution): Store draft                         │
│   - S3: Prompt snapshot for audit | Redis: Update state                      │
│   - EventBridge: DraftPrepared event                                         │
│                                                                              │
│ Output:  RESOLUTION email draft with concrete answer (dates, amounts)        │
│                                                                              │
│ Time: ~4 seconds | Cost: ~$0.021 | LLM: YES                                 │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 11A: QUALITY & GOVERNANCE GATE                                          │
│                                                                              │
│ Input:   DraftResponse (resolution) + TicketRecord + VendorProfile           │
│                                                                              │
│ What happens:                                                                │
│   PHASE 1: DETERMINISTIC CHECKS (no LLM)                                    │
│     [PASS] Ticket # format: INC0019847                                       │
│     [PASS] SLA wording: "4 hours" matches Silver/High policy                 │
│     [PASS] Required sections: greeting, status, timeline, next steps         │
│     [PASS] Restricted terms: 0 blocklist matches                             │
│     [PASS] Response length: 163 words (50-500 range)                         │
│     [PASS] Source citations: 2 KB articles cited                             │
│                                                                              │
│   PHASE 2: CONDITIONAL (priority = HIGH)                                     │
│     [PASS] PII scan: Rajesh's phone excluded from draft                      │
│     [SKIP] Tone check: no issues detected, LLM call skipped                 │
│                                                                              │
│   OVERALL: ██████████ 7/7 PASS ████████████                                  │
│                                                                              │
│ Services used:                                                               │
│   - QualityGateAgent: Rule-based validation                                  │
│   - Amazon Comprehend: PII detection                                         │
│   - S3 + PostgreSQL + EventBridge: Audit trail                               │
│                                                                              │
│ Output:  Validation PASSED — email approved for delivery                     │
│                                                                              │
│ Time: < 200ms | Cost: $0.00 | LLM: No                                       │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 12A: TICKET CREATED + RESOLUTION EMAIL SENT                             │
│                                                                              │
│ Input:   Validated resolution draft                                          │
│                                                                              │
│ What happens:                                                                │
│                                                                              │
│   1. TICKET CREATED IN SERVICENOW                                            │
│      - POST /api/now/table/incident -> INC0019847                            │
│      - Assigned to Finance Team (they MONITOR, not investigate)              │
│      - The ticket is a safety net — Finance Team steps in only if            │
│        Rajesh replies with a follow-up the AI cannot handle                  │
│                                                                              │
│   2. RESOLUTION EMAIL SENT TO RAJESH                                         │
│      - MS Graph API /sendMail                                                │
│      - To: rajesh.mehta@technovasolutions.in                                 │
│      - Subject: RE: Payment Status Inquiry [INC0019847]                      │
│      - Body: FULL ANSWER with payment timeline, ticket#, SLA                 │
│                                                                              │
│   3. STATUS UPDATES                                                          │
│      - PostgreSQL: status = RESPONDED | Redis: workflow = COMPLETE            │
│      - Audit log: EMAIL_SENT | EventBridge: TicketCreated + EmailSent        │
│                                                                              │
│ Output:  Rajesh gets his FULL ANSWER. Finance Team monitors ticket.          │
│          Query status: RESPONDED                                             │
│                                                                              │
│ Time: ~2.5 seconds | Cost: $0.00 | LLM: No                                  │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
                           (Continues to Step 13: SLA Monitor)
                           (Then to Step 16: Closure / Reopen)


═══════════════════════════════════════════════════════════════════════════════
PATH B: HUMAN-TEAM-RESOLVED FLOW (KB does NOT have the answer)
═══════════════════════════════════════════════════════════════════════════════

┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 10B: COMMUNICATION DRAFTING AGENT — ACKNOWLEDGMENT ONLY                 │
│                                                                              │
│ Input:   AnalysisResult + VendorProfile + SLA (4h)                           │
│          KB articles do NOT contain enough info to give a specific answer     │
│                                                                              │
│ What happens:                                                                │
│   The AI knows WHAT Rajesh is asking (PAYMENT_QUERY) but does NOT have       │
│   the specific facts to answer it. So it writes an ACKNOWLEDGMENT only:      │
│                                                                              │
│     "Dear Rajesh,                                                            │
│      We have received your query regarding Invoice #INV-2026-0451            │
│      (PO-HEX-78412, Rs.4,75,000).                                           │
│                                                                              │
│      Your ticket number is INC0019847.                                       │
│      This has been assigned to our Finance Team for review.                  │
│      You will receive a detailed response within 4 hours.                    │
│                                                                              │
│      Thank you for your patience.                                            │
│      VQMS Finance Support"                                                   │
│                                                                              │
│   ★ NOTICE: NO dates, NO payment timeline, NO resolution.                   │
│     Just: "We got it, here is your ticket, someone will help you."           │
│                                                                              │
│ Services used:                                                               │
│   - Amazon Bedrock (Claude Sonnet 3.5): Generate ACKNOWLEDGMENT draft        │
│     (uses acknowledgment template, NOT resolution template)                  │
│   - S3: Load acknowledgment prompt template + store snapshot                 │
│   - PostgreSQL + Redis + EventBridge: Status updates and audit               │
│                                                                              │
│ Output:  ACKNOWLEDGMENT email draft (no answer, just confirmation)           │
│                                                                              │
│ Time: ~3 seconds | Cost: ~$0.015 | LLM: YES                                 │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 11B: QUALITY & GOVERNANCE GATE (same 7 checks)                          │
│                                                                              │
│ Input:   Acknowledgment draft                                                │
│                                                                              │
│ What happens:   Same 7 safety checks as Path A:                              │
│   [PASS] Ticket # correct | [PASS] SLA wording | [PASS] Sections present    │
│   [PASS] No restricted terms | [PASS] Length OK | [PASS] PII clean           │
│                                                                              │
│ Output:  Validation PASSED — acknowledgment approved for delivery            │
│                                                                              │
│ Time: < 200ms | Cost: $0.00 | LLM: No                                       │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 12B: TICKET CREATED + ACKNOWLEDGMENT SENT                               │
│                                                                              │
│ Input:   Validated acknowledgment draft                                      │
│                                                                              │
│ What happens:                                                                │
│                                                                              │
│   1. TICKET CREATED IN SERVICENOW                                            │
│      - POST /api/now/table/incident -> INC0019847                            │
│      - Assigned to Finance Team (they MUST investigate this one)             │
│      - Ticket includes: AI analysis, vendor profile, urgency, SLA            │
│                                                                              │
│   2. ACKNOWLEDGMENT EMAIL SENT TO RAJESH                                     │
│      - "We received your query. Ticket: INC0019847. Finance Team             │
│        is reviewing. Response within 4 hours."                               │
│      - This is NOT the answer — just a confirmation of receipt               │
│                                                                              │
│   3. SLA CLOCK STARTS (4 hours for Finance Team to respond)                  │
│                                                                              │
│ Output:  Rajesh gets acknowledgment. Finance Team gets the ticket.           │
│          Query status: ACKNOWLEDGED (not RESPONDED yet)                      │
│                                                                              │
│ Time: ~2.5 seconds | Cost: $0.00 | LLM: No                                  │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 13B: SLA MONITOR STARTS (same as Path A, but more critical here)        │
│                                                                              │
│ What happens:   Timer is watching the 4-hour deadline.                       │
│   In Path B this actually matters because the Finance Team needs time.       │
│     70% (2h 48m): Warn assigned resolver                                     │
│     85% (3h 24m): Escalate to L1 manager                                     │
│     95% (3h 48m): Escalate to L2 senior leadership                           │
│                                                                              │
│ Output:  SLA actively monitored while Finance Team works                     │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ ★ STEP 14: HUMAN TEAM INVESTIGATES (Finance Team does the real work)         │
│                                                                              │
│ Input:   ServiceNow ticket INC0019847 in Finance Team's queue                │
│          Contains: AI analysis, vendor profile, extracted entities,           │
│          urgency level, SLA deadline, vendor history                          │
│                                                                              │
│ What happens:                                                                │
│   The Finance Team member opens the ticket and sees everything the AI        │
│   already figured out (intent, entities, urgency). They don't start          │
│   from scratch — the AI has done the triage work for them.                   │
│                                                                              │
│   The human then does what the AI could NOT do:                              │
│     - Logs into the internal payment system                                  │
│     - Looks up Invoice #INV-2026-0451                                        │
│     - Checks: Was it approved? Why is it delayed?                            │
│     - Finds: "3-way match passed Feb 28. Scheduled for April 5               │
│       payment run. Credit expected by April 10."                             │
│     - Adds resolution notes to the ServiceNow ticket                         │
│     - Marks ticket as RESOLVED in ServiceNow                                 │
│                                                                              │
│   ★ THIS is where the REAL INFORMATION comes from.                           │
│     The AI could NOT have done this — it needed a human to look up           │
│     Rajesh's specific invoice in the payment system.                         │
│                                                                              │
│ Services used:                                                               │
│   - ServiceNow ITSM: Finance Team views ticket, adds work notes,            │
│     updates status to RESOLVED with resolution summary                       │
│   - Internal payment system (outside VQMS): Finance Team looks up            │
│     invoice status — this is the source of the real answer                   │
│   - EventBridge: ResolutionPrepared event published when ticket              │
│     is marked RESOLVED — this triggers the next step automatically           │
│                                                                              │
│ Output:  Resolution notes added to ticket by Finance Team:                   │
│          "Invoice passed 3-way match Feb 28. Payment scheduled April 5.      │
│           Expected credit by April 10."                                      │
│          Ticket status: RESOLVED                                             │
│                                                                              │
│ Time: Minutes to hours (depends on complexity) | Cost: $0.00 | LLM: No      │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ ★ STEP 15: AI DRAFTS RESOLUTION EMAIL (using Finance Team's findings)        │
│                                                                              │
│ Input:   Finance Team's resolution notes from ServiceNow ticket +            │
│          Original query context + Vendor profile + SLA                       │
│                                                                              │
│ What happens:                                                                │
│   NOW the AI has real information to work with. The Finance Team found       │
│   the answer, and the AI takes their notes and writes a professional         │
│   email for the vendor:                                                      │
│                                                                              │
│   1. ResolutionPrepared event triggers Communication Drafting Agent           │
│   2. AI reads Finance Team's resolution notes from ServiceNow                │
│   3. AI drafts a polished resolution email:                                  │
│        "Dear Rajesh,                                                         │
│         Our Finance Team has reviewed your inquiry regarding                  │
│         Invoice #INV-2026-0451. The invoice passed three-way                 │
│         match on Feb 28. Payment is approved and scheduled for               │
│         April 5. Expected credit by April 10..."                             │
│   4. Quality Gate runs all 7 checks again (same as Step 11)                  │
│   5. Validated email sent to Rajesh via MS Graph API                         │
│   6. Ticket status moves to PENDING_CLOSURE                                  │
│                                                                              │
│   The AI's role here: turn the Finance Team's raw notes into a               │
│   professional, vendor-friendly email. The AI adds: proper greeting,         │
│   ticket reference, SLA statement, next steps, signature.                    │
│                                                                              │
│ Services used:                                                               │
│   - EventBridge: ResolutionPrepared event triggers this step                 │
│   - ServiceNow API: Read resolution notes from ticket                        │
│   - Amazon Bedrock (Claude Sonnet 3.5): Draft resolution email using         │
│     Finance Team's notes + original context + vendor profile                 │
│   - QualityGateAgent + Amazon Comprehend: Validate draft (7 checks + PII)   │
│   - Microsoft Graph API: Send resolution email to Rajesh                     │
│   - PostgreSQL + Redis + S3 + EventBridge: Status updates, audit trail       │
│                                                                              │
│ Output:  Professional resolution email sent to Rajesh                        │
│          Ticket status: PENDING_CLOSURE                                      │
│                                                                              │
│ Time: ~10 seconds (same AI pipeline) | Cost: ~$0.021 | LLM: YES             │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
                              (Continues to Step 16: Closure / Reopen)


═══════════════════════════════════════════════════════════════════════════════
BOTH PATHS CONVERGE HERE
═══════════════════════════════════════════════════════════════════════════════

┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 13: SLA MONITORING — BACKGROUND PROCESS (runs alongside both paths)     │
│                                                                              │
│ Input:   TicketCreated event from Step 12A or 12B                            │
│                                                                              │
│ What happens:                                                                │
│   SLA: 4 hours (Silver tier + High priority)                                 │
│   Created: 08:14:00 | Deadline: 12:14:00                                     │
│   70% mark: 11:02 -> SLAWarning70 -> notify resolver                        │
│   85% mark: 11:38 -> SLAEscalation85 -> L1 manager via escalation queue     │
│   95% mark: 12:02 -> SLAEscalation95 -> L2 senior management                │
│                                                                              │
│   PATH A: Resolved in ~11 seconds -> breach=false, no escalations            │
│   PATH B: Finance Team has up to 4 hours; escalations kick in if slow        │
│   PATH C: SLA clock starts AFTER human reviewer finishes. Review time        │
│           does NOT count against SLA. Then follows PATH A or B.              │
│                                                                              │
│ Services used:                                                               │
│   - AWS Step Functions (vqms-sla-monitor): Wait-state based timer            │
│   - Redis (vqms:sla:<ticket-id>): SLA state tracking                        │
│   - EventBridge: SLA warning/escalation events                               │
│   - SQS (vqms-escalation-queue): Delivers alerts to managers                 │
│   - PostgreSQL (reporting.sla_metrics): SLA performance data                 │
│                                                                              │
│ Output:  SLA tracked and recorded for reporting                              │
│                                                                              │
│ Time: Runs in background | Cost: $0.00 | LLM: No                            │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 16: CLOSURE OR REOPEN                                                   │
│                                                                              │
│ Input:   Resolution email has been sent to Rajesh (from either path)         │
│          Ticket status: PENDING_CLOSURE                                      │
│                                                                              │
│ What happens — three possible outcomes:                                      │
│                                                                              │
│   OUTCOME A — Rajesh replies "Thank you" (confirmation):                     │
│     - Email Ingestion Service detects reply                                  │
│     - QueryAnalysisAgent classifies intent as CONFIRMATION                   │
│     - Ticket CLOSED in ServiceNow                                            │
│     - SLA Monitor stops | TicketClosed event published                       │
│     - Closure summary saved to memory.episodic_memory (for future queries)   │
│     - Audit trail finalized                                                  │
│                                                                              │
│   OUTCOME B — Rajesh doesn't reply for 5 business days:                      │
│     - Step Functions wait state expires after 5 days                          │
│     - Policy-based auto-closure triggers                                     │
│     - Ticket CLOSED in ServiceNow (same as Outcome A after this)             │
│                                                                              │
│   OUTCOME C — Rajesh replies "Problem is back" or new issue:                 │
│     - Email Ingestion parses reply, thread correlation finds CLOSED ticket    │
│     - QueryAnalysisAgent analyzes the new email                              │
│     - LangGraph decision node evaluates:                                     │
│       * Same issue → REOPEN existing ticket, SLA restarts                    │
│       * New issue  → CREATE new linked ticket, fresh SLA                     │
│     - Flow re-enters from Step 8 (AI analysis) with updated context          │
│                                                                              │
│ Services used:                                                               │
│   - Email Ingestion Service + MS Graph API: Detect vendor reply              │
│   - QueryAnalysisAgent (Bedrock): Classify reply intent                      │
│   - LangGraph: Reopen vs new-linked-ticket decision                          │
│   - ServiceNow: Close or reopen ticket                                       │
│   - Step Functions: Wait state for auto-closure timeout                      │
│   - PostgreSQL (memory.episodic_memory): Store closure summary               │
│   - EventBridge: TicketClosed or TicketReopened event                        │
│                                                                              │
│ Output:  Ticket CLOSED (done) or REOPENED (flow restarts from Step 8)        │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║ DONE — COMPLETE                                                              ║
║                                                                              ║
║ PATH A SUMMARY (AI-Resolved — Rajesh's actual case):                        ║
║   Rajesh waited: ~0.4 seconds | Pipeline: ~11 seconds | Cost: ~$0.033       ║
║   Human involvement: ZERO | SLA breached: No                                ║
║                                                                              ║
║ PATH B SUMMARY (Human-Team-Resolved):                                       ║
║   Rajesh waited: ~0.4 seconds (got query ID + acknowledgment in ~12 sec)    ║
║   Finance Team works: minutes to hours | AI drafts final email: ~10 sec      ║
║   Human involvement: YES (Finance Team investigates) | SLA: depends         ║
║                                                                              ║
║ PATH C SUMMARY (Low-Confidence → Human Review → Resume):                    ║
║   Rajesh waited: ~0.4 seconds (got query ID)                                ║
║   Workflow PAUSES — no email, no ticket until human reviewer acts            ║
║   Reviewer corrects: intent, vendor, routing (minutes to hours)              ║
║   Workflow RESUMES with corrected data → then follows PATH A or PATH B      ║
║   Human involvement: YES (reviewer first, then possibly team)                ║
║                                                                              ║
║ WRITES (all paths): PostgreSQL(12+), Redis(9+), S3(3+), ServiceNow(1+),    ║
║   MS Graph(1+), Bedrock(2-3), Comprehend(1+), EventBridge(7+), SQS(1+)     ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

---

# ══════════════════════════════════════════════════════════════════
# OUTPUT 2: SIMPLE MANAGER-FRIENDLY ASCII FLOW (Updated with Both Paths)
# ══════════════════════════════════════════════════════════════════

```
╔══════════════════════════════════════════════════════════════════╗
║  VQMS — HOW A VENDOR QUERY GETS HANDLED                        ║
║  (Simple Business View — All Three Paths)                       ║
║                                                                  ║
║  Example: Rajesh from TechNova asks about a late payment.       ║
╚══════════════════════════════════════════════════════════════════╝


┌──────────────────────────────────────────────────────────────────┐
│  STEP 1: VENDOR LOGS IN                                          │
│                                                                  │
│  What comes in:  Rajesh opens the VQMS portal and signs in.     │
│                                                                  │
│  What happens:   System checks his identity and creates a        │
│                  secure session. Rajesh can only see his own      │
│                  company's data — never another vendor's.         │
│                                                                  │
│  What goes out:  Rajesh is logged in (valid for 8 hours).       │
│                                                                  │
│  Time: Less than 1 second                                        │
└──────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│  STEP 2: RAJESH SEES HIS DASHBOARD                               │
│                                                                  │
│  What comes in:  Rajesh's login session.                         │
│                                                                  │
│  What happens:   Portal shows his personalized dashboard:        │
│                    - 3 open queries, 11 resolved, 3.1h avg       │
│                    - His 4 most recent queries                    │
│                                                                  │
│  What goes out:  Rajesh clicks "+ New Query" to start.           │
│                                                                  │
│  Time: Under half a second                                       │
└──────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│  STEPS 3-5: RAJESH FILLS IN HIS QUERY (3-step wizard)            │
│                                                                  │
│  What comes in:  Empty form.                                     │
│                                                                  │
│  What happens:   3-step wizard in the browser:                   │
│    Step 3: Picks "Invoice Issue"                                 │
│    Step 4: Fills in subject, description, priority (High),       │
│            reference number (PO-HEX-78412)                       │
│    Step 5: Reviews and clicks "Submit Query"                     │
│                                                                  │
│  Important: Nothing is sent to the server until Submit.          │
│                                                                  │
│  What goes out:  Rajesh clicks "Submit Query."                   │
└──────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│  STEP 6: QUERY IS RECEIVED AND LOGGED                            │
│                                                                  │
│  What comes in:  Rajesh's complete query.                        │
│                                                                  │
│  What happens:   In about half a second, the system:             │
│    - Validates the data                                          │
│    - Assigns tracking number: VQ-2026-0108                       │
│    - Checks for duplicates                                       │
│    - Saves to database                                           │
│    - Starts the AI pipeline in the background                    │
│                                                                  │
│  What goes out:  Rajesh sees "VQ-2026-0108" on screen.           │
│                                                                  │
│  ═══════════════════════════════════════════════════              │
│  ★ Rajesh waited ~0.4 seconds. He's done.                        │
│    Everything below happens automatically.                       │
│  ═══════════════════════════════════════════════════              │
└──────────────────────────────────────────────────────────────────┘
                               │
         EVERYTHING BELOW RUNS AUTOMATICALLY IN BACKGROUND
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│  STEP 7: SYSTEM LOADS CONTEXT ABOUT THE VENDOR                   │
│                                                                  │
│  What comes in:  The query from the queue.                       │
│                                                                  │
│  What happens:   System gathers background info:                 │
│    - From Salesforce: TechNova, Silver tier, payment history     │
│    - From memory: 3 prior queries in 90 days                     │
│                                                                  │
│  What goes out:  Full vendor context ready for AI.               │
│                                                                  │
│  Time: Less than 1 second                                        │
└──────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│  STEP 8: AI READS AND UNDERSTANDS THE QUERY                      │
│                                                                  │
│  What comes in:  Rajesh's query + vendor context.                │
│                                                                  │
│  What happens:   AI figures out:                                 │
│    - What: PAYMENT_QUERY (asking where money is)                 │
│    - Urgency: HIGH (16 days overdue)                             │
│    - Confidence: 96% (very clear query)                          │
│                                                                  │
│  What goes out:  Clear understanding of the problem.             │
│                                                                  │
│  Time: ~3 seconds | Cost: ~1.2 cents                             │
└──────────────────────────────────────────────────────────────────┘
                               │
                               ▼
╔══════════════════════════════════════════════════════════════════╗
║                                                                  ║
║  ★ FIRST QUESTION: Is the AI confident enough to proceed?        ║
║                                                                  ║
║    Think of it like a doctor:                                    ║
║    - If the doctor is 96% sure → prescribes treatment (proceed)  ║
║    - If the doctor is only 62% sure → orders more tests          ║
║      (sends to human reviewer first)                             ║
║                                                                  ║
║    AI confidence >= 85%  → Continue to Step 9                    ║
║                            ★ Rajesh's case: 96% → goes here     ║
║                                                                  ║
║    AI confidence < 85%   → PATH C: Human reviews first           ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
              │                                  │
     confidence >= 85%                  confidence < 85%
     (Rajesh's case)                     (PATH C)
              │                                  │
              │                                  ▼
              │
              │    ════════════════════════════════════════
              │    PATH C: AI IS NOT SURE — HUMAN REVIEWS
              │    ════════════════════════════════════════
              │
              │    Example: Vendor writes a vague email saying
              │    "I have some concerns about our account."
              │    AI can't tell: Is this about payment? Contract?
              │    Delivery? It's only 62% confident.
              │
              │    ┌──────────────────────────────────────────────┐
              │    │  STEP 8C: HUMAN REVIEWER CHECKS THE AI's     │
              │    │  WORK BEFORE ANYTHING HAPPENS                 │
              │    │                                                │
              │    │  What happens:                                 │
              │    │                                                │
              │    │  1. SYSTEM PAUSES everything.                  │
              │    │     No email goes out. No ticket created.      │
              │    │     Nothing happens until a human looks at it. │
              │    │                                                │
              │    │  2. A TRIAGE PACKAGE is sent to the            │
              │    │     human review portal showing:               │
              │    │     - The vendor's original query              │
              │    │     - AI's best guess (but uncertain)          │
              │    │     - Suggested routing and draft               │
              │    │     - Why the AI is unsure                      │
              │    │                                                │
              │    │  3. A HUMAN REVIEWER opens the portal,         │
              │    │     reads the query, and fixes the AI:         │
              │    │     - "This is actually a PAYMENT_QUERY"       │
              │    │     - "This vendor is TechNova (VN-30892)"     │
              │    │     - "Route to Finance Team"                   │
              │    │                                                │
              │    │  4. Reviewer clicks SUBMIT.                    │
              │    │     System RESUMES with the corrected data.    │
              │    │     Flow continues to Step 9 as normal.        │
              │    │                                                │
              │    │  WHY THIS MATTERS:                             │
              │    │    The system NEVER sends a wrong response     │
              │    │    to a vendor. If the AI is unsure, it asks   │
              │    │    a human first. Better to be slow and right  │
              │    │    than fast and wrong.                         │
              │    │                                                │
              │    │  Time: Minutes to hours (waiting for reviewer) │
              │    └──────────────────────────────────────────────┘
              │                                  │
              │     PATH C rejoins here           │
              │              ┌────────────────────┘
              │              │
              ▼              ▼
┌──────────────────────────────────────────────────────────────────┐
│  STEP 9: ROUTING + KNOWLEDGE SEARCH (parallel)                   │
│                                                                  │
│  What comes in:  AI's analysis.                                  │
│                                                                  │
│  What happens:                                                   │
│    ROUTING: Finance Team, 4-hour SLA, full automation OK         │
│    KB SEARCH: Found 4 relevant articles (96%, 89%, 82%, 71%)    │
│                                                                  │
│  What goes out:  Routing decision + knowledge articles.          │
│                                                                  │
│  Time: Under 0.2 seconds                                         │
└──────────────────────────────────────────────────────────────────┘
                               │
                               ▼
╔══════════════════════════════════════════════════════════════════╗
║                                                                  ║
║  ★ SECOND QUESTION: Does the AI have enough information to       ║
║    give Rajesh a real answer right now?                           ║
║                                                                  ║
║    (We only get here if AI was confident enough — PATH C         ║
║     queries already went to a human reviewer above)              ║
║                                                                  ║
║    The system checks: Do the knowledge base articles contain     ║
║    specific facts (dates, amounts, procedures) that answer       ║
║    Rajesh's question?                                            ║
║                                                                  ║
║    YES → PATH A: AI sends the FULL ANSWER now                    ║
║    NO  → PATH B: AI sends "we got your query" and the           ║
║                  human team finds the answer first                ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
                     │                           │
            ┌────────┘                           └────────┐
            │                                             │
            ▼                                             ▼

════════════════════════════         ════════════════════════════
PATH A: AI HAS THE ANSWER            PATH B: AI NEEDS HUMAN HELP
(answer exists in KB)                 (specific info not in KB)
════════════════════════════         ════════════════════════════

Example:                              Example:
"When is my payment?"                 "Why was my payment rejected?"
→ KB has payment cycle dates          → AI doesn't know why, needs
                                        someone to check the system
★ Rajesh's case follows
  this path ★


PATH A CONTINUES:                     PATH B CONTINUES:
─────────────────                     ─────────────────

┌──────────────────────────┐          ┌──────────────────────────┐
│ STEP 10A:                │          │ STEP 10B:                │
│ AI WRITES FULL ANSWER    │          │ AI WRITES ACKNOWLEDGMENT │
│                          │          │ ONLY                     │
│ The AI found facts in    │          │                          │
│ the knowledge base:      │          │ AI sends:                │
│ - Payment cycle dates    │          │ "We received your query. │
│ - 3-way match policies   │          │  Ticket: INC0019847.     │
│ - Credit timelines       │          │  Finance Team will       │
│                          │          │  respond within 4 hours."│
│ So it writes a REAL      │          │                          │
│ answer:                  │          │ ★ NO answer yet.         │
│ "Payment scheduled       │          │   Just: we got it,       │
│  April 5, credit by      │          │   someone will help.     │
│  April 10."              │          │                          │
│                          │          │ Cost: ~1.5 cents         │
│ Cost: ~2.1 cents         │          └──────────────────────────┘
└──────────────────────────┘                     │
            │                                    ▼
            ▼                         ┌──────────────────────────┐
┌──────────────────────────┐          │ STEP 11B:                │
│ STEP 11A:                │          │ QUALITY CHECK            │
│ QUALITY CHECK            │          │ Same 7 safety checks     │
│ Same 7 safety checks     │          │ on the acknowledgment.   │
│ on the full answer.      │          └──────────────────────────┘
│ All pass.                │                     │
└──────────────────────────┘                     ▼
            │                         ┌──────────────────────────┐
            ▼                         │ STEP 12B:                │
┌──────────────────────────┐          │ TICKET CREATED +         │
│ STEP 12A:                │          │ ACKNOWLEDGMENT SENT      │
│ TICKET CREATED +         │          │                          │
│ FULL ANSWER SENT         │          │ 1. ServiceNow ticket     │
│                          │          │    INC0019847 created     │
│ 1. ServiceNow ticket     │          │    → Finance Team MUST   │
│    INC0019847 created    │          │      investigate          │
│    → Finance Team just   │          │                          │
│      monitors            │          │ 2. Acknowledgment email   │
│                          │          │    sent to Rajesh         │
│ 2. Resolution email      │          │    (NOT the answer)      │
│    sent to Rajesh        │          │                          │
│    (WITH the answer)     │          │ 3. SLA clock starts      │
│                          │          │    (4 hours)              │
│ ★ Rajesh has his         │          │                          │
│   answer already!        │          │ ★ Rajesh knows we're     │
│                          │          │   working on it.          │
│ Time: ~2.5 seconds       │          │                          │
└──────────────────────────┘          │ Time: ~2.5 seconds       │
            │                         └──────────────────────────┘
            │                                    │
            │                                    ▼
            │                         ┌──────────────────────────┐
            │                         │ ★ STEP 14:               │
            │                         │ FINANCE TEAM             │
            │                         │ INVESTIGATES             │
            │                         │                          │
            │                         │ Finance Team member:     │
            │                         │ - Opens ticket in        │
            │                         │   ServiceNow             │
            │                         │ - Sees AI's analysis     │
            │                         │   (doesn't start from    │
            │                         │   scratch)               │
            │                         │ - Looks up the invoice   │
            │                         │   in payment system      │
            │                         │ - Finds the answer:      │
            │                         │   "Payment scheduled     │
            │                         │    April 5, credit       │
            │                         │    by April 10"          │
            │                         │ - Adds notes to ticket   │
            │                         │ - Marks as RESOLVED      │
            │                         │                          │
            │                         │ ★ THIS is where the      │
            │                         │   real info comes from.  │
            │                         │                          │
            │                         │ Time: Minutes to hours   │
            │                         └──────────────────────────┘
            │                                    │
            │                                    ▼
            │                         ┌──────────────────────────┐
            │                         │ ★ STEP 15:               │
            │                         │ AI DRAFTS RESOLUTION     │
            │                         │ EMAIL (using Finance     │
            │                         │ Team's findings)         │
            │                         │                          │
            │                         │ NOW the AI has real      │
            │                         │ information. It takes    │
            │                         │ Finance Team's notes     │
            │                         │ and writes a polished    │
            │                         │ email to Rajesh:         │
            │                         │                          │
            │                         │ "Dear Rajesh,            │
            │                         │  Our Finance Team has    │
            │                         │  reviewed your inquiry.  │
            │                         │  Payment scheduled       │
            │                         │  April 5, credit by      │
            │                         │  April 10..."            │
            │                         │                          │
            │                         │ Quality Gate checks it   │
            │                         │ again → Email sent.      │
            │                         │                          │
            │                         │ Time: ~10 seconds        │
            │                         │ Cost: ~2.1 cents         │
            │                         └──────────────────────────┘
            │                                    │
            └──────────────┬─────────────────────┘
                           │
      BOTH PATHS MEET HERE │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  SLA MONITORING (runs in background the entire time)             │
│                                                                  │
│  PATH A: Resolved in ~11 seconds → no escalations needed         │
│  PATH B: Finance Team has up to 4 hours:                         │
│    At 70% (2h 48m): Warn the assigned person                     │
│    At 85% (3h 24m): Escalate to their manager                    │
│    At 95% (3h 48m): Escalate to senior leadership                │
│  PATH C: SLA clock starts AFTER human reviewer finishes.         │
│    The review time does NOT count against the SLA.               │
│    Once reviewer submits → SLA starts → then PATH A or B.        │
└──────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│  STEP 16: CLOSURE OR REOPEN                                      │
│                                                                  │
│  After Rajesh gets his answer (from either path), three          │
│  things can happen:                                              │
│                                                                  │
│  A. Rajesh replies "Thank you"                                   │
│     → Ticket closed. Done.                                       │
│                                                                  │
│  B. Rajesh doesn't reply for 5 business days                     │
│     → Ticket automatically closed.                               │
│                                                                  │
│  C. Rajesh replies "The problem is back"                         │
│     → Ticket reopens OR new linked ticket created                │
│     → Flow restarts from Step 8 (AI analysis)                    │
│     → SLA timer restarts                                         │
└──────────────────────────────────────────────────────────────────┘
                               │
                               ▼
╔══════════════════════════════════════════════════════════════════╗
║                                                                  ║
║   RESULT                                                         ║
║                                                                  ║
║   ┌─────────────────────────────────────────────────────┐       ║
║   │  PATH A (AI Resolved)         PATH B (Team Resolved)│       ║
║   │                                                     │       ║
║   │  Rajesh waited: 0.4s          Rajesh waited: 0.4s   │       ║
║   │  Got answer in: ~11 sec       Got ack in: ~12 sec    │       ║
║   │                               Got answer in: hours   │       ║
║   │  Cost: ~3.3 cents             Cost: ~5 cents         │       ║
║   │  Human work: ZERO             Human work: YES        │       ║
║   │  SLA breached: No             SLA: depends on team   │       ║
║   │                                                     │       ║
║   │  PATH C (Low Confidence → Human Review → Resume)    │       ║
║   │                                                     │       ║
║   │  Rajesh waited: 0.4s (got query ID)                 │       ║
║   │  Human review: minutes to hours (system paused)      │       ║
║   │  After review: continues as PATH A or PATH B        │       ║
║   │  Cost: ~3-5 cents (same as A or B after review)      │       ║
║   │  Human work: YES (reviewer first, then maybe team)   │       ║
║   │  SLA: starts after review completes                  │       ║
║   └─────────────────────────────────────────────────────┘       ║
║                                                                  ║
║   KEY TAKEAWAY:                                                  ║
║   The AI always handles the first response (ack or resolution). ║
║   The human team only gets involved when the AI doesn't have     ║
║   enough information to give a real answer.                      ║
║   If the AI is not even sure WHAT the vendor is asking,          ║
║   it pauses everything and asks a human to verify first          ║
║   (PATH C). The system NEVER sends a wrong answer.              ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
```
