# VQMS API Testing Guide

Ready-to-use examples for testing every endpoint in Swagger UI.
Copy-paste the JSON bodies directly into the Swagger form fields.

Last updated: 2026-04-14

---

## TABLE OF CONTENTS

1. [Setup — Login and Authorize](#1-setup--login-and-authorize)
2. [POST /queries — 5 Test Examples](#2-post-queries--5-test-examples)
3. [GET /queries/{query_id} — Check Status](#3-get-queriesquery_id--check-status)
4. [GET /vendors — List Vendors](#4-get-vendors--list-vendors)
5. [GET /emails — Email Dashboard](#5-get-emails--email-dashboard)
6. [POST /auth/logout — End Session](#6-post-authlogout--end-session)
7. [Understanding X-Vendor-ID](#7-understanding-x-vendor-id)
8. [Expected Responses Reference](#8-expected-responses-reference)
9. [Common Errors and Fixes](#9-common-errors-and-fixes)

---

## 1. Setup — Login and Authorize

Before testing any protected endpoint, you need a JWT token.

### Step 1: Login

**Endpoint:** POST /auth/login
**Body:**
```json
{
  "username_or_email": "admin_user",
  "password": "admin123"
}
```

**Expected Response (200):**
```json
{
  "token": "eyJhbGciOiJIUzI1NiIs...",
  "user_name": "admin_user",
  "email": "admin@vqms.local",
  "role": "ADMIN",
  "tenant": "hexaware",
  "vendor_id": null
}
```

### Step 2: Authorize

1. Copy the `token` value from the response (just the token, not the quotes)
2. Click the **Authorize** button (top-right of Swagger UI)
3. Paste the token into the "Value" field
4. Click **Authorize**, then **Close**

Now every request will automatically include `Authorization: Bearer <your-token>`.

---

## 2. POST /queries — 5 Test Examples

### How POST /queries Works

```
  You fill in two things:
    1. X-Vendor-ID header  — WHO is submitting (which vendor)
    2. Request body        — WHAT they're asking (the query)

  The system:
    1. Validates the body (Pydantic checks)
    2. Computes SHA-256 hash of (vendor_id + subject + description)
    3. Checks if that hash already exists (idempotency)
    4. If new: generates VQ-2026-XXXX ID, saves to DB, publishes events
    5. Returns 201 with the query_id
```

### Available Vendor IDs

Pick any of these for the `X-Vendor-ID` header. Each is a real
Salesforce Account ID from your vendor list:

```
  Vendor Name                  ID (use as X-Vendor-ID)       Tier
  ─────────────────────────    ──────────────────────────    ──────────
  Acme Industrial Supplies     001al00002Ie1zjAAB            GOLD
  TechNova Solutions           001al00002Ie1zkAAB            SILVER
  SwiftLog Freight             001al00002Ie1zlAAB            PLATINUM
  GreenBuild Facilities        001al00002Ie1zmAAB            SILVER
  DataPrime Analytics          001al00002Ie1znAAB            SILVER
  SecureGuard Services         001al00002Ie1zsAAB            SILVER
  Catalyst Consulting          001al00002Ie1zqAAB            SILVER
  CloudWave Technologies       001al00002Ie1zuAAB            GOLD
  StratEdge Advisors           001al00002Ie200AAB            PLATINUM
  ByteForge Software           001al00002Ie204AAB            GOLD
```

### Request Body Fields

```
  Field              Required?   Rules
  ────────────────   ─────────   ─────────────────────────────────────
  query_type         Yes         Any string (e.g., Invoice, Delivery)
  subject            Yes         5-500 characters
  description        Yes         10-5000 characters
  priority           No          LOW | MEDIUM | HIGH | CRITICAL (default: MEDIUM)
  reference_number   No          Any string (invoice #, PO #, etc.)
```

---

### Example 1: Invoice Payment Query

A vendor asking about a pending invoice payment.

**X-Vendor-ID:** `001al00002Ie1zjAAB` (Acme Industrial Supplies)

**Body:**
```json
{
  "query_type": "Invoice",
  "subject": "Payment pending for invoice INV-2026-0891",
  "description": "We submitted invoice INV-2026-0891 on March 5th for 125000 USD covering raw material supply for Q1 2026. The payment terms are Net-45 and the due date was April 19th. We have not received payment yet. Please confirm the payment status and expected date of remittance.",
  "priority": "HIGH",
  "reference_number": "INV-2026-0891"
}
```

**Expected Response (201):**
```json
{
  "query_id": "VQ-2026-XXXX",
  "status": "RECEIVED"
}
```

**What happens behind the scenes:**
1. Pydantic validates all fields
2. SHA-256 hash computed: hash(001al00002Ie1zjAAB + subject + description)
3. Idempotency check: INSERT into cache.idempotency_keys
4. Query ID generated: VQ-2026-XXXX (random 4-digit suffix)
5. Case created in workflow.case_execution (status=RECEIVED, source=portal)
6. EventBridge event published: QueryReceived
7. SQS message enqueued to vqms-query-intake-queue

---

### Example 2: Delivery/Shipping Query

A logistics vendor asking about a GRN confirmation.

**X-Vendor-ID:** `001al00002Ie1zlAAB` (SwiftLog Freight)

**Body:**
```json
{
  "query_type": "Delivery",
  "subject": "GRN confirmation needed for shipment SLF-SHP-2026-0344",
  "description": "We shipped 500 units of industrial valves against PO-2026-0344 on March 15th via our logistics network. Our tracking system shows delivery was completed on March 18th at your Mumbai warehouse (Dock 3, received by Mr. Patel). However, we have not received the Goods Receipt Note (GRN) which is required before we can raise the invoice. Could you please confirm receipt and share the GRN?",
  "priority": "MEDIUM",
  "reference_number": "PO-2026-0344"
}
```

---

### Example 3: Contract Renewal Query

A consulting vendor asking about their contract status.

**X-Vendor-ID:** `001al00002Ie1zqAAB` (Catalyst Consulting)

**Body:**
```json
{
  "query_type": "Contract",
  "subject": "Contract CNT-V-008-2025 renewal status for FY 2026-27",
  "description": "Our current consulting services contract CNT-V-008-2025 expires on April 30th 2026. We submitted the renewal proposal with updated rate card on March 10th to your procurement team. We have not heard back yet and would like to understand the renewal timeline. Our team is planning resource allocation for May onwards and needs clarity on whether the engagement will continue. Please share the status of the renewal review.",
  "priority": "HIGH",
  "reference_number": "CNT-V-008-2025"
}
```

---

### Example 4: Technical Support Query (Critical)

An IT vendor reporting a service outage.

**X-Vendor-ID:** `001al00002Ie1zuAAB` (CloudWave Technologies)

**Body:**
```json
{
  "query_type": "Technical",
  "subject": "URGENT - Cloud hosting service degradation since 8 AM IST",
  "description": "Our monitoring systems are showing degraded performance on the dedicated cloud hosting environment provisioned for your data analytics workloads (Environment ID: CW-PROD-HEX-042). CPU utilization has spiked to 98% and response times have increased from 200ms to 3500ms since 8:00 AM IST today. We have identified a potential root cause related to a runaway batch job and need authorization from your IT team to restart the affected pods. This is impacting your real-time dashboards. Please provide approval urgently.",
  "priority": "CRITICAL",
  "reference_number": "CW-PROD-HEX-042"
}
```

---

### Example 5: General Inquiry (Low Priority)

A vendor asking about onboarding a new contact.

**X-Vendor-ID:** `001al00002Ie1znAAB` (DataPrime Analytics)

**Body:**
```json
{
  "query_type": "General",
  "subject": "Adding new billing contact for DataPrime Analytics account",
  "description": "We have recently restructured our finance team and would like to update the billing contact for our account. The new billing contact is Ms. Priya Sharma (priya.sharma@dataprime.com, +91-9876543210). She will be the primary point of contact for all invoice-related communications going forward. Our previous billing contact Mr. Rajesh Kumar has moved to a different division. Please update your records accordingly.",
  "priority": "LOW",
  "reference_number": null
}
```

---

## 3. GET /queries/{query_id} — Check Status

After submitting a query, use the returned `query_id` to check its status.

### How It Works

```
  GET /queries/VQ-2026-1234
  Headers:
    Authorization: Bearer <your-token>
    X-Vendor-ID: 001al00002Ie1zjAAB    <- MUST match the vendor who submitted
```

### What is X-Vendor-ID here?

The GET endpoint uses X-Vendor-ID as an **ownership check**. It queries:

```sql
  SELECT ... FROM workflow.case_execution
  WHERE query_id = $1 AND vendor_id = $2
```

This means:
- Vendor A can only see Vendor A's queries
- If you use a different X-Vendor-ID than the one used to submit, you get 404
- In production, vendor_id comes from JWT claims (no header needed)

### Step-by-Step

1. Submit a query using Example 1 above (POST /queries)
2. Copy the `query_id` from the 201 response (e.g., `VQ-2026-4821`)
3. Open **GET /queries/{query_id}**
4. Enter the `query_id` in the path parameter field
5. Enter the **same X-Vendor-ID** you used to submit
6. Click Execute

### Expected Response (200)

```json
{
  "query_id": "VQ-2026-4821",
  "status": "RECEIVED",
  "source": "portal",
  "processing_path": null,
  "created_at": "2026-04-14 11:53:05.748016",
  "updated_at": "2026-04-14 11:53:05.748016"
}
```

### Field Explanations

```
  Field             What It Means
  ────────────────  ──────────────────────────────────────────────────
  query_id          Unique ID assigned by the system (VQ-YYYY-NNNN)
  status            Current workflow status:
                      RECEIVED        — just submitted, waiting for AI
                      ANALYZING       — Query Analysis Agent is running
                      ROUTING         — routing rules being applied
                      DRAFTING        — response email being generated
                      VALIDATING      — quality gate checking the draft
                      SENDING         — email being sent to vendor
                      RESOLVED        — vendor got a resolution (Path A)
                      AWAITING_TEAM   — waiting for human team (Path B)
                      AWAITING_REVIEW — waiting for human reviewer (Path C)
                      CLOSED          — done
  source            How the query arrived: "portal" or "email"
  processing_path   Which path the AI chose: "A", "B", "C", or null
                    (null means the AI hasn't analyzed it yet)
  created_at        When the query was submitted (IST)
  updated_at        Last status change (IST)
```

### Error Cases

| Scenario | Response |
|----------|----------|
| Wrong query_id | 404 `{"detail": "Query not found"}` |
| Wrong X-Vendor-ID (not the submitter) | 404 `{"detail": "Query not found"}` |
| No Authorization header | 401 `{"detail": "Not authenticated"}` |
| Database down | 503 `{"detail": "Database unavailable"}` |

---

## 4. GET /vendors — List Vendors

No parameters needed. Just click Execute.

**Expected:** Array of 25 vendor objects from Salesforce, each with:
- `id` — Salesforce Account ID (use this as X-Vendor-ID)
- `name` — Company name
- `vendor_id` — Internal code (V-001 to V-025)
- `vendor_tier` — PLATINUM, GOLD, SILVER, or BRONZE
- `category` — Raw Materials, IT Services, Logistics, etc.
- `sla_response_hours` — SLA target based on tier
- `billing_city`, `billing_state`, `billing_country`

---

## 5. GET /emails — Email Dashboard

### Basic (no filters)

Just click Execute with defaults:
- `page`: 1
- `page_size`: 20
- `sort_by`: timestamp
- `sort_order`: desc

### With Filters

| Parameter | Value | What It Does |
|-----------|-------|-------------|
| `status` | `New` | Only show unresolved emails |
| `status` | `Resolved` | Only show resolved emails |
| `priority` | `High` | Only high-priority emails |
| `search` | `invoice` | Search in subject and sender email |
| `sort_by` | `priority` | Sort by priority instead of date |

### Response Structure

```json
{
  "total": 3,
  "page": 1,
  "page_size": 20,
  "mail_chains": [
    {
      "conversation_id": "AAQkADhh...",
      "mail_items": [
        {
          "query_id": "VQ-2026-1175",
          "sender": {"name": "Rohit Magdum", "email": "rohitmagdum1306@gmail.com"},
          "subject": "Invoice Submission – CC/2026-27/0291...",
          "body": "Dear Accounts Payable Team...",
          "timestamp": "2026-04-13T23:10:18",
          "attachments": [
            {
              "attachment_id": "AAMkADhh...",
              "filename": "Invoice_CC-2026-27-0291.pdf",
              "content_type": "application/pdf",
              "size_bytes": 4936,
              "file_format": "PDF"
            }
          ],
          "thread_status": "NEW"
        }
      ],
      "status": "New",
      "priority": "Medium"
    }
  ]
}
```

---

## 6. POST /auth/logout — End Session

Just click Execute. No body needed.
The Authorization header (set by the Authorize button) provides the token.

**Expected Response (200):**
```json
{
  "message": "Logged out successfully"
}
```

After logout, the token is blacklisted. Any subsequent request with that
token returns 401 "Invalid or expired token". You'll need to login again.

---

## 7. Understanding X-Vendor-ID

### What Is It?

X-Vendor-ID is a request header that identifies **which vendor** is making
the request. It's the Salesforce Account ID of the vendor.

### Why Does It Exist?

```
  IN PRODUCTION:
    Vendor logs into Angular portal via Cognito
    Cognito JWT contains: { "vendor_id": "001al00002Ie1zjAAB", ... }
    The API extracts vendor_id FROM the JWT claims
    No X-Vendor-ID header needed

  IN DEV MODE (Swagger UI):
    We log in as admin_user (not a real vendor)
    Admin JWT has vendor_id = null
    So we pass X-Vendor-ID as a header to simulate a vendor
    The API reads it from the header instead of JWT
```

### Where Do I Get the Value?

From **GET /vendors** response. Each vendor has an `id` field:

```json
{
  "id": "001al00002Ie1zjAAB",       <-- THIS is the X-Vendor-ID
  "name": "Acme Industrial Supplies",
  "vendor_id": "V-001"               <-- this is just a display code
}
```

**Important:** Use the `id` field (Salesforce Account ID), NOT the `vendor_id` field.

### What Does It Do in Each Endpoint?

```
  POST /queries:
    Used to create the query — stored as vendor_id in
    workflow.case_execution. Links the query to this vendor.

  GET /queries/{query_id}:
    Used as an ownership check — the query's vendor_id
    in the database must match this header. Prevents
    Vendor A from seeing Vendor B's queries.
```

---

## 8. Expected Responses Reference

| Endpoint | Success | Duplicate | Not Found | Unauthorized | Validation Error |
|----------|---------|-----------|-----------|-------------|-----------------|
| POST /auth/login | 200 + JWT | — | — | 401 bad credentials | 422 missing fields |
| POST /auth/logout | 200 | — | — | 401 no token | — |
| POST /queries | 201 + query_id | 409 | — | 401 | 422 subject too short |
| GET /queries/{id} | 200 + status | — | 404 | 401 | — |
| GET /vendors | 200 + array | — | — | 401 | — |
| GET /emails | 200 + chains | — | — | 401 | 422 bad filter |

---

## 9. Common Errors and Fixes

### 401 "Not authenticated"

**Cause:** No Bearer token in the request.
**Fix:** Click the Authorize button and paste your JWT token from login.

### 401 "Invalid or expired token"

**Cause:** Token expired (30 min) or you logged out.
**Fix:** Login again (POST /auth/login) and re-authorize with the new token.

### 404 "Query not found"

**Cause:** Either the query_id doesn't exist, OR you used a different
X-Vendor-ID than the one used to submit the query.
**Fix:** Use the same X-Vendor-ID for both POST and GET.

### 409 "Duplicate query"

**Cause:** You submitted a query with the same vendor + subject + description
as a previous query. The idempotency check caught it.
**Fix:** Change the subject or description to submit a new query.

### 422 Validation Error

**Cause:** Request body fails Pydantic validation.
**Common issues:**
- Subject too short (minimum 5 characters)
- Description too short (minimum 10 characters)
- Invalid priority (must be LOW, MEDIUM, HIGH, or CRITICAL)
**Fix:** Check the error message for which field failed.

### 500 Internal Server Error

**Cause:** Something broke on the server.
**Fix:** Check the terminal running the server for the full traceback.
Common causes: database disconnected, Salesforce credentials expired.

### 502 "Salesforce query failed"

**Cause:** Salesforce API returned an error.
**Fix:** Check Salesforce credentials in .env. The session token may have expired.

### 503 "Service unavailable"

**Cause:** A required service (PostgreSQL, S3, SQS) failed to connect at startup.
**Fix:** Check the startup logs in the terminal. Restart the server after
fixing the connection issue.
