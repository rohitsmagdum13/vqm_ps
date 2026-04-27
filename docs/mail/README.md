# Sample Vendor Emails for VQMS Testing

Each subfolder contains realistic vendor emails for testing a specific behaviour in the VQMS pipeline. Send the body of any `.txt` file to your dev mailbox (`vendor-support@…`) — or paste it through the portal — and observe what the pipeline does with it.

## Folder map

| Folder | Purpose | Expected pipeline behaviour |
|---|---|---|
| [`triage/`](./triage/) | Low-confidence emails that should land in the **Path C reviewer queue** (`workflow.triage_packages`). The Query Analysis Agent should return `confidence_score < 0.85`. | Status `PAUSED_AWAITING_REVIEW`, `processing_path = 'C'`. Visible in the `/admin/triage` queue and on `/triage/queue` API. |
| [`query_types/`](./query_types/) | One email per major `query_type` enum value. Used to exercise the classifier across the full type range. | Should classify as the named type with `confidence_score >= 0.85`. |
| [`routing/`](./routing/) | One email per investigation team + priority extremes (CRITICAL, LOW). Used to verify the deterministic routing rules in [`src/orchestration/nodes/routing.py`](../../src/orchestration/nodes/routing.py). | `routing_decision.assigned_team` should match the file name. |
| [`investigations/`](./investigations/) | Clear queries the AI cannot resolve from the KB alone — they go to **Path B** so a human team must investigate before the resolution email is drafted. | `processing_path = 'B'`, ticket created in ServiceNow, vendor receives an acknowledgment email (Step 10B). |

## How to use

### 1. Email path
Send the entire body (everything after the `Subject:` line — including the subject line itself if your client supports it) to the configured `GRAPH_API_MAILBOX`. The Email Intake Service will pick it up via webhook or polling and route it through the pipeline.

### 2. Portal path
Paste the body into the "Description" field of the portal wizard, set the subject from the `Subject:` line, pick a query type, and submit. The Portal Submission Service generates a `query_id` and pushes onto `vqms-query-intake-queue`.

### 3. Verify which path the email took

After 1–2 minutes (LLM analysis + routing), query the DB directly:

```bash
uv run python -c "
import sys; sys.path.insert(0, 'src')
import asyncio
from db.connection import PostgresConnector
from config.settings import get_settings

async def go():
    pg = PostgresConnector(get_settings()); await pg.connect()
    rows = await pg.fetch('''
        SELECT ce.query_id, ce.processing_path, ce.status,
               em.subject, em.sender_email,
               (ce.analysis_result->>'confidence_score')::float AS confidence,
               ce.analysis_result->>'intent_classification' AS intent,
               ce.analysis_result->>'suggested_category' AS category
        FROM workflow.case_execution ce
        LEFT JOIN intake.email_messages em ON em.query_id = ce.query_id
        ORDER BY ce.created_at DESC LIMIT 10
    ''')
    for r in rows: print(r)
    await pg.disconnect()

asyncio.run(go())
"
```

## Data conventions used in these samples

- Currency in **₹ (INR)** with Indian numbering format (`₹7,67,000.00`).
- **Vendor IDs** match the `Vendor_ID__c` format (`V-001`, `V-002`, …) used in Salesforce.
- **Sender emails** prefer the seeded users (`dinesh.chauhan@technova.io`, `sneha.singh@acmeindustrial.com`, `deepak.reddy@swiftlogfreight.com`) so vendor identification works without extra Salesforce setup.
- **Invoice / PO / Ticket numbers** follow realistic in-house formats so entity-extraction has something to grab.
- **Dates** are in **April 2026** (current dev timeline). Adjust if testing later.

## Counts

- `triage/` — 5 emails
- `query_types/` — 6 emails
- `routing/` — 6 emails
- `investigations/` — 5 emails

Total: 22 sample emails covering the full pipeline behaviour matrix.
