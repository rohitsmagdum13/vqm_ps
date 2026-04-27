# VQMS Decision Paths — How the AI Pipeline Makes Decisions

A plain-English guide to every decision the VQMS pipeline makes,
from the moment a query arrives to the moment an email is sent.

---

## Table of Contents

1. [The Big Picture](#1-the-big-picture)
2. [Terminology](#2-terminology)
3. [Decision Point 1 — Confidence Gate](#3-decision-point-1--confidence-gate)
4. [Decision Point 2 — KB Match (Path A vs Path B)](#4-decision-point-2--kb-match-path-a-vs-path-b)
5. [SLA Calculation](#5-sla-calculation)
6. [Team Assignment (Routing)](#6-team-assignment-routing)
7. [Quality Gate — 7 Checks](#7-quality-gate--7-checks)
8. [Delivery Outcomes](#8-delivery-outcomes)
9. [Full Pipeline Flow](#9-full-pipeline-flow)
10. [Quick Reference Table](#10-quick-reference-table)

---

## 1. The Big Picture

Every vendor query (email or portal) goes through a pipeline of AI + rules.
The pipeline makes **two major decisions** that determine which "path" the query takes:

```
+------------------+     +------------------+     +------------------+
|   QUERY ARRIVES  | --> | DECISION POINT 1 | --> | DECISION POINT 2 |
|  (email/portal)  |     | Confidence Gate  |     | KB Match Quality |
+------------------+     +------------------+     +------------------+
                               |                        |       |
                               |                        |       |
                          Low confidence           Good KB   Poor KB
                          (< 0.85)                 match     match
                               |                    |         |
                               v                    v         v
                          +--------+          +--------+ +--------+
                          | PATH C |          | PATH A | | PATH B |
                          | Human  |          |   AI   | | Human  |
                          | Review |          |Resolves| | Invstg |
                          +--------+          +--------+ +--------+
```

**Three possible outcomes:**

| Path | What Happens | Human Involved? | Email Sent |
|------|-------------|-----------------|------------|
| **A** | AI finds the answer in KB and drafts a resolution email | No | Full answer |
| **B** | AI can't find the answer; drafts acknowledgment only | Yes (team investigates) | "We received it, team is on it" |
| **C** | AI is not confident in its own analysis | Yes (reviewer corrects) | Nothing until reviewer acts |

---

## 2. Terminology

| Term | What It Means |
|------|--------------|
| **Confidence Score** | A number between 0.0 and 1.0 that the AI assigns to its own analysis. Higher = more sure. |
| **KB (Knowledge Base)** | A database of pre-written articles with answers to common vendor questions. Stored as vectors in PostgreSQL (pgvector). |
| **Cosine Similarity** | A math formula that measures how "close" two pieces of text are in meaning. 1.0 = identical, 0.0 = completely unrelated. |
| **Vendor Tier** | The vendor's service level: PLATINUM > GOLD > SILVER > BRONZE. Higher tiers get faster SLAs. |
| **Urgency Level** | How urgent the query is: CRITICAL > HIGH > MEDIUM > LOW. Set by the AI during analysis. |
| **SLA** | Service Level Agreement — the maximum time (in hours) to respond to a query. |
| **Threshold** | A cutoff number. If a score is above the threshold, one thing happens. Below it, another. |
| **Processing Path** | Which route (A, B, or C) the query takes through the pipeline. |
| **Triage** | When a human reviewer looks at a low-confidence query to correct the AI's analysis. |
| **Quality Gate** | 7 automated checks every outbound email must pass before being sent. |

---

## 3. Decision Point 1 — Confidence Gate

**Where:** After the Query Analysis Agent (Step 8)
**Code:** `src/orchestration/nodes/confidence_check.py`
**Threshold:** `0.85` (configurable in `.env` as `AGENT_CONFIDENCE_THRESHOLD`)

### How the Confidence Score Is Calculated

The Query Analysis Agent (LLM Call #1) reads the vendor's query and returns
a JSON response. One of the fields is `confidence_score` — the AI's self-assessed
certainty about its own analysis. The AI considers:

- **Clarity of the query** — Is the vendor asking one clear question or a vague mess?
- **Entity extraction success** — Did it find invoice numbers, dates, PO numbers?
- **Intent match** — Does the query clearly map to one of the 12 VQMS query types?
- **Ambiguity** — Are there multiple possible interpretations?

The LLM returns a float between 0.0 and 1.0. This is NOT a probability —
it is the model's self-reported confidence in the structured output it produced.

### The Decision

```
                    +-------------------+
                    | CONFIDENCE SCORE  |
                    | from AI Analysis  |
                    +-------------------+
                            |
                   +--------+--------+
                   |                 |
              >= 0.85           < 0.85
                   |                 |
                   v                 v
        +------------------+  +------------------+
        |    CONTINUE      |  |     PATH C       |
        | to Routing + KB  |  | Workflow PAUSES   |
        | (may become A/B) |  | Human reviews     |
        +------------------+  +------------------+
```

### What Happens on Each Branch

**If confidence >= 0.85:** The pipeline continues. The query flows to
Routing (team assignment + SLA) and KB Search (vector similarity).
From there, Decision Point 2 picks Path A or Path B.

**If confidence < 0.85 (Path C):** The entire pipeline STOPS.
A TriagePackage is created with:
- The original query
- The AI's analysis (even though it's low confidence)
- Confidence breakdown
- Suggested routing and draft

This package goes to a human reviewer who corrects the analysis,
then the pipeline resumes with the corrected data.

### Examples

| Query | Confidence | Why | Path |
|-------|-----------|-----|------|
| "Invoice INV-2024-0891 payment is 15 days overdue" | 0.92 | Clear intent, specific invoice number | Continue |
| "We need to discuss several things about our account" | 0.68 | Vague, multiple possible intents | Path C |
| "Where is my shipment for PO-7823?" | 0.91 | Clear intent, specific PO number | Continue |
| "Something is wrong" | 0.45 | No useful information | Path C |

---

## 4. Decision Point 2 — KB Match (Path A vs Path B)

**Where:** After KB Search (Step 9B)
**Code:** `src/orchestration/nodes/path_decision.py`
**Threshold:** `0.80` cosine similarity (configurable as `KB_MATCH_THRESHOLD`)

This decision is ONLY reached if confidence >= 0.85 (Decision Point 1 passed).

### How KB Search Works

1. The query text is converted to a **vector** (list of 1024 numbers)
   using an embedding model (Titan Embed v2 or OpenAI fallback)
2. This vector is compared against all KB article vectors stored in
   PostgreSQL (`memory.embedding_index` table) using **cosine similarity**
3. Articles are ranked by similarity score (0.0 to 1.0)
4. The search is filtered by category to return relevant articles only
5. Top 5 matches are returned

### The Decision (Two Conditions Must Be Met)

```
                    +-------------------+
                    |  KB SEARCH RESULT |
                    | (top match score) |
                    +-------------------+
                            |
                +-----------+-----------+
                |                       |
         BOTH conditions          EITHER condition
           are TRUE:                 is FALSE:
                |                       |
      +-------------------+    +-------------------+
      | 1. Best match     |    | Insufficient KB   |
      |    score >= 0.80  |    | match for the AI  |
      | 2. Top article    |    | to draft a real   |
      |    has >= 100     |    | answer             |
      |    characters of  |    |                   |
      |    actual content |    |                   |
      +-------------------+    +-------------------+
                |                       |
                v                       v
        +------------------+   +------------------+
        |     PATH A       |   |     PATH B       |
        | AI drafts FULL   |   | AI drafts ACK    |
        | resolution email |   | only; human team |
        | with the answer  |   | investigates     |
        +------------------+   +------------------+
```

### The Two Conditions Explained

**Condition 1 — Similarity score >= 0.80:**
The KB article must be at least 80% semantically similar to the query.
This means the article is genuinely about the same topic.

**Condition 2 — Content length >= 100 characters:**
The KB article must have substantial content (not just a title or
one-liner). Short snippets are likely generic boilerplate, not
actionable information the AI can use to write a resolution.

### What Happens on Each Branch

**Path A (AI Resolves):**
- The Resolution Node (Step 10A) uses the KB articles to draft a
  full answer email with specific facts, citations, and next steps
- The email actually answers the vendor's question
- A ServiceNow ticket is created for **monitoring** (team watches, not investigates)
- Status: RESOLVED

**Path B (Human Team Investigates):**
- The Acknowledgment Node (Step 10B) drafts a "we received your query" email
- The email does NOT contain any answer — just confirmation + ticket number + SLA
- A ServiceNow ticket is created for **investigation** (team must find the answer)
- Status: AWAITING_RESOLUTION
- Later, when the team resolves the ticket, a second email is generated from their notes

### Examples

| Query | Best KB Score | Content Length | Path | Why |
|-------|--------------|----------------|------|-----|
| "What is your return policy for defective items?" | 0.89 | 450 chars | A | High match + substantial article about return policy |
| "Invoice INV-2024-0891 is 15 days overdue, where is my payment?" | 0.72 | 300 chars | B | KB has general invoice info but can't answer about specific payment |
| "How do I integrate with your API v3?" | 0.84 | 820 chars | A | Good match + detailed API integration guide in KB |
| "Our shipment of custom parts hasn't arrived" | 0.55 | 200 chars | B | KB has generic shipping info but score is too low |
| "What is your return policy?" | 0.91 | 50 chars | B | High score but content is too short (< 100 chars) |

---

## 5. SLA Calculation

**Where:** Routing Node (Step 9A)
**Code:** `src/orchestration/nodes/routing.py`
**Formula:** `SLA Hours = Base Hours (from tier) x Multiplier (from urgency)`

### Step 1 — Get Base Hours from Vendor Tier

```
+---------------------------------------------------+
|           VENDOR TIER -> BASE SLA HOURS            |
+---------------------------------------------------+
|  PLATINUM  |  GOLD  |  SILVER  |  BRONZE           |
|   4 hours  | 8 hours| 16 hours | 24 hours          |
+---------------------------------------------------+
     Fastest               ------>              Slowest
```

The vendor tier comes from their Salesforce profile. Higher-tier vendors
pay more and get faster response times.

### Step 2 — Apply Urgency Multiplier

The urgency level is determined by the Query Analysis Agent (LLM).
Each urgency level has a multiplier:

```
+---------------------------------------------------+
|         URGENCY LEVEL -> MULTIPLIER                |
+---------------------------------------------------+
|  CRITICAL  |   HIGH   |  MEDIUM  |   LOW           |
|   x 0.25   |  x 0.50  |  x 1.00  |  x 1.50        |
+---------------------------------------------------+
    Fastest                ------>              Slowest
```

### Step 3 — Calculate Final SLA

```
Final SLA = max(1, floor(Base Hours x Multiplier))
```

The `max(1, ...)` ensures the SLA is never less than 1 hour.

### Full SLA Matrix (Tier x Urgency)

```
+------------------------------------------------------+
|              SLA HOURS = Tier x Urgency               |
+------------------------------------------------------+
|              | CRITICAL | HIGH | MEDIUM | LOW         |
|              | (x0.25)  |(x0.5)| (x1.0) | (x1.5)    |
+--------------+----------+------+--------+-------------|
| PLATINUM (4h)|    1h    |  2h  |   4h   |   6h       |
| GOLD     (8h)|    2h    |  4h  |   8h   |  12h       |
| SILVER  (16h)|    4h    |  8h  |  16h   |  24h       |
| BRONZE  (24h)|    6h    | 12h  |  24h   |  36h       |
+--------------+----------+------+--------+-------------+
```

**Example:**
- SteelCraft Industries is a GOLD tier vendor
- Their query is flagged as HIGH urgency
- SLA = 8 hours (GOLD) x 0.50 (HIGH) = **4 hours**

### SLA Escalation Thresholds

Once the SLA is set, the system monitors progress at three checkpoints:

```
+-----+----------+----------+----------+----------+-----+
| 0%  |          |   70%    |   85%    |   95%    | 100%|
|     |          | WARNING  |  L1 ESC  |  L2 ESC  | SLA |
| SLA |          |  alert   | escalate | escalate |BLOWN|
|START|          |  sent    | to mgr   | to dir   |     |
+-----+----------+----------+----------+----------+-----+

         TIME PASSING ---->
```

| Checkpoint | % of SLA Used | What Happens |
|-----------|--------------|-------------|
| Warning | 70% | Alert sent to the assigned team |
| L1 Escalation | 85% | Escalated to team manager |
| L2 Escalation | 95% | Escalated to director level |
| SLA Breach | 100% | SLA breached, incident logged |

**Example (4-hour SLA):**
- Warning at 70%: after 2h 48m
- L1 at 85%: after 3h 24m
- L2 at 95%: after 3h 48m
- Breach at 100%: after 4h 0m

### Path C SLA Exception

For Path C queries, the SLA timer does NOT start until the human
reviewer completes their review. Review time is excluded from the SLA.

```
+----------+    +----------+    +----------+    +----------+
|  Query   | -> | Path C   | -> | Reviewer | -> | SLA      |
|  arrives |    | detected |    | corrects |    | starts   |
+----------+    +----------+    +----------+    +----------+
                |<-- NO SLA -->|                 |<-- SLA ->|
                 review time                      counts
                 excluded                         from here
```

---

## 6. Team Assignment (Routing)

**Where:** Routing Node (Step 9A)
**Code:** `src/orchestration/nodes/routing.py`

The routing node assigns a team based on the query category. It uses
a two-level lookup:

### Level 1 — Official Query Type (Exact Match)

If the AI classifies the query as one of the 12 official VQMS types:

```
+------------------------------------------------------+
|            QUERY TYPE -> ASSIGNED TEAM                |
+------------------------------------------------------+
| INVOICE_PAYMENT     --> finance-ops                   |
| RETURN_REFUND       --> finance-ops                   |
| DELIVERY_SHIPMENT   --> supply-chain                  |
| CONTRACT_QUERY      --> legal-compliance              |
| COMPLIANCE_AUDIT    --> legal-compliance              |
| TECHNICAL_SUPPORT   --> tech-support                  |
| CATALOG_PRICING     --> procurement                   |
| PURCHASE_ORDER      --> procurement                   |
| ONBOARDING          --> vendor-management             |
| QUALITY_ISSUE       --> quality-assurance             |
| SLA_BREACH_REPORT   --> sla-compliance                |
| GENERAL_INQUIRY     --> general-support               |
+------------------------------------------------------+
```

### Level 2 — Category Keyword (Fallback)

If the AI returns a free-text category instead of an official type,
the routing node matches keywords:

```
+------------------------------------------------------+
|           KEYWORD -> FALLBACK TEAM                    |
+------------------------------------------------------+
| billing, invoice, payment,    --> finance-ops         |
| return, refund                                        |
|                                                       |
| delivery, shipping,           --> supply-chain        |
| logistics, shipment                                   |
|                                                       |
| contract, agreement, terms,   --> legal-compliance    |
| legal, compliance, audit                              |
|                                                       |
| technical, integration,       --> tech-support        |
| api, product                                          |
|                                                       |
| catalog, pricing, purchase    --> procurement         |
|                                                       |
| onboarding                    --> vendor-management   |
| quality, defect               --> quality-assurance   |
| sla                           --> sla-compliance      |
|                                                       |
| (no keyword match)            --> general-support     |
+------------------------------------------------------+
```

---

## 7. Quality Gate — 7 Checks

**Where:** Quality Gate Node (Step 11)
**Code:** `src/orchestration/nodes/quality_gate.py`

Every email draft (Path A resolution OR Path B acknowledgment) must pass
ALL 7 checks before it can be sent to the vendor.

```
+------------------------------------------------------------------+
|                     QUALITY GATE (7 CHECKS)                       |
+------------------------------------------------------------------+
|                                                                    |
|  +-------------------+  +-------------------+  +-----------------+ |
|  | 1. TICKET NUMBER  |  | 2. SLA WORDING    |  | 3. SECTIONS    | |
|  | "PENDING" or      |  | Contains SLA-     |  | Has greeting,  | |
|  | "INC-XXXXXXX"     |  | related words     |  | next steps,    | |
|  | must be present   |  | (prioritizing,    |  | and closing    | |
|  |                   |  |  expect, etc.)    |  |                | |
|  +-------------------+  +-------------------+  +-----------------+ |
|                                                                    |
|  +-------------------+  +-------------------+  +-----------------+ |
|  | 4. RESTRICTED     |  | 5. WORD COUNT     |  | 6. CITATIONS   | |
|  | No internal       |  | Between 50 and    |  | KB article IDs | |
|  | jargon: "jira",   |  | 500 words         |  | referenced     | |
|  | "sprint", "hack", |  | (not too short,   |  | (Path A only)  | |
|  | "TODO", etc.      |  |  not too long)    |  |                | |
|  +-------------------+  +-------------------+  +-----------------+ |
|                                                                    |
|  +-------------------+                                             |
|  | 7. PII SCAN       |                                             |
|  | No SSN patterns   |                                             |
|  | No credit card    |                                             |
|  | numbers           |                                             |
|  +-------------------+                                             |
|                                                                    |
+------------------------------------------------------------------+
         |                                    |
    ALL 7 PASS                          ANY CHECK FAILS
         |                                    |
         v                                    v
+------------------+               +-------------------+
| Status:          |               | Status:           |
| DELIVERING       |               | DRAFT_REJECTED    |
| (proceed to      |               | (re-draft up to   |
|  Step 12)        |               |  2 times, then    |
+------------------+               |  human review)    |
                                   +-------------------+
```

### Check Details

| # | Check Name | What It Looks For | Fails When |
|---|-----------|-------------------|------------|
| 1 | Ticket Number | "PENDING" or "INC-XXXXXXX" pattern | Neither found in body |
| 2 | SLA Wording | Keywords: "prioritizing", "priority", "expect", "being processed", etc. | No SLA-related language found |
| 3 | Required Sections | Greeting ("Dear", "Hello"), next steps ("please", "if you"), closing ("Regards", "Thank you") | Any section missing |
| 4 | Restricted Terms | Scans for 13 banned words: "jira", "slack channel", "sprint", "TODO", "hack", etc. | Any restricted term found |
| 5 | Word Count | Counts words in the body | Below 50 or above 500 |
| 6 | Source Citations | Checks for KB article references (Path A only) | Path A draft has no sources |
| 7 | PII Scan | SSN pattern (XXX-XX-XXXX), credit card (16 digits) | Pattern detected in body |

### What Happens When Checks Fail

```
+------------------+     +------------------+     +------------------+
|   Draft fails    | --> | Re-draft attempt | --> | Re-draft attempt |
|   quality gate   |     |    #1            |     |    #2 (final)    |
+------------------+     +------------------+     +------------------+
                                                          |
                                                   Still fails?
                                                          |
                                                          v
                                                 +------------------+
                                                 | Route to HUMAN   |
                                                 | REVIEW — AI gave |
                                                 | up after 2 tries |
                                                 +------------------+
```

---

## 8. Delivery Outcomes

**Where:** Delivery Node (Step 12)
**Code:** `src/orchestration/nodes/delivery.py`

After the Quality Gate passes, delivery handles two things:
1. Create a ServiceNow ticket (get a real INC-XXXXXXX number)
2. Send the email to the vendor (replace "PENDING" with the real ticket number)

### Path A Delivery

```
+--------------+     +-----------------+     +------------------+
| Create ticket| --> | Replace PENDING | --> | Send RESOLUTION  |
| in ServiceNow|     | with INC-number |     | email to vendor  |
| (monitoring) |     | in subject+body |     | via Graph API    |
+--------------+     +-----------------+     +------------------+
                                                      |
                                                      v
                                             Status: RESOLVED
                                             (AI handled it)
```

### Path B Delivery

```
+--------------+     +-----------------+     +-------------------+
| Create ticket| --> | Replace PENDING | --> | Send ACKNOWLEDGMENT|
| in ServiceNow|     | with INC-number |     | email to vendor    |
| (investigate)|     | in subject+body |     | via Graph API      |
+--------------+     +-----------------+     +-------------------+
                                                      |
                                                      v
                                             Status: AWAITING_RESOLUTION
                                             (human team investigates)
                                                      |
                                              +-------+-------+
                                              | Team resolves |
                                              | ticket later  |
                                              +-------+-------+
                                                      |
                                                      v
                                             +-------------------+
                                             | Second email sent |
                                             | with the actual   |
                                             | resolution (from  |
                                             | team's notes)     |
                                             +-------------------+
```

---

## 9. Full Pipeline Flow

The complete end-to-end flow with all decision points:

```
+=========================================================================+
|                        VQMS AI PIPELINE                                  |
+=========================================================================+

   +-------------------+          +-------------------+
   | EMAIL ARRIVES     |          | PORTAL SUBMISSION |
   | (Graph API fetch) |          | (POST /queries)   |
   +--------+----------+          +--------+----------+
            |                              |
            v                              v
   +-------------------+          +-------------------+
   | Parse + S3 store  |          | Validate + IDs    |
   | + vendor ID       |          | + JWT vendor_id   |
   +--------+----------+          +--------+----------+
            |                              |
            +---------- SQS Queue ---------+
                           |
                           v
              +------------------------+
              | Step 7: CONTEXT LOADING|
              | Load vendor profile,   |
              | episodic memory        |
              +------------------------+
                           |
                           v
              +------------------------+
              | Step 8: QUERY ANALYSIS |
              | LLM Call #1            |
              | Intent, entities,      |
              | urgency, confidence    |
              +------------------------+
                           |
                           v
              +========================+
              | DECISION POINT 1       |
              | confidence >= 0.85 ?   |
              +========================+
                    |            |
                   YES          NO
                    |            |
                    |            v
                    |   +-----------------+
                    |   | PATH C: TRIAGE  |
                    |   | Workflow PAUSES  |
                    |   | Human reviews   |
                    |   +-----------------+
                    |            |
                    |        (reviewer
                    |         corrects)
                    |            |
                    v            v
              +------------------------+
              | Step 9A: ROUTING       |
              | Team + SLA assignment  |
              | (deterministic rules)  |
              +------------------------+
                           |
                           v
              +------------------------+
              | Step 9B: KB SEARCH     |
              | Embed query + cosine   |
              | similarity on pgvector |
              +------------------------+
                           |
                           v
              +========================+
              | DECISION POINT 2       |
              | KB score >= 0.80 AND   |
              | content >= 100 chars?  |
              +========================+
                    |            |
                   YES          NO
                    |            |
                    v            v
           +-----------+  +-------------+
           | Step 10A  |  | Step 10B    |
           | PATH A:   |  | PATH B:     |
           | Resolution|  | Acknowledge |
           | LLM #2    |  | LLM #2     |
           | (answer)  |  | (no answer) |
           +-----------+  +-------------+
                    |            |
                    +-----+------+
                          |
                          v
              +------------------------+
              | Step 11: QUALITY GATE  |
              | 7 checks on draft      |
              | (ticket, SLA, sections,|
              |  terms, length, cites, |
              |  PII)                  |
              +------------------------+
                          |
                     PASS | FAIL (max 2 re-drafts)
                          |
                          v
              +------------------------+
              | Step 12: DELIVERY      |
              | 1. Create ServiceNow   |
              |    ticket              |
              | 2. Replace PENDING     |
              |    with INC-XXXXXXX    |
              | 3. Send email via      |
              |    Graph API           |
              +------------------------+
                          |
              +-----------+-----------+
              |                       |
              v                       v
     +----------------+      +------------------+
     | PATH A: DONE   |      | PATH B: WAITING  |
     | Status=RESOLVED|      | Status=AWAITING  |
     | Team monitors  |      | Team investigates|
     +----------------+      +------------------+
```

---

## 10. Quick Reference Table

| Concept | Value | Where Configured | Code File |
|---------|-------|-----------------|-----------|
| Confidence threshold | 0.85 | `AGENT_CONFIDENCE_THRESHOLD` in `.env` | `confidence_check.py` |
| KB match threshold | 0.80 | `KB_MATCH_THRESHOLD` in `.env` | `path_decision.py` |
| Min KB content length | 100 chars | `MIN_CONTENT_LENGTH` constant | `path_decision.py` |
| PLATINUM base SLA | 4 hours | `TIER_SLA_HOURS` dict | `routing.py` |
| GOLD base SLA | 8 hours | `TIER_SLA_HOURS` dict | `routing.py` |
| SILVER base SLA | 16 hours | `TIER_SLA_HOURS` dict | `routing.py` |
| BRONZE base SLA | 24 hours | `TIER_SLA_HOURS` dict | `routing.py` |
| CRITICAL multiplier | x 0.25 | `URGENCY_MULTIPLIER` dict | `routing.py` |
| HIGH multiplier | x 0.50 | `URGENCY_MULTIPLIER` dict | `routing.py` |
| MEDIUM multiplier | x 1.00 | `URGENCY_MULTIPLIER` dict | `routing.py` |
| LOW multiplier | x 1.50 | `URGENCY_MULTIPLIER` dict | `routing.py` |
| SLA warning | 70% | `SLA_WARNING_THRESHOLD_PERCENT` in `.env` | `routing.py` |
| SLA L1 escalation | 85% | `SLA_L1_ESCALATION_THRESHOLD_PERCENT` in `.env` | `routing.py` |
| SLA L2 escalation | 95% | `SLA_L2_ESCALATION_THRESHOLD_PERCENT` in `.env` | `routing.py` |
| Min email words | 50 | `MIN_WORD_COUNT` constant | `quality_gate.py` |
| Max email words | 500 | `MAX_WORD_COUNT` constant | `quality_gate.py` |
| Max re-drafts | 2 | `max_redrafts` in gate result | `quality_gate.py` |
| Quality checks count | 7 | `TOTAL_CHECKS` constant | `quality_gate.py` |
| Restricted terms | 13 terms | `RESTRICTED_TERMS` list | `quality_gate.py` |
| Embedding dimensions | 1024 | `memory.embedding_index` table | `006_create_memory_tables.sql` |

---

*This document reflects the code as of 2026-04-16. All thresholds
and values are configurable. See `config/settings.py` for the full
list of settings loaded from `.env`.*
