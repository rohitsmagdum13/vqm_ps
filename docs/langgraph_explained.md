# LangGraph - How It Actually Works

> Think of LangGraph as a **railway switching yard** for AI tasks.
> Trains (data) enter, follow tracks (edges), stop at stations (nodes),
> and a switchman (conditional logic) decides which track to take next.

---

## 1. The Core Idea

```
+------------------------------------------------------+
|                                                      |
|   Regular Code          vs        LangGraph          |
|                                                      |
|   step_1()                    [Node A]               |
|     |                            |                   |
|   step_2()                   {Decision}              |
|     |                          /    \                |
|   step_3()               [Node B]  [Node C]          |
|     |                        \      /                |
|   step_4()                  [Node D]                 |
|                                                      |
|   Straight line.          Graph with branches.       |
|   No decisions.           Decisions at every fork.   |
|                                                      |
+------------------------------------------------------+
```

**Regular code** = a recipe. Do step 1, then 2, then 3. Always the same.

**LangGraph** = a choose-your-own-adventure book. After each step,
the system DECIDES what happens next based on the current situation.

---

## 2. The Three Building Blocks

LangGraph has only **3 things** you need to understand:

```
+-------------------+-------------------+-------------------+
|                   |                   |                   |
|   1. STATE        |   2. NODES        |   3. EDGES        |
|   (The Clipboard) |   (The Workers)   |   (The Arrows)    |
|                   |                   |                   |
+-------------------+-------------------+-------------------+
```

### 2a. STATE = The Clipboard

Imagine a clipboard that gets passed from person to person in an office.
Each person reads it, does their job, writes their result on it, and
passes it to the next person.

```
Real World Example:                   LangGraph Example:
                                      
  Hospital Patient Chart              Pipeline State
  +---------------------+            +-------------------------+
  | Name: Rajesh         |            | query_id: "VQ-2026-01" |
  | Symptoms: fever      |            | email_body: "Where is   |
  | Lab Results: ___     |  <--->     |   my invoice?"          |
  | Diagnosis: ___       |            | confidence: ___         |
  | Prescription: ___    |            | draft_response: ___     |
  +---------------------+            | path: ___               |
                                      +-------------------------+
  
  Each doctor fills in               Each node fills in
  their section.                     their section.
  Everyone can read                  Every node can read
  what came before.                  what came before.
```

**In code, State is just a Python dictionary (TypedDict):**

```python
from typing import TypedDict

class PipelineState(TypedDict):
    query_id: str
    email_body: str
    confidence: float        # Filled by analysis node
    draft_response: str      # Filled by resolution node
    path: str                # "A", "B", or "C"
```

> KEY INSIGHT: State is NOT stored inside nodes.
> State flows BETWEEN nodes like water in pipes.
> Each node receives state, modifies it, returns updated state.

---

### 2b. NODES = The Workers

A node is just a Python function that:
1. Receives the current state (reads the clipboard)
2. Does some work (calls an LLM, queries a DB, runs rules)
3. Returns updates to the state (writes on the clipboard)

```
Real World:                          LangGraph:

  +-------------+                    +-------------------+
  | Lab Tech    |                    | analysis_node()   |
  |             |                    |                   |
  | IN:  blood  |                    | IN:  email_body   |
  |      sample |        <--->       |                   |
  | DO:  run    |                    | DO:  call Claude  |
  |      tests  |                    |      to classify  |
  | OUT: lab    |                    | OUT: confidence,  |
  |      results|                    |      intent       |
  +-------------+                    +-------------------+
```

**In code, a node is just a function:**

```python
def analysis_node(state: PipelineState) -> dict:
    """
    I receive the state, call the LLM, return my updates.
    I don't need to know what happens before or after me.
    """
    
    # Read from state (read the clipboard)
    email_body = state["email_body"]
    
    # Do my job (call Claude via Bedrock)
    result = call_llm(f"Classify this query: {email_body}")
    
    # Return ONLY what I changed (write on the clipboard)
    return {
        "confidence": result.confidence,
        "intent": result.intent,
    }
```

> KEY INSIGHT: A node returns a PARTIAL dict, not the full state.
> LangGraph merges your updates into the existing state automatically.
> You only return what changed, like filling in one section of a form.

---

### 2c. EDGES = The Arrows

Edges connect nodes. There are **3 types**:

```
TYPE 1: Normal Edge (always go here next)
+--------+          +--------+
| Node A | -------> | Node B |
+--------+          +--------+

  "After A, ALWAYS go to B."
  Like: "After the receptionist, ALWAYS see the nurse."


TYPE 2: Conditional Edge (decide where to go)
                        +--------+
                   +--> | Node B |  (if confidence >= 0.85)
+--------+        |    +--------+
| Node A | ---{?}-+
+--------+        |    +--------+
                   +--> | Node C |  (if confidence < 0.85)
                        +--------+

  "After A, CHECK something, THEN decide."
  Like: "After lab results, if normal -> go home, if abnormal -> see specialist."


TYPE 3: Entry/Exit (where it starts and ends)
                                        
  __START__  -----> [First Node]        
                                        
  [Last Node] ---->  __END__            
                                        
  Every graph needs a beginning and an end.
```

**In code:**

```python
from langgraph.graph import StateGraph, START, END

graph = StateGraph(PipelineState)

# Add nodes (register the workers)
graph.add_node("analyze", analysis_node)
graph.add_node("resolve", resolution_node)
graph.add_node("acknowledge", acknowledgment_node)

# TYPE 1: Normal edge
graph.add_edge(START, "analyze")       # Start -> analyze (always)

# TYPE 2: Conditional edge
graph.add_conditional_edges(
    "analyze",                         # After this node...
    decide_path,                       # ...run this function to decide...
    {                                  # ...and go to:
        "path_a": "resolve",           #   if returns "path_a" -> resolve
        "path_b": "acknowledge",       #   if returns "path_b" -> acknowledge
    }
)

# TYPE 1: Normal edges to END
graph.add_edge("resolve", END)
graph.add_edge("acknowledge", END)
```

**The decision function is just a regular function:**

```python
def decide_path(state: PipelineState) -> str:
    """Look at the clipboard and decide which track to take."""
    if state["confidence"] >= 0.85:
        return "path_a"
    else:
        return "path_b"
```

---

## 3. How It All Fits Together (With Real VQMS Code)

### Where the graph is built

The graph is assembled in one file:

```
src/orchestration/graph.py  -->  build_pipeline_graph()
```

This function takes 6 node objects, registers them, wires edges, and
returns a compiled graph. Think of it as the **blueprint factory**.

### Where the graph is triggered

```
src/orchestration/sqs_consumer.py  -->  PipelineConsumer
```

This class polls SQS queues, pulls a message (a vendor query), builds
the initial PipelineState dict, and calls `compiled_graph.invoke(state)`.
Think of it as the **loading dock** that puts a package on the conveyor belt.

### The State (the clipboard that travels through every node)

Defined in: `src/models/workflow.py` --> `PipelineState`

```
+======================================================================+
|                                                                      |
|   PipelineState (TypedDict)  -- the CLIPBOARD                        |
|                                                                      |
|   Think of this as a FORM with many blank fields.                    |
|   Each node fills in its section and passes it along.                |
|                                                                      |
|   Field                    Who fills it        When                  |
|   ----------------------   ----------------    ------------------    |
|   query_id                 SQS Consumer        At the very start     |
|   correlation_id           SQS Consumer        At the very start     |
|   source                   SQS Consumer        "email" or "portal"   |
|   unified_payload          SQS Consumer        The raw query data    |
|   vendor_context           Context Loading     Step 7                |
|   analysis_result          Query Analysis      Step 8                |
|   routing_decision         Routing             Step 9A               |
|   kb_search_result         KB Search           Step 9B               |
|   processing_path          Confidence/Path     "A", "B", or "C"     |
|   draft_response           Resolution/Ack      Step 10               |
|   quality_gate_result      Quality Gate        Step 11               |
|   ticket_info              Delivery            Step 12               |
|   triage_package           Triage              Path C only           |
|   status                   Every node          Updated at each step  |
|   updated_at               Every node          IST timestamp         |
|                                                                      |
+======================================================================+
```

> IMPORTANT: PipelineState uses `total=False`, which means ALL fields
> are optional. Nodes only return the fields they changed. LangGraph
> merges those updates into the existing state automatically.

---

### Now let's trace a real query, step by step

```
A vendor named Rajesh from TechNova Inc sends an email:
"Where is my invoice INV-2024-5678? It was due last week."
```

---

### STEP 0: Message enters the system

```
  src/services/email_intake.py (or portal_intake.py)
        |
        | Parses the email, identifies the vendor,
        | stores raw email in S3, writes to PostgreSQL,
        | and pushes a message onto the SQS queue.
        |
        v
  +--[ SQS Queue: vqms-email-intake ]--+
  |                                     |
  |  { query_id, vendor_id, subject,   |
  |    body, attachments, source }      |
  +------------------+------------------+
                     |
                     v
  src/orchestration/sqs_consumer.py --> PipelineConsumer
        |
        | Pulls the SQS message, builds initial PipelineState:
        |
        |   state = {
        |     "query_id": "VQ-2026-0042",
        |     "correlation_id": "a1b2c3d4-...",
        |     "source": "email",
        |     "unified_payload": { subject, body, vendor_id, ... },
        |     "status": "RECEIVED",
        |   }
        |
        | Then calls:  compiled_graph.invoke(state)
        |
        v
  +-[ LangGraph takes over from here ]----+
```

**Plain English:** An email arrives. The intake service parses it and
puts it on a queue. The SQS consumer picks it up, creates the initial
"clipboard" (PipelineState), and hands it to LangGraph. From this
point, LangGraph controls the flow.

---

### STEP 1: Context Loading  (START --> context_loading)

```
  File:   src/orchestration/nodes/context_loading.py
  Class:  ContextLoadingNode
  Method: execute(state) -> dict

  +---------------------------------------------------------------+
  |                                                               |
  |  WHAT IT READS from the clipboard:                            |
  |    state["unified_payload"]["vendor_id"]  (e.g. "VEND-001")  |
  |    state["correlation_id"]                                    |
  |                                                               |
  |  WHAT IT DOES (in plain English):                             |
  |                                                               |
  |    1. Checks PostgreSQL cache for vendor profile              |
  |       "Have we looked up this vendor recently? (within 1hr)"  |
  |        |                                                      |
  |        +-- Cache HIT  --> use cached profile (saves time)     |
  |        +-- Cache MISS --> ask Salesforce CRM for the profile  |
  |        +-- Both FAIL  --> use a default "BRONZE" profile      |
  |                                                               |
  |    2. Loads last 5 interactions from PostgreSQL                |
  |       "What did this vendor ask us before?"                   |
  |       Query: memory.episodic_memory WHERE vendor_id = X       |
  |       (If query fails, returns empty list -- non-critical)    |
  |                                                               |
  |    3. Bundles everything into a VendorContext object           |
  |                                                               |
  |  WHAT IT WRITES to the clipboard:                             |
  |    state["vendor_context"] = {                                |
  |        "vendor_id": "VEND-001",                               |
  |        "vendor_profile": {                                    |
  |            "vendor_name": "TechNova Inc",                     |
  |            "tier": { "tier_name": "GOLD", "sla_hours": 8 }   |
  |        },                                                     |
  |        "recent_interactions": [ ... last 5 queries ... ]      |
  |    }                                                          |
  |    state["status"] = "ANALYZING"                              |
  |                                                               |
  +---------------------------------------------------------------+
                         |
                    (normal edge)
                    graph.add_edge("context_loading", "query_analysis")
                         |
                         v
```

**Plain English:** Before asking the AI anything, we first gather
background info. "Who is this vendor? Are they important (GOLD tier)?
What did they ask us last time?" This is like a doctor reading the
patient's history before the examination.

---

### STEP 2: Query Analysis  (context_loading --> query_analysis)

```
  File:   src/orchestration/nodes/query_analysis.py
  Class:  QueryAnalysisNode
  Method: execute(state) -> dict

  +---------------------------------------------------------------+
  |                                                               |
  |  WHAT IT READS from the clipboard:                            |
  |    state["unified_payload"]["body"]     (the email text)      |
  |    state["unified_payload"]["subject"]  (email subject line)  |
  |    state["vendor_context"]              (from Step 1)         |
  |                                                               |
  |  WHAT IT DOES (the 8-layer defense strategy):                 |
  |                                                               |
  |    Layer 1: INPUT VALIDATION                                  |
  |      "Is the email body empty? Too long? Truncate to 10K."   |
  |                                                               |
  |    Layer 2: PROMPT ENGINEERING                                |
  |      Renders a Jinja2 template (query_analysis_v1.j2) with:  |
  |      - vendor name, tier, query text, attachment text         |
  |      File: src/orchestration/prompts/query_analysis_v1.j2    |
  |                                                               |
  |    Layer 3: LLM CALL                                          |
  |      Sends the prompt to Claude Sonnet 3.5 via Bedrock       |
  |      adapter (src/adapters/llm_gateway.py)                   |
  |      temperature=0.1 (very focused, not creative)            |
  |                                                               |
  |    Layer 4: OUTPUT PARSING                                    |
  |      Claude returns JSON. Parse it, handle markdown fences.  |
  |      "Did Claude wrap it in ```json ...```? Strip that."     |
  |                                                               |
  |    Layer 5: PYDANTIC VALIDATION                               |
  |      Validate against AnalysisResult model                   |
  |      (src/models/workflow.py --> AnalysisResult)              |
  |      "Is confidence_score between 0.0 and 1.0? Is urgency    |
  |       one of LOW/MEDIUM/HIGH/CRITICAL?"                      |
  |                                                               |
  |    Layer 6: SELF-CORRECTION (if parse/validate failed)        |
  |      Send error back to Claude: "Your response was broken,   |
  |      here's the error, please fix it." (1 attempt)           |
  |                                                               |
  |    Layer 7: SAFE FALLBACK (if everything failed)              |
  |      Return confidence=0.3 --> automatically goes to Path C  |
  |      "We couldn't analyze this, so send it to a human."      |
  |                                                               |
  |    Layer 8: AUDIT LOGGING                                     |
  |      Log everything: tokens used, time taken, model ID       |
  |                                                               |
  |  WHAT IT WRITES to the clipboard:                             |
  |    state["analysis_result"] = {                               |
  |        "intent_classification": "invoice_inquiry",            |
  |        "extracted_entities": {                                |
  |            "invoice_numbers": ["INV-2024-5678"],              |
  |            "dates": ["last week"]                             |
  |        },                                                     |
  |        "urgency_level": "HIGH",                               |
  |        "sentiment": "FRUSTRATED",                             |
  |        "confidence_score": 0.92,   <-- this is the KEY number|
  |        "suggested_category": "billing",                       |
  |        "tokens_in": 1423,                                     |
  |        "tokens_out": 387                                      |
  |    }                                                          |
  |                                                               |
  +---------------------------------------------------------------+
                         |
                    (normal edge)
                    graph.add_edge("query_analysis", "confidence_check")
                         |
                         v
```

**Plain English:** This is the brain of the system. It sends the
vendor's email to Claude (the AI) and asks: "What does this person
want? How urgent is it? How confident are you?" Claude reads the
email and returns a structured analysis. If Claude's response is
broken or garbled, the system tries to fix it automatically. If
that fails too, it returns a low confidence score so a human
reviews it instead. The system NEVER crashes here.

---

### STEP 3: Confidence Check  (query_analysis --> confidence_check)

```
  File:   src/orchestration/nodes/confidence_check.py
  Class:  ConfidenceCheckNode
  Method: execute(state) -> dict

  +---------------------------------------------------------------+
  |                                                               |
  |  WHAT IT READS from the clipboard:                            |
  |    state["analysis_result"]["confidence_score"]  (e.g. 0.92) |
  |                                                               |
  |  WHAT IT DOES:                                                |
  |                                                               |
  |    Just ONE simple check:                                     |
  |                                                               |
  |      confidence_score >= 0.85 ?                               |
  |                                                               |
  |        YES --> don't change processing_path                   |
  |                (will continue to routing)                      |
  |                                                               |
  |        NO  --> set processing_path = "C"                      |
  |                set status = "PAUSED"                          |
  |                (will go to triage for human review)            |
  |                                                               |
  |  WHAT IT WRITES to the clipboard:                             |
  |                                                               |
  |    If confident (0.92 >= 0.85):                               |
  |      { "updated_at": "2026-04-15T14:30:00" }                 |
  |      (nothing important changes -- just keeps going)          |
  |                                                               |
  |    If NOT confident (0.60 < 0.85):                            |
  |      { "processing_path": "C", "status": "PAUSED" }          |
  |      (flags the query for human review)                       |
  |                                                               |
  +---------------------------------------------------------------+
                         |
                    (CONDITIONAL edge -- this is where the fork happens)
                         |
                    graph.add_conditional_edges(
                        "confidence_check",
                        route_after_confidence_check,   <-- decision function
                        {"routing": "routing", "triage": "triage"}
                    )
                         |
              +----------+-----------+
              |                      |
              v                      v

  route_after_confidence_check(state)
  File: src/orchestration/graph.py (line 108)

  This function just checks:
    if state["processing_path"] == "C":
        return "triage"     --> goes to triage_placeholder
    else:
        return "routing"    --> goes to routing node
```

**Plain English:** This is the traffic cop. It looks at ONE number --
the confidence score. If the AI was confident (>= 0.85), the query
continues down the normal track. If the AI wasn't sure (< 0.85),
the query gets pulled aside for a human to look at. Simple yes/no
gate, nothing fancy.

---

### STEP 4: Routing  (confidence_check --> routing)

*(Only reached if confidence >= 0.85)*

```
  File:   src/orchestration/nodes/routing.py
  Class:  RoutingNode
  Method: execute(state) -> dict

  +---------------------------------------------------------------+
  |                                                               |
  |  WHAT IT READS from the clipboard:                            |
  |    state["analysis_result"]["suggested_category"] ("billing") |
  |    state["analysis_result"]["urgency_level"]      ("HIGH")    |
  |    state["vendor_context"]["vendor_profile"]["tier"]  ("GOLD")|
  |                                                               |
  |  WHAT IT DOES (NO AI -- pure business rules):                 |
  |                                                               |
  |    Rule 1: TEAM ASSIGNMENT (lookup table)                     |
  |                                                               |
  |      Category         -->  Team                               |
  |      --------              ----                               |
  |      "billing"        -->  "finance-ops"                      |
  |      "invoice"        -->  "finance-ops"                      |
  |      "delivery"       -->  "supply-chain"                     |
  |      "contract"       -->  "legal-compliance"                 |
  |      "technical"      -->  "tech-support"                     |
  |      (anything else)  -->  "general-support"                  |
  |                                                               |
  |      For our query: "billing" --> "finance-ops"               |
  |                                                               |
  |    Rule 2: SLA CALCULATION (tier x urgency)                   |
  |                                                               |
  |      Tier base hours:  PLATINUM=4, GOLD=8, SILVER=16, BRONZE=24
  |      Urgency multiply: CRITICAL=0.25, HIGH=0.5, MED=1.0, LOW=1.5
  |                                                               |
  |      Our query: GOLD(8h) x HIGH(0.5) = 4 hours SLA           |
  |                                                               |
  |      Like a restaurant:                                       |
  |        - VIP customer (GOLD) gets faster service              |
  |        - Urgent order (HIGH) gets priority                    |
  |        - Combined: 4 hours to respond                         |
  |                                                               |
  |  WHAT IT WRITES to the clipboard:                             |
  |    state["routing_decision"] = {                              |
  |        "assigned_team": "finance-ops",                        |
  |        "sla_target": { "total_hours": 4 },                   |
  |        "category": "billing",                                 |
  |        "priority": "HIGH",                                    |
  |        "routing_reason": "Category 'billing' -> 'finance-ops'.|
  |            Tier 'GOLD' + urgency 'HIGH' -> SLA 4h."          |
  |    }                                                          |
  |    state["status"] = "ROUTING"                                |
  |                                                               |
  +---------------------------------------------------------------+
                         |
                    (normal edge)
                    graph.add_edge("routing", "kb_search")
                         |
                         v
```

**Plain English:** No AI here -- just a rulebook. "Billing question?
Send to the finance team. GOLD tier vendor with HIGH urgency?
They get a 4-hour SLA." This is like the department directory
at a hospital: "Broken bone? Floor 3. Eye problem? Floor 5."
Fast, deterministic, no guesswork.

---

### STEP 5: KB Search  (routing --> kb_search)

```
  File:   src/orchestration/nodes/kb_search.py
  Class:  KBSearchNode
  Method: execute(state) -> dict

  +---------------------------------------------------------------+
  |                                                               |
  |  WHAT IT READS from the clipboard:                            |
  |    state["unified_payload"]["subject"]  ("Invoice inquiry")   |
  |    state["unified_payload"]["body"]     ("Where is INV...")   |
  |                                                               |
  |  WHAT IT DOES:                                                |
  |                                                               |
  |    Step 9B.1: BUILD SEARCH TEXT                               |
  |      Combines subject + body, truncates to 2000 chars         |
  |      "Invoice inquiry Where is my invoice INV-2024-5678..."   |
  |                                                               |
  |    Step 9B.2: GENERATE EMBEDDING                              |
  |      Sends text to Amazon Titan Embed v2 via Bedrock          |
  |      Returns a vector of 1536 numbers                         |
  |      (src/adapters/llm_gateway.py --> llm_embed())            |
  |                                                               |
  |      Think of it like this:                                   |
  |        "Where is my invoice?" --> [0.12, -0.45, 0.78, ...]   |
  |        A fingerprint of the MEANING, not the words.           |
  |                                                               |
  |    Step 9B.3: VECTOR SIMILARITY SEARCH                        |
  |      Query PostgreSQL with pgvector extension:                |
  |        "Find KB articles whose fingerprint is most similar    |
  |         to this query's fingerprint"                          |
  |                                                               |
  |      SQL: SELECT ... FROM memory.embedding_index              |
  |           ORDER BY embedding <=> query_vector                 |
  |           LIMIT 5                                             |
  |                                                               |
  |      Like a librarian:                                        |
  |        You describe what you need, the librarian finds        |
  |        the 5 most relevant books. Each book gets a            |
  |        relevance score (0.0 = useless, 1.0 = perfect match). |
  |                                                               |
  |    Step 9B.4: FILTER AND RANK                                 |
  |      Only keep matches scoring >= 0.80 (configurable)         |
  |      If no matches >= 0.80, has_sufficient_match = False      |
  |                                                               |
  |  WHAT IT WRITES to the clipboard:                             |
  |    state["kb_search_result"] = {                              |
  |        "matches": [                                           |
  |          { "title": "Invoice Tracking Process",               |
  |            "similarity_score": 0.91,                          |
  |            "content_snippet": "Invoices can be tracked..." }, |
  |          { "title": "Payment Terms FAQ",                      |
  |            "similarity_score": 0.84, ... },                   |
  |        ],                                                     |
  |        "best_match_score": 0.91,                              |
  |        "has_sufficient_match": true    <-- KEY for next step  |
  |    }                                                          |
  |                                                               |
  |  IF EMBEDDING OR SEARCH FAILS:                                |
  |    Returns has_sufficient_match=false (forces Path B)         |
  |    "We can't search? Then a human team will handle it."       |
  |                                                               |
  +---------------------------------------------------------------+
                         |
                    (normal edge)
                    graph.add_edge("kb_search", "path_decision")
                         |
                         v
```

**Plain English:** The system searches its knowledge base (a library
of articles) to see if it already has the answer. It converts the
question into a mathematical fingerprint, then finds articles with
similar fingerprints. If it finds a good match (>= 80% similar),
the AI can answer the question directly. If not, a human team
will need to investigate.

---

### STEP 6: Path Decision  (kb_search --> path_decision)

```
  File:   src/orchestration/nodes/path_decision.py
  Class:  PathDecisionNode
  Method: execute(state) -> dict

  +---------------------------------------------------------------+
  |                                                               |
  |  WHAT IT READS from the clipboard:                            |
  |    state["kb_search_result"]["has_sufficient_match"]  (bool)  |
  |    state["kb_search_result"]["matches"][0] (top match)        |
  |                                                               |
  |  WHAT IT DOES (two checks):                                   |
  |                                                               |
  |    Check 1: has_sufficient_match == true?                     |
  |      "Did the KB search find an article scoring >= 80%?"      |
  |                                                               |
  |    Check 2: Top match content_snippet >= 100 chars?           |
  |      "Does that article have enough actual content?"          |
  |      (Short snippets are generic boilerplate, not helpful)    |
  |                                                               |
  |    BOTH true --> PATH A (AI can answer using KB articles)     |
  |    EITHER false --> PATH B (human team investigates)          |
  |                                                               |
  |  WHAT IT WRITES to the clipboard:                             |
  |                                                               |
  |    Path A (our example -- 0.91 match, long content):          |
  |      { "processing_path": "A", "status": "DRAFTING" }        |
  |                                                               |
  |    Path B (no good KB match):                                 |
  |      { "processing_path": "B", "status": "DRAFTING",         |
  |        "routing_decision": { ...requires_human=true... } }   |
  |                                                               |
  +---------------------------------------------------------------+
                         |
                    (CONDITIONAL edge -- second fork)
                         |
                    graph.add_conditional_edges(
                        "path_decision",
                        route_after_path_decision,    <-- decision function
                        {"resolution": "resolution",
                         "acknowledgment": "acknowledgment"}
                    )
                         |
              +----------+-----------+
              |                      |
              v                      v

  route_after_path_decision(state)
  File: src/orchestration/graph.py (line 120)

    if state["processing_path"] == "A":
        return "resolution"       --> AI drafts full answer
    else:
        return "acknowledgment"   --> AI drafts "we got it" reply
```

**Plain English:** This is the second fork in the road. "Do we have
a good knowledge base article to answer this? If yes, let the AI
write a full answer (Path A). If no, just tell the vendor 'we received
your question, our team is looking into it' (Path B)."

---

### STEPS 7-9: Resolution/Acknowledgment, Quality Gate, Delivery

*(These are currently PLACEHOLDER stubs -- Phase 4 implementation pending)*

```
  File: src/orchestration/graph.py (lines 41-100)

  +-------- PATH A (our example) --------+-------- PATH B -----------------+
  |                                       |                                |
  |  resolution_placeholder(state)        |  acknowledgment_placeholder()  |
  |  "TODO: LLM Call #2 -- draft a       |  "TODO: Draft an email that    |
  |   full answer using KB articles"      |   says 'we received your query,|
  |                                       |   ticket is INC-XXXXXXX,       |
  |  Will be:                             |   team is reviewing'"          |
  |  src/pipeline/nodes/resolution.py     |                                |
  |                                       |  Will be:                      |
  +-------------------+-------------------+  src/pipeline/nodes/            |
                      |                      acknowledgment.py             |
                      |                      +--------------+---------------+
                      |                                     |
                      +----------------+--------------------+
                                       |
                                       v
                         quality_gate_placeholder(state)
                         "TODO: Run 7 checks on the draft"
                         - Ticket # format (INC-XXXXXXX)?
                         - SLA wording correct?
                         - Required sections present?
                         - No restricted terms?
                         - Length 50-500 words?
                         - Source citations (Path A)?
                         - No PII leaked?

                         Will be:
                         src/pipeline/nodes/quality_gate.py
                                       |
                                       v
                         delivery_placeholder(state)
                         "TODO: Create ServiceNow ticket
                          + send email via MS Graph API"

                         Will be:
                         src/pipeline/nodes/delivery.py
                                       |
                                       v
                                     __END__
```

---

### STEP 3b (alternate): Triage -- Path C

*(When confidence < 0.85 at Step 3)*

```
  File: src/orchestration/graph.py (line 41)

  +---------------------------------------------------------------+
  |  triage_placeholder(state)                                    |
  |                                                               |
  |  "TODO: Build a TriagePackage with:                           |
  |   - The original query                                        |
  |   - The AI's analysis (even though it's low confidence)       |
  |   - Confidence breakdown                                      |
  |   - Suggested routing                                         |
  |   - Suggested draft                                           |
  |                                                               |
  |  Push to human-review queue. PAUSE workflow."                 |
  |                                                               |
  |  Will be: src/pipeline/nodes/triage.py                        |
  |                                                               |
  |  Writes: status = "PAUSED"                                    |
  |                                                               |
  |  The workflow STOPS here until a human reviewer logs in,      |
  |  reviews the package, corrects the classification, and        |
  |  submits. Then the workflow RESUMES from the routing step     |
  |  with the corrected data.                                     |
  +---------------------------------------------------------------+
                         |
                    graph.add_edge("triage", END)
                         |
                         v
                       __END__  (for now -- resumes later)
```

---

### The Complete Wiring (from graph.py lines 161-211)

```
  This is what build_pipeline_graph() produces:


                              __START__
                                  |
                       set_entry_point("context_loading")
                                  |
                                  v
                        +------------------+
                        | context_loading  |  ContextLoadingNode.execute
                        +------------------+  src/orchestration/nodes/context_loading.py
                                  |
                       add_edge("context_loading", "query_analysis")
                                  |
                                  v
                        +------------------+
                        | query_analysis   |  QueryAnalysisNode.execute
                        +------------------+  src/orchestration/nodes/query_analysis.py
                                  |
                       add_edge("query_analysis", "confidence_check")
                                  |
                                  v
                        +------------------+
                        | confidence_check |  ConfidenceCheckNode.execute
                        +------------------+  src/orchestration/nodes/confidence_check.py
                                  |
                       add_conditional_edges(
                           "confidence_check",
                           route_after_confidence_check,  <-- graph.py:108
                           {"routing": "routing", "triage": "triage"}
                       )
                                  |
                   +--------------+--------------+
                   |                             |
          processing_path != "C"         processing_path == "C"
                   |                             |
                   v                             v
          +------------------+          +------------------+
          |     routing      |          |     triage       |  [STUB]
          +------------------+          +------------------+
          RoutingNode.execute                    |
          nodes/routing.py            add_edge("triage", END)
                   |                             |
        add_edge("routing",                      v
                 "kb_search")                 __END__
                   |
                   v
          +------------------+
          |    kb_search     |  KBSearchNode.execute
          +------------------+  nodes/kb_search.py
                   |
        add_edge("kb_search",
                 "path_decision")
                   |
                   v
          +------------------+
          |  path_decision   |  PathDecisionNode.execute
          +------------------+  nodes/path_decision.py
                   |
        add_conditional_edges(
            "path_decision",
            route_after_path_decision,  <-- graph.py:120
            {"resolution": "resolution",
             "acknowledgment": "acknowledgment"}
        )
                   |
          +--------+--------+
          |                 |
    path == "A"       path == "B"
          |                 |
          v                 v
   +------------+   +---------------+
   | resolution |   | acknowledgment|  [BOTH STUBS]
   +------------+   +---------------+
          |                 |
          +--------+--------+
                   |
        add_edge(both, "quality_gate")
                   |
                   v
          +------------------+
          |  quality_gate    |  [STUB]
          +------------------+
                   |
        add_edge("quality_gate", "delivery")
                   |
                   v
          +------------------+
          |    delivery      |  [STUB]
          +------------------+
                   |
        add_edge("delivery", END)
                   |
                   v
                __END__
```

---

### Summary: File-to-Step Map

```
+------+---------------------+----------------------------------------+-----------+
| Step | What Happens        | File + Class                           | LLM Call? |
+------+---------------------+----------------------------------------+-----------+
|  0   | Message arrives     | src/orchestration/sqs_consumer.py      | No        |
|      | from SQS queue      | --> PipelineConsumer                   |           |
+------+---------------------+----------------------------------------+-----------+
|  7   | Load vendor context | src/orchestration/nodes/               | No        |
|      | (who is this vendor?|   context_loading.py                   |           |
|      |  what's their       | --> ContextLoadingNode.execute()       |           |
|      |  history?)          |                                        |           |
+------+---------------------+----------------------------------------+-----------+
|  8   | Analyze the query   | src/orchestration/nodes/               | YES (#1)  |
|      | (what do they want? |   query_analysis.py                    | Claude    |
|      |  how urgent? how    | --> QueryAnalysisNode.execute()        | Sonnet    |
|      |  confident?)        |                                        | via       |
|      |                     |                                        | Bedrock   |
+------+---------------------+----------------------------------------+-----------+
| DP1  | Confidence gate     | src/orchestration/nodes/               | No        |
|      | (>= 0.85 continue   |   confidence_check.py                  | (just a   |
|      |  < 0.85 --> Path C) | --> ConfidenceCheckNode.execute()      |  number   |
|      |                     |                                        |  check)   |
+------+---------------------+----------------------------------------+-----------+
| 9A   | Assign team + SLA   | src/orchestration/nodes/               | No        |
|      | (billing --> finance |   routing.py                           | (pure     |
|      |  GOLD+HIGH --> 4hr) | --> RoutingNode.execute()              |  rules)   |
+------+---------------------+----------------------------------------+-----------+
| 9B   | Search knowledge    | src/orchestration/nodes/               | YES       |
|      | base for answer     |   kb_search.py                         | (embed    |
|      | (vector similarity) | --> KBSearchNode.execute()             |  only,    |
|      |                     |                                        |  Titan)   |
+------+---------------------+----------------------------------------+-----------+
| DP2  | Path A vs Path B    | src/orchestration/nodes/               | No        |
|      | (KB match >= 80%?   |   path_decision.py                     | (just     |
|      |  has real content?) | --> PathDecisionNode.execute()         |  checks)  |
+------+---------------------+----------------------------------------+-----------+
| 10A  | Draft resolution    | [STUB] graph.py:resolution_placeholder | YES (#2) |
|      | (full AI answer)    | Future: src/pipeline/nodes/resolution  | Claude    |
+------+---------------------+----------------------------------------+-----------+
| 10B  | Draft acknowledgment| [STUB] graph.py:acknowledgment_placeholder| YES(#2)|
|      | ("we got it" reply) | Future: src/pipeline/nodes/acknowledgment|         |
+------+---------------------+----------------------------------------+-----------+
| 11   | Quality checks      | [STUB] graph.py:quality_gate_placeholder | No     |
|      | (7 validation rules)| Future: src/pipeline/nodes/quality_gate|           |
+------+---------------------+----------------------------------------+-----------+
| 12   | Create ticket +     | [STUB] graph.py:delivery_placeholder   | No        |
|      | send email          | Future: src/pipeline/nodes/delivery    |           |
+------+---------------------+----------------------------------------+-----------+

  Graph assembly:  src/orchestration/graph.py --> build_pipeline_graph()
  State shape:     src/models/workflow.py --> PipelineState (TypedDict)
  Decision logic:  src/orchestration/graph.py --> route_after_confidence_check()
                   src/orchestration/graph.py --> route_after_path_decision()
```

---

## 4. The Full Picture as ASCII

```
                    __START__
                        |
                        v
               +----------------+
               | Context Loading|  Load vendor info
               +----------------+  + past interactions
                        |
                        v
               +----------------+
               | Query Analysis |  LLM Call #1:
               |   (Claude)     |  "What does this
               +----------------+  vendor want?"
                        |
                   {confidence?}
                   /          \
             >= 0.85        < 0.85
                /              \
               v                v
     +------------------+   +---------+
     |  Routing (rules) |   | Triage  |------> PAUSE
     |        +         |   | (Path C)|        (human
     | KB Search (embed)|   +---------+         reviews)
     +------------------+       |                 |
              |                 |      +----------+
         {KB match?}            |      | Reviewer submits
          /       \             |      | corrections
      >= 80%    < 80%           |      +----------+
        /          \            |           |
       v            v           |    (re-enters at
  +---------+  +----------+    |     routing with
  |Resolution|  |Acknowledge|   |     corrected data)
  | (Path A) |  | (Path B)  |  |
  +---------+  +----------+   |
       |            |          |
       v            v          |
  +---------+  +---------+    |
  | Quality |  | Quality |    |
  |  Gate   |  |  Gate   |    |
  +---------+  +---------+    |
       |            |          |
       v            v          |
  +---------+  +---------+    |
  |Delivery |  |Delivery |    |
  |(ticket  |  |(ticket  |    |
  | + email)|  | + email)|    |
  +---------+  +---------+    |
       |            |          |
       v            v          |
     __END__     __END__       |
```

---

## 5. Key Concepts with Simple Analogies

### Concept 1: State is Immutable (New Copy Each Time)

```
WRONG way to think:           RIGHT way to think:

  One clipboard passed        A PHOTOCOPY made at each step.
  around, everyone             Each worker gets a copy,
  scribbles on it.             writes on it, passes the
                               updated copy forward.

  [A] writes on clipboard     [A] gets copy #1, returns copy #2
        |                            |
  [B] same clipboard          [B] gets copy #2, returns copy #3
        |                            |
  [C] same clipboard          [C] gets copy #3, returns copy #4

  Why? If Node B crashes,     Why? If Node B crashes,
  the clipboard is messy.     we still have copy #1
  Can't retry cleanly.        and can retry from there.
```

### Concept 2: Nodes Don't Know Each Other

```
  BAD (tightly coupled):         GOOD (LangGraph way):
  
  def node_a():                  def node_a(state):
      result = node_b()              # I just read state
      if result > 5:                 # and return my updates
          node_c()                   return {"x": compute()}
      else:                      
          node_d()               # The GRAPH decides who
                                 # runs next, not the node.
  Node A calls B directly.
  A must know B exists.          Nodes are independent workers.
  Hard to change the flow.       The graph wiring controls flow.
```

### Concept 3: Conditional Edges = The Traffic Cop

```
  Think of a traffic circle (roundabout):

         [Node B]
            ^
            |
  ----------+----------
  |                    |
  |    TRAFFIC COP     |
  |    checks state    |
  |    and points      |
  |                    |
  ----------+----------
            |
            v
         [Node C]
  
  The cop (conditional edge function) looks at the state
  and says: "You go LEFT" or "You go RIGHT."
  
  The nodes don't decide. The cop decides.
  The nodes just do their job wherever they are sent.
```

### Concept 4: Compile = Freeze the Blueprint

```
  Building phase:                    Running phase:
  
  graph = StateGraph(State)          app = graph.compile()
  graph.add_node(...)                
  graph.add_edge(...)                result = app.invoke({
  graph.add_conditional_edges(...)       "email_body": "..."
                                     })
  
  Like drawing the blueprint         Like building the house
  of a house. You can erase          from the blueprint.
  and redraw lines.                  Can't change walls now.
  
  .compile() = "Blueprint is done.   .invoke() = "Run the
   Lock it in. Build it."             pipeline with this input."
```

---

## 6. Parallel Nodes (Do Two Things at Once)

LangGraph can run nodes **in parallel** when they don't depend on each other:

```
  Sequential (slow):              Parallel (fast):
  
  [Routing] --> [KB Search]       [Routing]----+
                                               |---> [Path Decision]
  Total: 2 seconds + 3 seconds   [KB Search]--+
       = 5 seconds                
                                  Total: max(2s, 3s) = 3 seconds
```

**In code, you fan out and fan in:**

```python
# Fan out: after analysis, run BOTH routing and kb_search
graph.add_edge("analysis", "routing")
graph.add_edge("analysis", "kb_search")

# Fan in: both must finish before path_decision runs
graph.add_edge("routing", "path_decision")
graph.add_edge("kb_search", "path_decision")
```

```
  Visually:
  
       [analysis]
        /      \
       v        v
  [routing]  [kb_search]     <-- these run at the SAME TIME
       \      /
        v    v
    [path_decision]          <-- waits for BOTH to finish
```

---

## 7. Human-in-the-Loop (Path C: Pause and Resume)

Sometimes the AI isn't confident. The workflow needs to STOP, wait
for a human, then CONTINUE.

```
  Normal flow:       Path C flow (human-in-the-loop):
  
  [A] -> [B] -> [C]   [A] -> [B] -> PAUSE .......... RESUME -> [C]
                                       |                  ^
                                       v                  |
                                  Human reviews      Human submits
                                  the triage         corrections
                                  package            
                                  
  Like an assembly line           Like a quality inspector
  that never stops.               who can STOP the line,
                                  fix the issue, then
                                  restart it.
```

**In LangGraph, this uses "interrupt" or callback tokens:**

```python
from langgraph.checkpoint.memory import MemorySaver

# Add checkpointing so state can be saved and resumed
checkpointer = MemorySaver()
app = graph.compile(checkpointer=checkpointer)

# The triage node can interrupt the workflow
def triage_node(state):
    """Pause here. Human will review and resume."""
    return {
        "status": "AWAITING_HUMAN_REVIEW",
        "triage_package": build_triage_package(state),
    }

# When using interrupt_before or interrupt_after:
app = graph.compile(
    checkpointer=checkpointer,
    interrupt_before=["triage"]   # Pause BEFORE triage runs
)
```

---

## 8. Checkpointing (Save Your Progress)

Like a video game save point. If the system crashes, you can
resume from the last checkpoint instead of starting over.

```
  Without checkpointing:          With checkpointing:
  
  [A] -> [B] -> [C] -> CRASH!    [A] -> [B] -> [C] -> CRASH!
                                    S      S      S
  Must restart from [A].            |      |      |
  All work lost.                  saved  saved  saved
                                  
                                  Resume from [C]'s save.
                                  Work preserved.
  
  S = save point (checkpoint stored in PostgreSQL / memory)
```

**In code:**

```python
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres import PostgresSaver

# In-memory (for development)
checkpointer = MemorySaver()

# PostgreSQL (for production)
checkpointer = PostgresSaver(connection_string="postgresql://...")

app = graph.compile(checkpointer=checkpointer)

# Every node execution automatically saves a checkpoint.
# If something fails, invoke again with the same thread_id
# and it picks up where it left off.
result = app.invoke(
    {"email_body": "Where is my invoice?"},
    config={"configurable": {"thread_id": "VQ-2026-0042"}}
)
```

---

## 9. Putting It All Together - Minimal Working Example

```python
"""
Minimal LangGraph example: a 3-node pipeline that classifies
a query and routes it to either a resolver or acknowledger.
"""

from langgraph.graph import StateGraph, START, END
from typing import TypedDict


# ---- STEP 1: Define the State (the clipboard) ----

class QueryState(TypedDict):
    question: str
    confidence: float
    answer: str


# ---- STEP 2: Define the Nodes (the workers) ----

def analyze(state: QueryState) -> dict:
    """Fake analysis - in real code, this calls Claude."""
    question = state["question"]
    if "invoice" in question.lower():
        return {"confidence": 0.95}
    else:
        return {"confidence": 0.60}


def resolve(state: QueryState) -> dict:
    """Path A: AI knows the answer."""
    return {"answer": f"Your invoice status is: PAID."}


def acknowledge(state: QueryState) -> dict:
    """Path B: AI doesn't know, human team will check."""
    return {"answer": "We received your query. A team member will respond."}


# ---- STEP 3: Define the Decision Function ----

def route_by_confidence(state: QueryState) -> str:
    """The traffic cop. Looks at confidence and picks a path."""
    if state["confidence"] >= 0.85:
        return "path_a"
    else:
        return "path_b"


# ---- STEP 4: Build the Graph (draw the blueprint) ----

graph = StateGraph(QueryState)

# Register workers
graph.add_node("analyze", analyze)
graph.add_node("resolve", resolve)
graph.add_node("acknowledge", acknowledge)

# Wire them up
graph.add_edge(START, "analyze")           # Start -> analyze

graph.add_conditional_edges(               # analyze -> ??? (depends)
    "analyze",
    route_by_confidence,
    {
        "path_a": "resolve",               #   high confidence -> resolve
        "path_b": "acknowledge",           #   low confidence -> acknowledge
    }
)

graph.add_edge("resolve", END)             # resolve -> done
graph.add_edge("acknowledge", END)         # acknowledge -> done


# ---- STEP 5: Compile and Run (build and use) ----

app = graph.compile()

result = app.invoke({
    "question": "Where is my invoice INV-2024-5678?",
    "confidence": 0.0,
    "answer": "",
})

print(result["answer"])
# Output: "Your invoice status is: PAID."
```

**What happens when you call `app.invoke()`:**

```
  invoke({"question": "Where is my invoice?"})
     |
     v
  START --> analyze()
              |
              | state["confidence"] = 0.95
              v
         route_by_confidence(state)
              |
              | returns "path_a" (because 0.95 >= 0.85)
              v
         resolve()
              |
              | state["answer"] = "Your invoice status is: PAID."
              v
            END
              |
              v
         return state  -->  {"question": "...", "confidence": 0.95, 
                             "answer": "Your invoice status is: PAID."}
```

---

## 10. LangGraph vs Other Approaches

```
+--------------------+-------------------+--------------------+
|   Plain Python     |   LangChain       |   LangGraph        |
+--------------------+-------------------+--------------------+
|                    |                   |                    |
| result = step1()   | chain = (         | graph.add_node()   |
| result = step2(r)  |   prompt          | graph.add_edge()   |
| result = step3(r)  |   | llm           | graph.compile()    |
|                    |   | parser        |                    |
| Straight line.     | )                 | Any shape.         |
| No branching.      |                   | Branches, loops,   |
| No state mgmt.     | Straight line     | parallel, pause,   |
| No retries.        | (mostly).         | resume, retry.     |
|                    | Good for simple   |                    |
| Fine for scripts.  | LLM chains.      | Built for agents   |
|                    |                   | and orchestration. |
+--------------------+-------------------+--------------------+
```

---

## 11. Vocabulary Cheat Sheet

```
+---------------------+---------------------------+---------------------------+
| LangGraph Term      | Plain English             | Real-World Analogy        |
+---------------------+---------------------------+---------------------------+
| StateGraph          | The blueprint             | Architectural drawing     |
| State (TypedDict)   | The shared data clipboard | Patient chart at hospital |
| Node                | A worker / processing step| A station on assembly line|
| Edge                | A connection between nodes| Railroad track            |
| Conditional Edge    | A fork in the road        | Traffic cop at roundabout |
| START               | Where the pipeline begins | Factory loading dock      |
| END                 | Where the pipeline stops  | Shipping department       |
| .compile()          | Lock the blueprint        | "Blueprint approved"      |
| .invoke()           | Run the pipeline once     | "Process one order"       |
| .stream()           | Run + show progress live  | "Watch the assembly line" |
| Checkpointer        | Save-game system          | Video game save points    |
| thread_id           | Which "game save" to use  | Save slot 1, 2, 3...     |
| interrupt_before    | Pause before a node       | "Stop line before QA"     |
| MemorySaver         | In-memory checkpoints     | Sticky notes (temporary)  |
| PostgresSaver       | DB-backed checkpoints     | Filing cabinet (permanent)|
+---------------------+---------------------------+---------------------------+
```

---

## 12. Common Mistakes (and How to Avoid Them)

```
MISTAKE 1: Returning full state from a node
  
  BAD:   return state                    # Returns everything
  GOOD:  return {"confidence": 0.92}     # Returns only changes


MISTAKE 2: Nodes calling other nodes directly

  BAD:   def node_a(state):
             result = node_b(state)      # Don't do this!
  GOOD:  Let the GRAPH connect them via edges.


MISTAKE 3: Forgetting to compile before invoke

  BAD:   graph.invoke(...)               # StateGraph has no .invoke()
  GOOD:  app = graph.compile()
         app.invoke(...)                 # CompiledGraph has .invoke()


MISTAKE 4: Not providing all required state keys on invoke

  BAD:   app.invoke({})                  # Missing required fields
  GOOD:  app.invoke({
             "question": "...",
             "confidence": 0.0,
             "answer": ""
         })


MISTAKE 5: Hardcoding paths in nodes instead of using conditional edges

  BAD:   def analyze(state):
             if confident:
                 return resolve(state)   # Node decides flow
  GOOD:  Use add_conditional_edges()     # Graph decides flow
```

---

## Summary

```
+----------------------------------------------------------+
|                                                          |
|   LangGraph in one sentence:                             |
|                                                          |
|   "A state machine where AI agents are the nodes,       |
|    conditions are the edges, and a shared state dict     |
|    is the memory that flows through the whole thing."    |
|                                                          |
+----------------------------------------------------------+

  STATE   = What we know so far (the clipboard)
  NODES   = What we do at each step (the workers)
  EDGES   = How steps connect (the arrows + decisions)
  COMPILE = Freeze the design
  INVOKE  = Run it once with input data
```
