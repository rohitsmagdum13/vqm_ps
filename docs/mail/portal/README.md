# Portal Test Queries

Sample portal submissions — one or two per query type — for end-to-end pipeline testing. Each file under this folder is an array of ready-to-POST JSON bodies that match the `QuerySubmission` Pydantic model in [src/models/query.py](../../../src/models/query.py).

## Will portal submissions show in the timeline?

Yes. After the SQS-consumer wiring in [app/lifespan.py](../../../app/lifespan.py), every portal submission flows through:

```
POST /queries
  → PortalIntakeService writes case_execution + intake.portal_queries rows
  → trail row "intake/received" written immediately
  → SQS message enqueued on vqms-query-intake-queue
  → PipelineConsumer (long-poll) picks it up
  → LangGraph runs every node, each writes a trail row via the wrapper
  → @log_llm_call writes an "llm_call" sub-step row per LLM call
  → Delivery node parks Path A at PENDING_APPROVAL
```

While that's running, open `/queries/<VQ-id>` as an admin and the **Pipeline timeline** section polls every 3 s and renders each step live (✓/✗/… status badge, duration, expandable JSON details).

---

## How to submit a sample

### Prerequisites

1. The seed script has run — KB articles are in `memory.embedding_index`:
   ```
   uv run python scripts/seed_knowledge_base.py
   ```
   Without this, `kb_search` always returns 0 matches and **every** query is forced to **Path B** (acknowledgment auto-sent, no `PENDING_APPROVAL`).

2. Backend running (`uv run uvicorn main:app --reload`) — startup logs must include `Pipeline consumer started` and `Execution Trail Service ready`.

3. A vendor JWT for `X-Vendor-ID = V-001` (or whichever vendor in your `tbl_users` table). Get one from `POST /auth/login`.

### curl

```bash
TOKEN=eyJhbGciOiJIUzI1NiIs...
JSON=$(jq -c '.samples[0]' docs/mail/portal/01_invoice_payment.json)

curl -s -X POST http://localhost:8000/queries \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Vendor-ID: V-001" \
  -H "Content-Type: application/json" \
  -d "$JSON"
```

The response is `{ "query_id": "VQ-2026-XXXX", "status": "RECEIVED", "created_at": "..." }`. Open `http://localhost:4200/queries/VQ-2026-XXXX` to watch the timeline.

### PowerShell

```powershell
$body = (Get-Content docs/mail/portal/01_invoice_payment.json | ConvertFrom-Json).samples[0] | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8000/queries `
  -Headers @{ Authorization = "Bearer $token"; "X-Vendor-ID" = "V-001" } `
  -ContentType "application/json" `
  -Body $body
```

### Wizard

If you'd rather paste into the UI, copy `subject`, `description`, `priority`, and `reference_number` from any sample into the New Query wizard at `/wizard`.

---

## What each sample is designed to do

Every JSON file has 1–2 entries with an `expected_path` annotation:

| `expected_path` | What you should see in the timeline |
|---|---|
| `A` | KB match ≥ 0.80 → `path_decision/path_a` → `resolution` (with `llm_call` sub-row) → `quality_gate/passed` → `delivery/pending_approval`. Status parks at `PENDING_APPROVAL` until an admin approves at `/admin/draft-approvals`. |
| `B` | KB miss → `path_decision/path_b` → `acknowledgment` → `delivery/ack_email_sent`. Status flips to `AWAITING_RESOLUTION`. Email sent. |
| `C` | Confidence < 0.85 → `triage/paused`. Status `PAUSED`. Visible at `/admin/triage`. |

The `expected_path` field is **only documentation** — the AI decides at runtime, so a query labelled `A` may legitimately fall to `B` if the LLM analyses confidence below threshold or KB scores below 0.80.

---

## How to tell where the pipeline failed

Open `/queries/<id>` and read the trail bottom-up. The **last** row tells you where it stopped.

| Last row | Diagnosis |
|---|---|
| `intake/received` | SQS message stuck — consumer not running or DLQ. Check `Pipeline consumer started` log. |
| `query_analysis/failed` | LLM error (Bedrock 4xx/5xx, OpenAI fallback also failed, or JSON parse failure). Expand details for `error_type`. |
| `kb_search/success` with `total_matches: 0` for every query | KB is empty — run `seed_knowledge_base.py`. |
| `path_decision/path_b` for queries you expected to be Path A | KB articles weren't a strong-enough match. Lower `KB_MATCH_THRESHOLD` in `.env` or improve KB content. |
| `quality_gate/failed` | LLM output failed the 7-check gate. Expand `failed_checks` (e.g. `missing_sections:next_steps`). Check the prompt template. |
| `delivery/delivery_failed` | ServiceNow create failed OR Graph send failed. Expand for `error`. |
| `delivery/pending_approval` | Path A success — case is correctly waiting for admin approval. |
| `triage/paused` (Path C) | Confidence < 0.85 — go to `/admin/triage` to review. |

---

## Files

- [01_invoice_payment.json](01_invoice_payment.json)
- [02_purchase_order.json](02_purchase_order.json)
- [03_delivery_shipment.json](03_delivery_shipment.json)
- [04_contract_query.json](04_contract_query.json)
- [05_return_refund.json](05_return_refund.json)
- [06_general_inquiry.json](06_general_inquiry.json)
- [07_catalog_pricing.json](07_catalog_pricing.json)
- [08_sla_breach_report.json](08_sla_breach_report.json)
- [09_compliance_audit.json](09_compliance_audit.json)
- [10_technical_support.json](10_technical_support.json)
- [11_onboarding.json](11_onboarding.json)
- [12_quality_issue.json](12_quality_issue.json)
- [submit_sample.ps1](submit_sample.ps1) — one-liner helper to POST any sample
