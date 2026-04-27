# VQMS — Logic Flow (Simple Walkthrough)

A short, plain-English explanation of how a vendor query moves through the system, followed by a single ASCII box diagram that shows every step end-to-end.

---

## What This System Does (in 5 lines)

1. A vendor sends a question, either by **email** or through the **web portal**.
2. The system **fetches it, parses it, and identifies the vendor**.
3. An **AI pipeline** reads the question, scores its confidence, and searches the knowledge base.
4. Based on confidence and KB match, the query takes one of **three paths**: A (AI answers), B (human team answers), or C (human reviews first).
5. The vendor receives a reply email and the case is closed.

---

## The Three Paths (one line each)

- **Path A — AI-Resolved:** AI is confident AND KB has a clear answer. AI drafts the full reply.
- **Path B — Human-Team-Resolved:** AI is confident BUT KB has no specific facts. AI sends an acknowledgment, human team investigates, AI drafts the final reply from the team's notes.
- **Path C — Low-Confidence:** AI is unsure. Workflow PAUSES. A human reviewer corrects the analysis, then it resumes as Path A or B.

---

## End-to-End Logic Flow (ASCII)

```
+================================================================================+
|                            VQMS — END-TO-END LOGIC FLOW                        |
+================================================================================+

   +------------------------+              +-------------------------+
   |   ENTRY 1: EMAIL       |              |   ENTRY 2: PORTAL       |
   |   vendor sends email   |              |   vendor logs in,       |
   |   to support mailbox   |              |   submits a form        |
   +-----------+------------+              +------------+------------+
               |                                        |
               v                                        v
   +------------------------+              +-------------------------+
   | Email Intake Service   |              | Portal Submission       |
   | - webhook + 5 min poll |              | - JWT auth check        |
   | - dedupe (idempotency) |              | - Pydantic validate     |
   | - parse MIME + attach. |              | - generate query_id     |
   | - find vendor (SF)     |              | - dedupe (idempotency)  |
   | - thread correlation   |              | - HTTP 201 instantly    |
   | - store raw -> S3      |              | - write -> PostgreSQL   |
   | - meta -> PostgreSQL   |              |                         |
   +-----------+------------+              +------------+------------+
               |                                        |
               +-------------------+--------------------+
                                   |
                                   v
                        +----------------------+
                        |   SQS QUEUE          |
                        |  (intake messages)   |
                        +----------+-----------+
                                   |
                                   v
+--------------------------------------------------------------------------------+
|                     LANGGRAPH AI PIPELINE (one shared graph)                   |
+--------------------------------------------------------------------------------+
                                   |
                                   v
                 +-----------------------------------+
                 | Step 7: CONTEXT LOADING           |
                 | - load vendor profile (SF cache)  |
                 | - load last 5 vendor interactions |
                 | - cache workflow state (24h TTL)  |
                 +----------------+------------------+
                                  |
                                  v
                 +-----------------------------------+
                 | Step 8: QUERY ANALYSIS  (LLM #1)  |
                 | Bedrock Claude Sonnet 3.5         |
                 | - intent, entities, urgency       |
                 | - sentiment, confidence (0..1)    |
                 +----------------+------------------+
                                  |
                                  v
                 +-----------------------------------+
                 |  DECISION 1: confidence >= 0.85 ? |
                 +---+---------------------------+---+
                     | YES                       | NO
                     v                           v
   +----------------------------+    +-------------------------------+
   | Step 9A: ROUTING           |    |  PATH C — TRIAGE              |
   | - team, SLA, category      |    |  - build TriagePackage        |
   |                            |    |  - push to human-review queue |
   | Step 9B: KB SEARCH         |    |  - PAUSE workflow (callback)  |
   | - embed query (Titan v2)   |    |                               |
   | - cosine search pgvector   |    |  Reviewer logs in, fixes      |
   +-------------+--------------+    |  intent / vendor / routing    |
                 |                   |  - workflow RESUMES           |
                 v                   |  - SLA clock starts NOW       |
   +----------------------------+    +---------------+---------------+
   | DECISION 2:                |                    |
   | KB match >= 0.80 AND       |                    | (loops back
   | resolution conf >= 0.85 ?  |                    |  to Step 9
   +---+---------------------+--+                    |  with corrected
       | YES                 | NO                    |  data)
       v                     v                       |
+--------------+    +------------------+             |
| PATH A       |    | PATH B           |<------------+
| AI-RESOLVED  |    | TEAM-RESOLVED    |
+------+-------+    +---------+--------+
       |                      |
       v                      v
+----------------+    +----------------------+
| Step 10A:      |    | Step 10B:            |
| RESOLUTION     |    | ACKNOWLEDGMENT       |
| (LLM #2)       |    | (LLM #2)             |
| full answer    |    | "we got it,          |
| from KB facts  |    |  ticket INC-... ,    |
|                |    |  team is reviewing"  |
+--------+-------+    +----------+-----------+
         |                       |
         +-----------+-----------+
                     |
                     v
        +------------------------------+
        | Step 11: QUALITY GATE        |
        | 7 checks on the draft:       |
        | 1. ticket # format           |
        | 2. SLA wording               |
        | 3. required sections         |
        | 4. restricted terms          |
        | 5. length 50..500 words      |
        | 6. source citations (A only) |
        | 7. PII scan (Comprehend)     |
        | max 2 re-drafts -> else      |
        | route to human review        |
        +--------------+---------------+
                       |
                       v
        +------------------------------+
        | Step 12: DELIVERY            |
        | - create ticket in           |
        |   ServiceNow                 |
        | - send email via             |
        |   MS Graph /sendMail         |
        | - publish EventBridge events |
        +--------------+---------------+
                       |
                       v
        +------------------------------+
        | PATH B ONLY (back-fill):     |
        | - human team investigates    |
        | - resolves ticket in SNOW    |
        | - webhook -> LLM #3 drafts   |
        |   real answer from notes     |
        | - Quality Gate -> send email |
        +--------------+---------------+
                       |
                       v
        +------------------------------+
        | Step 13-16: SLA + CLOSURE    |
        | - SLA timer (70/85/95%)      |
        | - vendor confirms OR         |
        |   auto-close after 5 days    |
        | - save episodic memory       |
        +------------------------------+

+================================================================================+
|  STORAGE EVERYWHERE                                                            |
|  - PostgreSQL (intake / workflow / audit / memory / reporting / cache)         |
|  - S3 single bucket "vqms-data-store" (prefix-organized by VQ-ID)              |
|  - pgvector for KB embeddings (no separate vector DB)                          |
|  - EventBridge bus for the 20 audit events                                     |
|  - Correlation ID flows through every step                                     |
+================================================================================+
```

---

## Step-by-Step in Plain English

| # | Step | What it does (one line) |
|---|------|------------------------|
| 1 | **Entry — Email** | Vendor email lands in shared mailbox; webhook + 5 min poll catch it. |
| 2 | **Entry — Portal** | Vendor submits a form via JWT-authed `POST /queries`. |
| 3 | **Idempotency** | PostgreSQL `INSERT ON CONFLICT` ensures the same query is never processed twice. |
| 4 | **Vendor identification** | Match sender email to a Salesforce vendor (3-step fallback for email path). |
| 5 | **SQS enqueue** | Both paths drop a normalized payload onto the same queue. |
| 6 | **Context loading** | Pipeline pulls vendor profile + last 5 interactions from memory. |
| 7 | **Query analysis (LLM #1)** | Claude reads the query and scores intent, entities, urgency, confidence. |
| 8 | **Confidence check** | < 0.85 → Path C (pause). >= 0.85 → continue. |
| 9 | **Routing + KB search (parallel)** | Rules pick the team/SLA; Titan embeddings + pgvector find KB matches. |
| 10 | **Path decision** | Strong KB match + high resolution confidence → Path A; otherwise → Path B. |
| 11 | **Draft (LLM #2)** | Path A drafts a full answer; Path B drafts an acknowledgment only. |
| 12 | **Quality gate** | 7 deterministic checks; up to 2 re-drafts before escalating to human. |
| 13 | **Delivery** | Create ServiceNow ticket, send email through MS Graph, publish events. |
| 14 | **Path B back-fill** | After the team resolves the ticket, an LLM drafts the final reply from their notes. |
| 15 | **SLA + closure** | Timer warns at 70/85/95%; vendor confirms or auto-close after 5 business days. |

---

## Key Rules to Remember

- **Two entries, one pipeline** — email and portal converge at the LangGraph orchestrator.
- **No Redis** — PostgreSQL handles idempotency, caching, and vector search (via pgvector).
- **Correlation ID** flows through every step for traceability.
- **Path C pauses the workflow** — SLA clock starts only after the human reviewer finishes.
- **All LLM calls go through `src/adapters/bedrock.py`** — nothing calls Bedrock directly.
- **Quality Gate is mandatory** — no email leaves the system without passing all 7 checks.
