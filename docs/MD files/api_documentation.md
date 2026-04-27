# VQMS API Documentation

Complete reference for every API endpoint in the Vendor Query
Management System. Covers authentication, inputs, outputs,
error codes, and internal flow for each endpoint.

---

## Table of Contents

1. [How Authentication Works](#1-how-authentication-works)
2. [API Endpoint Summary Table](#2-api-endpoint-summary-table)
3. [POST /auth/login](#3-post-authlogin)
4. [POST /auth/logout](#4-post-authlogout)
5. [GET /vendors](#5-get-vendors)
6. [POST /vendors (Create)](#6-post-vendors-create)
7. [PUT /vendors/{vendor_id}](#7-put-vendorsvendor_id)
8. [DELETE /vendors/{vendor_id}](#8-delete-vendorsvendor_id)
9. [POST /queries](#9-post-queries)
10. [GET /queries/{query_id}](#10-get-queriesquery_id)
11. [GET /emails](#11-get-emails)
12. [GET /emails/stats](#12-get-emailsstats)
13. [GET /emails/{query_id}](#13-get-emailsquery_id)
14. [GET /emails/{query_id}/attachments/{attachment_id}/download](#14-get-attachment-download)
15. [POST /webhooks/ms-graph](#15-post-webhooksms-graph)
16. [GET /health](#16-get-health)
17. [Security Headers](#17-security-headers)
18. [Error Code Reference](#18-error-code-reference)

---

## 1. How Authentication Works

### The Big Picture

VQMS uses JWT (JSON Web Token) for authentication. Think of it
like a movie ticket — you buy it once (login), show it at every
screen (API call), and it expires after a set time.

```
+------------------------------------------------------------------+
|                    AUTHENTICATION FLOW                            |
|                                                                  |
|                                                                  |
|   STEP 1: LOGIN                                                  |
|   ~~~~~~~~~~~~~~                                                 |
|                                                                  |
|   You (Client)                          Server                   |
|       |                                    |                     |
|       |   POST /auth/login                 |                     |
|       |   { username, password }           |                     |
|       |----------------------------------->|                     |
|       |                                    |                     |
|       |                        +-----------+-----------+         |
|       |                        | 1. Find user in DB    |         |
|       |                        | 2. Check password     |         |
|       |                        | 3. Look up role       |         |
|       |                        | 4. Create JWT token   |         |
|       |                        +-----------+-----------+         |
|       |                                    |                     |
|       |   { token: "eyJhbG...",            |                     |
|       |     user_name: "admin_user",       |                     |
|       |     role: "ADMIN" }                |                     |
|       |<-----------------------------------|                     |
|       |                                    |                     |
|                                                                  |
|   STEP 2: USE THE TOKEN                                          |
|   ~~~~~~~~~~~~~~~~~~~~~                                          |
|                                                                  |
|   You (Client)                          Server                   |
|       |                                    |                     |
|       |   GET /vendors                     |                     |
|       |   Authorization: Bearer eyJhbG...  |                     |
|       |----------------------------------->|                     |
|       |                                    |                     |
|       |                        +-----------+-----------+         |
|       |                        | AuthMiddleware:       |         |
|       |                        |  1. Extract token     |         |
|       |                        |  2. Decode JWT        |         |
|       |                        |  3. Check blacklist   |         |
|       |                        |  4. Check expiry      |         |
|       |                        |  5. Set user context  |         |
|       |                        +-----------+-----------+         |
|       |                                    |                     |
|       |   200 OK + vendor data             |                     |
|       |<-----------------------------------|                     |
|       |                                    |                     |
|                                                                  |
|   STEP 3: LOGOUT                                                 |
|   ~~~~~~~~~~~~~~                                                 |
|                                                                  |
|   You (Client)                          Server                   |
|       |                                    |                     |
|       |   POST /auth/logout                |                     |
|       |   Authorization: Bearer eyJhbG...  |                     |
|       |----------------------------------->|                     |
|       |                                    |                     |
|       |                        +-----------+-----------+         |
|       |                        | 1. Decode JWT         |         |
|       |                        | 2. Extract jti (ID)   |         |
|       |                        | 3. Save jti to        |         |
|       |                        |    blacklist table     |         |
|       |                        |    (PostgreSQL)        |         |
|       |                        +-----------+-----------+         |
|       |                                    |                     |
|       |   { "message": "Logged out" }      |                     |
|       |<-----------------------------------|                     |
|       |                                    |                     |
|       |                                    |                     |
|       |   GET /vendors (same token)        |                     |
|       |----------------------------------->|                     |
|       |   401 Unauthorized (blacklisted!)  |                     |
|       |<-----------------------------------|                     |
|                                                                  |
+------------------------------------------------------------------+
```

### What's Inside a JWT Token?

When you decode a JWT, it contains these fields (called "claims"):

```
+-------------------------------------------------------+
|                    JWT TOKEN PAYLOAD                   |
+-------------------------------------------------------+
|                                                       |
|   {                                                   |
|     "sub":    "admin_user",     <-- username           |
|     "role":   "ADMIN",         <-- user role           |
|     "tenant": "hexaware",      <-- organization        |
|     "exp":    1776160401.3,    <-- expires at (unix)    |
|     "iat":    1776158601.3,    <-- issued at (unix)     |
|     "jti":    "a3e06942-..."   <-- unique token ID      |
|   }                                                   |
|                                                       |
|   Token lifetime: 30 minutes (1800 seconds)           |
|   Algorithm: HMAC-SHA256                              |
|   Secret: from JWT_SECRET_KEY in .env                 |
|                                                       |
+-------------------------------------------------------+
```

### Auto Token Refresh

If your token is about to expire (within 5 minutes), the server
automatically creates a new token and sends it back in the
response header. Your frontend should watch for this header.

```
+---------------------------------------------------------+
|                 TOKEN AUTO-REFRESH                       |
+---------------------------------------------------------+
|                                                         |
|   Request comes in with token that expires in 3 min     |
|                                                         |
|       Client                           Server           |
|         |                                 |             |
|         |  GET /vendors                   |             |
|         |  Authorization: Bearer <token>  |             |
|         |-------------------------------->|             |
|         |                                 |             |
|         |                     +-----------+--------+    |
|         |                     | Token expires in   |    |
|         |                     | 3 min (< 5 min)    |    |
|         |                     | --> Create new JWT  |    |
|         |                     +--------------------+    |
|         |                                 |             |
|         |  200 OK                         |             |
|         |  X-New-Token: eyJhbG...NEW      |             |
|         |  Body: [vendor data]            |             |
|         |<--------------------------------|             |
|         |                                 |             |
|         |  (Frontend saves new token,     |             |
|         |   uses it for next request)     |             |
|                                                         |
+---------------------------------------------------------+
```

### Which Paths Skip Authentication?

The middleware does NOT check tokens for these paths:

```
+------------------------------------+----------------------------+
|  Path                              |  Why It's Skipped          |
+------------------------------------+----------------------------+
|  /health                           |  Load balancer checks      |
|  /auth/login                       |  Need to login first!      |
|  /docs                             |  Swagger UI page           |
|  /openapi.json                     |  Swagger schema            |
|  /redoc                            |  ReDoc page                |
|  /webhooks/*                       |  MS Graph notifications    |
+------------------------------------+----------------------------+
|  Everything else                   |  REQUIRES Bearer token     |
+------------------------------------+----------------------------+
```

### How the Token Blacklist Works

When you logout, the token's unique ID (jti) is saved in the
database. Every future request checks this blacklist.

```
+-----------------------------------------------------------+
|               TOKEN BLACKLIST (PostgreSQL)                 |
+-----------------------------------------------------------+
|                                                           |
|  Table: cache.kv_store                                    |
|                                                           |
|  +------------------------------------------+--------+   |
|  | key                                      | expiry |   |
|  +------------------------------------------+--------+   |
|  | vqms:auth:blacklist:a3e06942-3d1b-...    | 30min  |   |
|  | vqms:auth:blacklist:f7b21cc4-8e3a-...    | 30min  |   |
|  +------------------------------------------+--------+   |
|                                                           |
|  - Key format: vqms:auth:blacklist:<jti>                  |
|  - TTL matches token lifetime (auto-cleanup)              |
|  - No Redis needed — PostgreSQL handles it                |
|                                                           |
+-----------------------------------------------------------+
```

### Database Tables Used by Auth

```
+------------------------------------------------------------------+
|                                                                  |
|   public.tbl_users                    public.tbl_user_roles      |
|   +-----------------+                 +-------------------+      |
|   | id (PK)         |                 | slno (PK)         |      |
|   | user_name       |---+             | user_name         |      |
|   | email_id        |   |             | email_id          |      |
|   | tenant          |   +------------>| tenant            |      |
|   | password (hash) |   (matched by   | role              |      |
|   | status          |   user_name     | first_name        |      |
|   | security_q1..q3 |   + tenant)     | last_name         |      |
|   | security_a1..a3 |                 | created_by        |      |
|   +-----------------+                 | created_date      |      |
|                                       | modified_by       |      |
|   Passwords stored as                 | modified_date     |      |
|   werkzeug scrypt hash                +-------------------+      |
|   (never returned in API)                                        |
|                                       Roles: ADMIN, VENDOR,      |
|                                       REVIEWER                   |
|                                                                  |
+------------------------------------------------------------------+
```

---

## 2. API Endpoint Summary Table

```
+------+---------------------------------------------------+-----------+-----------+------------------+
| #    | Endpoint                                          | Auth      | Role      | Purpose          |
+------+---------------------------------------------------+-----------+-----------+------------------+
|  1   | POST   /auth/login                                | None      | Any       | Get JWT token    |
|  2   | POST   /auth/logout                               | Bearer    | Any       | Invalidate token |
|  3   | GET    /vendors                                   | Bearer    | ADMIN     | List vendors (sorted V-001..V-NNN)    |
|  4   | POST   /vendors                                   | Bearer    | ADMIN     | Create vendor (returns full record)   |
|  5   | PUT    /vendors/{vendor_id}                       | Bearer    | ADMIN     | Update vendor (returns full record)   |
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

---

## 3. POST /auth/login

**Purpose:** Authenticate a user and get a JWT token.

### Request

```
POST /auth/login
Content-Type: application/json

{
    "username_or_email": "admin_user",     <-- username OR email
    "password": "admin123"                 <-- plain text password
}
```

### What Happens Inside

```
+---------------------------------------------------------------+
|  POST /auth/login  INTERNAL FLOW                              |
+---------------------------------------------------------------+
|                                                               |
|  1. Receive { username_or_email, password }                   |
|                      |                                        |
|                      v                                        |
|  2. Query PostgreSQL:                                         |
|     SELECT * FROM tbl_users                                   |
|     WHERE user_name = $1 OR email_id = $1                     |
|                      |                                        |
|               +------+------+                                 |
|               |             |                                 |
|           Not found      Found                                |
|               |             |                                 |
|         401 "Invalid    3. Check status == "ACTIVE"            |
|          credentials"      |                                  |
|                      +-----+------+                           |
|                      |            |                            |
|                  INACTIVE       ACTIVE                         |
|                      |            |                            |
|                401 "Account   4. Verify password               |
|                 is inactive"     (werkzeug hash check          |
|                                   in background thread)       |
|                                   |                           |
|                            +------+------+                    |
|                            |             |                    |
|                        Wrong           Correct                |
|                            |             |                    |
|                      401 "Invalid    5. Query tbl_user_roles  |
|                       credentials"      for role              |
|                                         |                     |
|                                  6. Create JWT with:          |
|                                     sub = username            |
|                                     role = ADMIN/VENDOR/etc   |
|                                     tenant = hexaware         |
|                                     exp = now + 30 min        |
|                                     jti = random UUID         |
|                                         |                     |
|                                  7. Return LoginResponse      |
|                                                               |
+---------------------------------------------------------------+
```

### Successful Response (200)

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

### Error Responses

```
+--------+------------------------------+----------------------------+
| Status | Body                         | Cause                      |
+--------+------------------------------+----------------------------+
|  401   | {"detail":"Invalid           | User not found OR          |
|        |  credentials"}               | wrong password             |
+--------+------------------------------+----------------------------+
|  401   | {"detail":"Account is        | User status is not         |
|        |  inactive"}                  | "ACTIVE" in tbl_users      |
+--------+------------------------------+----------------------------+
|  422   | {"detail":[...validation...]}| Missing username_or_email  |
|        |                              | or password field          |
+--------+------------------------------+----------------------------+
```

### Files Involved

```
Request  -->  src/api/routes/auth.py      (login endpoint)
              src/services/auth.py        (authenticate_user function)
              src/models/auth.py          (LoginRequest, LoginResponse)
              src/cache/cache_client.py   (blacklist check)
              src/db/connection.py        (PostgreSQL queries)
```

---

## 4. POST /auth/logout

**Purpose:** Invalidate the current JWT token so it can't be reused.

### Request

```
POST /auth/logout
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

No request body needed. The token comes from the Authorization header.

### What Happens Inside

```
+---------------------------------------------------------------+
|  POST /auth/logout  INTERNAL FLOW                             |
+---------------------------------------------------------------+
|                                                               |
|  1. Extract token from "Authorization: Bearer <token>"        |
|                      |                                        |
|               +------+------+                                 |
|               |             |                                 |
|          No Bearer       Has token                            |
|               |             |                                 |
|         401 "No token   2. Decode JWT                         |
|          provided"         |                                  |
|                      3. Extract jti (unique token ID)         |
|                            |                                  |
|                      4. Save to blacklist:                    |
|                         cache.kv_store                        |
|                         key = "vqms:auth:blacklist:<jti>"     |
|                         ttl = remaining token lifetime        |
|                            |                                  |
|                      5. Return success                        |
|                                                               |
+---------------------------------------------------------------+
```

### Successful Response (200)

```json
{
    "message": "Logged out successfully"
}
```

### Error Responses

```
+--------+------------------------------+----------------------------+
| Status | Body                         | Cause                      |
+--------+------------------------------+----------------------------+
|  401   | {"detail":"No token          | Missing Authorization      |
|        |  provided"}                  | header                     |
+--------+------------------------------+----------------------------+
|  400   | {"detail":"..."}             | Token decode failed        |
+--------+------------------------------+----------------------------+
```

---

## 5. GET /vendors

**Purpose:** Get all active vendors from the Salesforce Vendor_Account__c custom object.

**Role Required:** ADMIN only (403 for VENDOR/REVIEWER)

### Request

```
GET /vendors
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

No query parameters. Returns all vendors with status "Active",
sorted ascending by Vendor_ID__c (V-001 first, V-025 last).

### What Happens Inside

```
+---------------------------------------------------------------+
|  GET /vendors  INTERNAL FLOW                                  |
+---------------------------------------------------------------+
|                                                               |
|  1. AuthMiddleware validates JWT token                        |
|                      |                                        |
|  2. Check role == "ADMIN" (403 if not)                        |
|                      |                                        |
|  3. Route handler calls:                                      |
|     salesforce.get_all_active_vendors()                       |
|                      |                                        |
|  3. Salesforce connector runs SOQL query:                     |
|     SELECT Id, Name, Vendor_ID__c, Website__c, ...            |
|     FROM Vendor_Account__c                                    |
|     WHERE Vendor_Status__c = 'Active'                         |
|     ORDER BY Vendor_ID__c ASC                                 |
|                      |                                        |
|     (Uses asyncio.to_thread because                           |
|      simple-salesforce is synchronous)                        |
|                      |                                        |
|  4. Map Salesforce field names to Python snake_case:          |
|     Id                  --> id                                |
|     Name                --> name                              |
|     Vendor_ID__c        --> vendor_id                         |
|     Vendor_Tier__c      --> vendor_tier                       |
|     City__c             --> billing_city                      |
|     State__c            --> billing_state                     |
|     Country__c          --> billing_country                   |
|     Website__c          --> website                           |
|     Annual_Revenue__c   --> annual_revenue                    |
|     ... etc                                                   |
|                      |                                        |
|  5. Return list of VendorAccountData objects                  |
|                                                               |
+---------------------------------------------------------------+
```

### Successful Response (200)

```json
[
    {
        "id": "001al00002Ie1zjAAB",
        "name": "TechNova Solutions",
        "vendor_id": "V-001",
        "website": "https://technova.com",
        "vendor_tier": "Platinum",
        "category": "IT Services",
        "payment_terms": "Net 30",
        "annual_revenue": 5000000.0,
        "sla_response_hours": 4.0,
        "sla_resolution_days": 2.0,
        "vendor_status": "Active",
        "onboarded_date": "2024-01-15",
        "billing_city": "Mumbai",
        "billing_state": "Maharashtra",
        "billing_country": "India"
    },
    {
        "id": "001al00002Ie1zsAAB",
        "name": "Acme Corp",
        "vendor_id": "V-002",
        ...
    }
]
```

### Response Fields Explained

```
+---------------------+----------+--------------------------------------------+
| Field               | Type     | Description                                |
+---------------------+----------+--------------------------------------------+
| id                  | string   | Salesforce Vendor_Account__c record ID     |
| name                | string   | Company name                               |
| vendor_id           | string?  | Custom vendor code (V-001, V-002, etc.)    |
| website             | string?  | Company website URL                        |
| vendor_tier         | string?  | Platinum, Gold, Silver, or Bronze          |
| category            | string?  | IT Services, Logistics, etc.               |
| payment_terms       | string?  | Net 30, Net 60, etc.                       |
| annual_revenue      | float?   | Annual revenue in USD                      |
| sla_response_hours  | float?   | Max hours to first response                |
| sla_resolution_days | float?   | Max days to resolve                        |
| vendor_status       | string?  | Active or Inactive                         |
| onboarded_date      | string?  | Date vendor was onboarded (YYYY-MM-DD)     |
| billing_city        | string?  | City                                       |
| billing_state       | string?  | State                                      |
| billing_country     | string?  | Country                                    |
+---------------------+----------+--------------------------------------------+

  ? = nullable (can be null)
```

### Error Responses

```
+--------+-----------------------------------+---------------------------+
| Status | Body                              | Cause                     |
+--------+-----------------------------------+---------------------------+
|  401   | {"detail":"Not authenticated"}    | Missing/invalid token     |
|  403   | {"detail":"Admin access required. | User role is not ADMIN    |
|        |  Your role: VENDOR"}              | (VENDOR, REVIEWER, etc.)  |
+--------+-----------------------------------+---------------------------+
|  502   | {"detail":"Salesforce query        | Salesforce API is down    |
|        |  failed"}                         | or credentials invalid    |
+--------+-----------------------------------+---------------------------+
```

### Files Involved

```
Request  -->  src/api/middleware/auth_middleware.py  (JWT check)
              src/api/routes/vendors.py             (get_all_vendors + _require_admin)
              src/adapters/salesforce.py             (get_all_active_vendors)
              src/models/vendor.py                  (VendorAccountData)
```

---

## 6. POST /vendors (Create)

**Purpose:** Create a new Vendor_Account__c record in Salesforce.
Auto-generates the next Vendor_ID__c (V-001, V-002, ...).
Returns the full vendor record after creation.

**Role Required:** ADMIN only (403 for VENDOR/REVIEWER)

### Request

```
POST /vendors
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
Content-Type: application/json

{
    "name": "NewVendor Corp",
    "website": "https://newvendor.com",
    "vendor_tier": "Silver",
    "category": "IT Services",
    "payment_terms": "Net-30",
    "annual_revenue": 5000000,
    "sla_response_hours": 12,
    "sla_resolution_days": 5,
    "vendor_status": "Active",
    "onboarded_date": "2026-04-14",
    "billing_city": "Pune",
    "billing_state": "Maharashtra",
    "billing_country": "India"
}
```

### Input Fields

```
+---------------------+----------+---------+------------------------------------+
| Field               | Required | Default | Description                        |
+---------------------+----------+---------+------------------------------------+
| name                | YES      | —       | Company name (required)            |
| website             | No       | null    | Company website URL                |
| vendor_tier         | No       | null    | Platinum, Gold, Silver, Bronze     |
| category            | No       | null    | Must match Salesforce picklist!    |
| payment_terms       | No       | null    | Must match Salesforce picklist!    |
| annual_revenue      | No       | null    | Annual revenue (number)            |
| sla_response_hours  | No       | null    | SLA response time in hours         |
| sla_resolution_days | No       | null    | SLA resolution time in days        |
| vendor_status       | No       | Active  | Active or Inactive                 |
| onboarded_date      | No       | null    | YYYY-MM-DD format                  |
| billing_city        | No       | null    | City                               |
| billing_state       | No       | null    | State                              |
| billing_country     | No       | null    | Country                            |
+---------------------+----------+---------+------------------------------------+

  NOTE: category and payment_terms are RESTRICTED PICKLISTS in
  Salesforce. You must use values that exist in the Salesforce
  picklist — arbitrary strings will cause a 502 error.
```

### How Vendor_ID__c Auto-Generation Works

```
+---------------------------------------------------------------+
|  VENDOR ID AUTO-GENERATION                                    |
+---------------------------------------------------------------+
|                                                               |
|  1. Query ALL Vendor_ID__c values from Salesforce:            |
|     SELECT Vendor_ID__c FROM Vendor_Account__c                |
|     WHERE Vendor_ID__c != null                                |
|                                                               |
|  2. Extract the number from each:                             |
|     V-001 --> 1                                               |
|     V-002 --> 2                                               |
|     ...                                                       |
|     V-025 --> 25                                              |
|                                                               |
|  3. Find the maximum: 25                                      |
|                                                               |
|  4. Next ID = V-{max+1} = V-026                              |
|     (zero-padded to 3 digits)                                 |
|                                                               |
|  5. If NO vendors exist yet: returns V-001                    |
|                                                               |
+---------------------------------------------------------------+
```

### What Happens Inside

```
+---------------------------------------------------------------+
|  POST /vendors  INTERNAL FLOW                                 |
+---------------------------------------------------------------+
|                                                               |
|  1. AuthMiddleware validates JWT token                        |
|                      |                                        |
|  2. Check role == "ADMIN" (403 if not)                        |
|                      |                                        |
|  3. Pydantic validates VendorCreateRequest                    |
|     (name is required)                                        |
|                      |                                        |
|  4. Convert Python fields to Vendor_Account__c API names:     |
|     name          --> Name                                    |
|     vendor_tier   --> Vendor_Tier__c                          |
|     billing_city  --> City__c                                 |
|     website       --> Website__c                              |
|     annual_revenue --> Annual_Revenue__c                      |
|     ... etc                                                   |
|                      |                                        |
|  5. get_next_vendor_id():                                     |
|     Query all Vendor_ID__c --> find max --> V-{max+1}         |
|                      |                                        |
|  6. Add Vendor_ID__c = "V-026" to the create data            |
|                      |                                        |
|  7. Salesforce Vendor_Account__c.create(data)                 |
|     --> returns { id: "a02NEW...", success: true }            |
|                      |                                        |
|  8. Fetch the full record back from Salesforce                |
|     SELECT all fields FROM Vendor_Account__c WHERE Id = ?     |
|                      |                                        |
|  9. Return success + full vendor record                       |
|                                                               |
+---------------------------------------------------------------+
```

### Successful Response (201)

```json
{
    "success": true,
    "salesforce_id": "a02al00000oA5XXAA0",
    "vendor_id": "V-026",
    "name": "NewVendor Corp",
    "message": "Vendor 'NewVendor Corp' created with ID V-026",
    "vendor": {
        "id": "a02al00000oA5XXAA0",
        "name": "NewVendor Corp",
        "vendor_id": "V-026",
        "website": "https://newvendor.com",
        "vendor_tier": "Silver",
        "category": "IT Services",
        "payment_terms": "Net-30",
        "annual_revenue": 5000000.0,
        "sla_response_hours": 12.0,
        "sla_resolution_days": 5.0,
        "vendor_status": "Active",
        "onboarded_date": "2026-04-14",
        "billing_city": "Pune",
        "billing_state": "Maharashtra",
        "billing_country": "India"
    }
}
```

### Error Responses

```
+--------+-----------------------------------+----------------------------+
| Status | Body                              | Cause                      |
+--------+-----------------------------------+----------------------------+
|  401   | {"detail":"Not authenticated"}    | Missing/invalid token      |
|  403   | {"detail":"Admin access required. | User role is not ADMIN     |
|        |  Your role: VENDOR"}              |                            |
|  422   | {"detail":[...validation...]}     | Missing "name" field       |
|  502   | {"detail":"Salesforce create       | Salesforce API error       |
|        |  failed: ..."}                    | (e.g., bad picklist value) |
+--------+-----------------------------------+----------------------------+
```

---

## 7. PUT /vendors/{vendor_id}

**Purpose:** Update one or more fields of a Vendor_Account__c record
in Salesforce. Returns the full vendor record after update.

**Role Required:** ADMIN only (403 for VENDOR/REVIEWER)

### Request

```
PUT /vendors/001al00002Ie1zjAAB
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
Content-Type: application/json

{
    "vendor_tier": "Gold",
    "payment_terms": "Net 45",
    "billing_city": "Pune"
}
```

You can send any combination of updatable fields. At least one
field must be provided.

### Vendor ID Formats

The endpoint accepts two formats for the vendor_id path param:

```
+--------------------------------------------------+
|  FORMAT 1: Salesforce Record ID                  |
|  Example: a02al00000oA5JOAA0                     |
|  - 15 or 18 characters long                      |
|  - Used directly (no lookup needed)              |
+--------------------------------------------------+
|  FORMAT 2: Custom Vendor Code                    |
|  Example: V-001                                  |
|  - Starts with "V-"                              |
|  - Short (4-5 chars)                             |
|  - Requires SOQL lookup to find record ID        |
+--------------------------------------------------+
```

### What Happens Inside

```
+---------------------------------------------------------------+
|  PUT /vendors/{vendor_id}  INTERNAL FLOW                      |
+---------------------------------------------------------------+
|                                                               |
|  1. AuthMiddleware validates JWT token                        |
|                      |                                        |
|  2. Parse VendorUpdateRequest body                            |
|     Validate at least one field is present                    |
|                      |                                        |
|  3. Convert Python snake_case to Vendor_Account__c names:     |
|     vendor_tier    -->  Vendor_Tier__c                        |
|     payment_terms  -->  Payment_Terms__c                      |
|     billing_city   -->  City__c                               |
|     website        -->  Website__c                            |
|     annual_revenue -->  Annual_Revenue__c                     |
|                      |                                        |
|  4. Detect vendor_id format:                                  |
|                      |                                        |
|           +----------+----------+                             |
|           |                     |                             |
|     "a02al00000..."         "V-001"                           |
|     (Record ID)           (Vendor Code)                       |
|           |                     |                             |
|     Use directly          SOQL lookup:                        |
|     (no query)            WHERE Vendor_ID__c = 'V-001'        |
|           |                     |                             |
|           +----------+----------+                             |
|                      |                                        |
|  5. Vendor_Account__c.update(record_id, fields)               |
|                      |                                        |
|  6. Fetch full record back from Salesforce                    |
|                      |                                        |
|  7. Return success + full vendor record                       |
|                                                               |
+---------------------------------------------------------------+
```

### Updatable Fields

```
+---------------------+------------------------+
| Python Field        | Vendor_Account__c Field|
+---------------------+------------------------+
| website             | Website__c             |
| vendor_tier         | Vendor_Tier__c         |
| category            | Category__c            |
| payment_terms       | Payment_Terms__c       |
| annual_revenue      | Annual_Revenue__c      |
| sla_response_hours  | SLA_Response_Hours__c  |
| sla_resolution_days | SLA_Resolution_Days__c |
| vendor_status       | Vendor_Status__c       |
| onboarded_date      | Onboarded_Date__c      |
| billing_city        | City__c                |
| billing_state       | State__c               |
| billing_country     | Country__c             |
+---------------------+------------------------+
```

### Successful Response (200)

```json
{
    "success": true,
    "vendor_id": "V-001",
    "updated_fields": ["Vendor_Tier__c", "Website__c", "City__c"],
    "message": "Updated 3 field(s) for vendor V-001",
    "vendor": {
        "id": "a02al00000oA5JOAA0",
        "name": "Acme Industrial Supplies",
        "vendor_id": "V-001",
        "website": "https://updated-site.com",
        "vendor_tier": "Gold",
        "category": "Raw Materials",
        "payment_terms": "Net-30",
        "annual_revenue": 5000000.0,
        "sla_response_hours": 8.0,
        "sla_resolution_days": 3.0,
        "vendor_status": "Active",
        "onboarded_date": "2024-01-15",
        "billing_city": "Mumbai",
        "billing_state": "Maharashtra",
        "billing_country": "India"
    }
}
```

### Error Responses

```
+--------+-----------------------------------+----------------------------+
| Status | Body                              | Cause                      |
+--------+-----------------------------------+----------------------------+
|  401   | {"detail":"Not authenticated"}    | Missing/invalid token      |
|  403   | {"detail":"Admin access required. | User role is not ADMIN     |
|        |  Your role: VENDOR"}              |                            |
|  422   | {"detail":"At least one field     | Empty request body or all  |
|        |  must be provided for update"}    | fields are null            |
|  502   | {"detail":"Salesforce update       | Salesforce API error or    |
|        |  failed: ..."}                    | vendor not found           |
+--------+-----------------------------------+----------------------------+
```

### Files Involved

```
Request  -->  src/api/middleware/auth_middleware.py  (JWT check)
              src/api/routes/vendors.py             (update_vendor + _require_admin)
              src/adapters/salesforce.py             (update_vendor_account)
              src/models/vendor.py                  (VendorUpdateRequest, VendorUpdateResult)
```

---

## 8. DELETE /vendors/{vendor_id}

**Purpose:** Permanently delete a Vendor_Account__c record from Salesforce.

**Role Required:** ADMIN only (403 for VENDOR/REVIEWER)

**WARNING:** This permanently deletes the Vendor_Account__c record
from Salesforce. Use with caution — there is no undo.

### Request

```
DELETE /vendors/V-025
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

No request body needed. The vendor is identified by the path parameter.

### Vendor ID Formats

Same as PUT — accepts both formats:

```
+--------------------------------------------------+
|  FORMAT 1: Salesforce Record ID                  |
|  Example: a02al00000oA5JOAA0                     |
|  - 15 or 18 characters long                      |
|  - Used directly (no lookup needed)              |
+--------------------------------------------------+
|  FORMAT 2: Custom Vendor Code                    |
|  Example: V-025                                  |
|  - Starts with "V-"                              |
|  - Requires SOQL lookup to find record ID        |
+--------------------------------------------------+
```

### What Happens Inside

```
+---------------------------------------------------------------+
|  DELETE /vendors/{vendor_id}  INTERNAL FLOW                   |
+---------------------------------------------------------------+
|                                                               |
|  1. AuthMiddleware validates JWT token                        |
|                      |                                        |
|  2. Check role == "ADMIN" (403 if not)                        |
|                      |                                        |
|  3. Detect vendor_id format:                                  |
|                      |                                        |
|           +----------+----------+                             |
|           |                     |                             |
|     "a02al00000..."         "V-025"                           |
|     (Record ID)           (Vendor Code)                       |
|           |                     |                             |
|     Use directly          SOQL lookup:                        |
|     as record_id          SELECT Id FROM Vendor_Account__c    |
|           |               WHERE Vendor_ID__c = 'V-025'        |
|           |                     |                             |
|           |               +-----+------+                      |
|           |               |            |                      |
|           |            Not found    Found                     |
|           |               |            |                      |
|           |          502 error    Use resolved ID              |
|           |                            |                      |
|           +----------+----------------+                       |
|                      |                                        |
|  4. Call Vendor_Account__c.delete(record_id)                  |
|                      |                                        |
|  5. Return success with vendor_id                             |
|                                                               |
+---------------------------------------------------------------+
```

### Successful Response (200)

```json
{
    "success": true,
    "vendor_id": "V-025",
    "message": "Vendor V-025 deleted successfully"
}
```

### Error Responses

```
+--------+-----------------------------------+----------------------------+
| Status | Body                              | Cause                      |
+--------+-----------------------------------+----------------------------+
|  401   | {"detail":"Not authenticated"}    | Missing/invalid token      |
|  403   | {"detail":"Admin access required. | User role is not ADMIN     |
|        |  Your role: VENDOR"}              |                            |
|  502   | {"detail":"Salesforce delete       | Salesforce API error,      |
|        |  failed: ..."}                    | vendor not found, or       |
|        |                                   | permission denied          |
+--------+-----------------------------------+----------------------------+
```

### Files Involved

```
Request  -->  src/api/middleware/auth_middleware.py  (JWT check)
              src/api/routes/vendors.py             (delete_vendor + _require_admin)
              src/adapters/salesforce.py             (delete_vendor_account)
              src/models/vendor.py                  (VendorDeleteResult)
```

---

## 9. POST /queries

**Purpose:** Submit a new vendor query from the portal.

### Request

```
POST /queries
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
Content-Type: application/json
X-Vendor-ID: 001al00002Ie1zsAAB
X-Correlation-ID: (optional, auto-generated if missing)

{
    "query_type": "invoice",
    "subject": "Invoice INV-2026-1234 payment status",
    "description": "We submitted invoice INV-2026-1234 on March 15...",
    "priority": "HIGH",
    "reference_number": "INV-2026-1234"
}
```

### Input Validation Rules

```
+-------------------+----------+---------------------------+------------+
| Field             | Required | Rules                     | Example    |
+-------------------+----------+---------------------------+------------+
| query_type        | Yes      | Any string                | "invoice"  |
| subject           | Yes      | 5 - 500 characters        | "Invoice.." |
| description       | Yes      | 10 - 5000 characters      | "We sent.." |
| priority          | No       | LOW, MEDIUM, HIGH,        | "HIGH"     |
|                   |          | CRITICAL (default MEDIUM) |            |
| reference_number  | No       | Any string or null        | "INV-123"  |
+-------------------+----------+---------------------------+------------+

  X-Vendor-ID header is REQUIRED (tells us who the vendor is)
```

### What Happens Inside

```
+---------------------------------------------------------------+
|  POST /queries  INTERNAL FLOW                                 |
+---------------------------------------------------------------+
|                                                               |
|  1. AuthMiddleware validates JWT token                        |
|                      |                                        |
|  2. Pydantic validates QuerySubmission body:                  |
|     - subject length (5-500 chars)                            |
|     - description length (10-5000 chars)                      |
|     - priority enum check                                     |
|                      |                                        |
|  3. PortalIntakeService.submit_query() starts:                |
|                      |                                        |
|     a. Generate SHA-256 idempotency key:                      |
|        hash(vendor_id + subject + description)                |
|                      |                                        |
|     b. INSERT idempotency key into PostgreSQL:                |
|        INSERT INTO cache.idempotency_keys                     |
|        ON CONFLICT DO NOTHING                                 |
|              |                                                |
|        +-----+------+                                         |
|        |            |                                         |
|     Already       New (inserted)                              |
|     exists            |                                       |
|        |         c. Generate IDs:                              |
|   409 Duplicate     query_id = VQ-2026-XXXX                   |
|                     correlation_id = UUID v4                   |
|                     execution_id = UUID v4                     |
|                          |                                    |
|                     d. Create UnifiedQueryPayload              |
|                          |                                    |
|                     e. INSERT into PostgreSQL:                 |
|                        workflow.case_execution                 |
|                          |                                    |
|                     f. Publish to EventBridge:                 |
|                        "QueryReceived" event                   |
|                          |                                    |
|                     g. Enqueue to SQS:                         |
|                        vqms-query-intake queue                 |
|                          |                                    |
|                     h. Return query_id + status                |
|                                                               |
+---------------------------------------------------------------+
```

### Successful Response (201)

```json
{
    "query_id": "VQ-2026-0042",
    "status": "RECEIVED"
}
```

### Error Responses

```
+--------+-----------------------------------+----------------------------+
| Status | Body                              | Cause                      |
+--------+-----------------------------------+----------------------------+
|  401   | {"detail":"Not authenticated"}    | Missing/invalid token      |
|  409   | {"detail":"Duplicate query:       | Same vendor + subject +    |
|        |  <hash>"}                         | description already sent   |
|  422   | {"detail":[...validation...]}     | Subject < 5 chars,         |
|        |                                   | description < 10 chars,    |
|        |                                   | invalid priority, etc.     |
|  503   | {"detail":"Portal Intake Service  | PostgreSQL or SQS not      |
|        |  unavailable..."}                 | connected at startup       |
+--------+-----------------------------------+----------------------------+
```

### Files Involved

```
Request  -->  src/api/routes/queries.py            (submit_query endpoint)
              src/services/portal_submission.py     (PortalIntakeService)
              src/models/query.py                  (QuerySubmission, UnifiedQueryPayload)
              src/db/connection.py                 (PostgreSQL insert)
              src/queues/sqs.py                    (SQS enqueue)
              src/events/eventbridge.py            (event publish)
```

---

## 10. GET /queries/{query_id}

**Purpose:** Check the status of a submitted query.

### Request

```
GET /queries/VQ-2026-0042
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
X-Vendor-ID: 001al00002Ie1zsAAB
```

The X-Vendor-ID header ensures vendors can only see their
own queries (ownership check).

### What Happens Inside

```
+---------------------------------------------------------------+
|  GET /queries/{query_id}  INTERNAL FLOW                       |
+---------------------------------------------------------------+
|                                                               |
|  1. AuthMiddleware validates JWT token                        |
|                      |                                        |
|  2. Query PostgreSQL:                                         |
|     SELECT query_id, status, source, processing_path,         |
|            created_at, updated_at                              |
|     FROM workflow.case_execution                               |
|     WHERE query_id = $1                                        |
|       AND vendor_id = $2      <-- ownership check              |
|                      |                                        |
|           +----------+----------+                             |
|           |                     |                             |
|        Not found             Found                            |
|           |                     |                             |
|        404 "Query          Return status                      |
|         not found"                                            |
|                                                               |
+---------------------------------------------------------------+
```

### Successful Response (200)

```json
{
    "query_id": "VQ-2026-0042",
    "status": "RECEIVED",
    "source": "portal",
    "processing_path": null,
    "created_at": "2026-04-14 14:30:00",
    "updated_at": "2026-04-14 14:30:00"
}
```

### Status Values

```
+-------------------+-------------------------------------------+
| Status            | Meaning                                   |
+-------------------+-------------------------------------------+
| RECEIVED          | Query entered the system                  |
| ANALYZING         | AI pipeline is processing                 |
| ROUTING           | Being routed to correct team              |
| RESOLVED          | Answer sent to vendor                     |
| PENDING_REVIEW    | Waiting for human reviewer (Path C)       |
| CLOSED            | Fully resolved and closed                 |
+-------------------+-------------------------------------------+
```

### Error Responses

```
+--------+-----------------------------------+----------------------------+
| Status | Body                              | Cause                      |
+--------+-----------------------------------+----------------------------+
|  401   | {"detail":"Not authenticated"}    | Missing/invalid token      |
|  404   | {"detail":"Query not found"}      | Wrong query_id or wrong    |
|        |                                   | vendor_id (not owner)      |
|  503   | {"detail":"Database unavailable"} | PostgreSQL not connected   |
+--------+-----------------------------------+----------------------------+
```

---

## 11. GET /emails

**Purpose:** Paginated list of email chains for the dashboard.

### Request

```
GET /emails?page=1&page_size=20&status=New&priority=High&search=invoice&sort_by=timestamp&sort_order=desc
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

All query parameters are optional.

### Query Parameters

```
+------------+----------+---------+---------------------------------------+
| Parameter  | Type     | Default | Options                               |
+------------+----------+---------+---------------------------------------+
| page       | integer  | 1       | >= 1                                  |
| page_size  | integer  | 20      | 1 - 100                               |
| status     | string   | null    | "New", "Reopened", "Resolved"         |
| priority   | string   | null    | "High", "Medium", "Low"               |
| search     | string   | null    | Searches subject and sender email     |
| sort_by    | string   | timestamp| "timestamp", "status", "priority"    |
| sort_order | string   | desc    | "asc", "desc"                         |
+------------+----------+---------+---------------------------------------+
```

### What Happens Inside

```
+---------------------------------------------------------------+
|  GET /emails  INTERNAL FLOW  (4-query pattern)                |
+---------------------------------------------------------------+
|                                                               |
|  EmailDashboardService.list_email_chains() runs 4 queries:    |
|                                                               |
|  QUERY 1: COUNT                                               |
|  ~~~~~~~~~~~~                                                 |
|  SELECT COUNT(DISTINCT ...)                                   |
|  FROM intake.email_messages em                                |
|  JOIN workflow.case_execution ce ON em.query_id = ce.query_id |
|  WHERE [filters]                                              |
|                                                               |
|       Result: total = 47                                      |
|                      |                                        |
|  QUERY 2: PAGE KEYS                                           |
|  ~~~~~~~~~~~~~~~~~                                            |
|  SELECT conversation_id, query_id                              |
|  FROM intake.email_messages em                                |
|  JOIN workflow.case_execution ce ...                           |
|  WHERE [filters]                                              |
|  ORDER BY [sort] LIMIT 20 OFFSET 0                            |
|                                                               |
|       Result: 20 thread keys for this page                    |
|                      |                                        |
|  QUERY 3: EMAILS                                              |
|  ~~~~~~~~~~~~~~~                                              |
|  SELECT em.*, ce.status, ce.processing_path                   |
|  FROM intake.email_messages em                                |
|  JOIN workflow.case_execution ce ...                           |
|  WHERE em.query_id IN ($1, $2, ... $20)                       |
|                                                               |
|       Result: All emails for those 20 threads                 |
|                      |                                        |
|  QUERY 4: ATTACHMENTS                                         |
|  ~~~~~~~~~~~~~~~~~~~~                                         |
|  SELECT * FROM intake.email_attachments                        |
|  WHERE query_id IN ($1, $2, ... $20)                          |
|                                                               |
|       Result: All attachments for those emails                |
|                      |                                        |
|  GROUPING:                                                    |
|  ~~~~~~~~~                                                    |
|  Group emails by conversation_id into chains                  |
|  Attach attachments to their parent emails                    |
|  Return paginated response                                    |
|                                                               |
+---------------------------------------------------------------+
```

### Successful Response (200)

```json
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
                    "sender": {
                        "name": "Rajesh Kumar",
                        "email": "rajesh@technova.com"
                    },
                    "subject": "Invoice INV-2026-001 payment query",
                    "body": "Dear Team, we submitted invoice...",
                    "timestamp": "2026-04-10T09:30:00+05:30",
                    "attachments": [
                        {
                            "attachment_id": "att-001",
                            "filename": "invoice.pdf",
                            "content_type": "application/pdf",
                            "size_bytes": 245000,
                            "file_format": "PDF"
                        }
                    ],
                    "thread_status": "NEW"
                }
            ],
            "status": "New",
            "priority": "High"
        }
    ]
}
```

### Error Responses

```
+--------+-----------------------------------+----------------------------+
| Status | Body                              | Cause                      |
+--------+-----------------------------------+----------------------------+
|  401   | {"detail":"Not authenticated"}    | Missing/invalid token      |
|  422   | {"detail":"Invalid status filter  | Bad status, priority,      |
|        |  ..."}                            | sort_by, or sort_order     |
|  503   | {"detail":"Email dashboard        | Service not initialized    |
|        |  service is not available"}       | at startup                 |
+--------+-----------------------------------+----------------------------+
```

---

## 12. GET /emails/stats

**Purpose:** Aggregate statistics for the email dashboard.

### Request

```
GET /emails/stats
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

No parameters. Returns a summary of all email-sourced queries.

### What Happens Inside

```
+---------------------------------------------------------------+
|  GET /emails/stats  INTERNAL FLOW                             |
+---------------------------------------------------------------+
|                                                               |
|  Single SQL query using COUNT with FILTER clauses:            |
|                                                               |
|  SELECT                                                       |
|    COUNT(*) AS total_emails,                                  |
|    COUNT(*) FILTER (WHERE status IN (...)) AS new_count,      |
|    COUNT(*) FILTER (WHERE status = 'REOPENED') AS reopened,   |
|    COUNT(*) FILTER (WHERE status IN (...)) AS resolved,       |
|    COUNT(*) FILTER (WHERE priority = 'HIGH') AS high,         |
|    COUNT(*) FILTER (WHERE priority = 'MEDIUM') AS medium,     |
|    COUNT(*) FILTER (WHERE priority = 'LOW') AS low,           |
|    COUNT(*) FILTER (WHERE created_at >= today) AS today,      |
|    COUNT(*) FILTER (WHERE created_at >= 7_days_ago) AS week   |
|  FROM intake.email_messages em                                |
|  JOIN workflow.case_execution ce ON ...                        |
|  WHERE ce.source = 'email'                                    |
|                                                               |
|  One query, one round-trip, all stats.                        |
|                                                               |
+---------------------------------------------------------------+
```

### Successful Response (200)

```json
{
    "total_emails": 156,
    "new_count": 23,
    "reopened_count": 5,
    "resolved_count": 128,
    "priority_breakdown": {
        "High": 34,
        "Medium": 89,
        "Low": 33
    },
    "today_count": 7,
    "this_week_count": 42
}
```

---

## 13. GET /emails/{query_id}

**Purpose:** Get a single email chain with full thread detail.

### Request

```
GET /emails/VQ-2026-0001
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

### What Happens Inside

```
+---------------------------------------------------------------+
|  GET /emails/{query_id}  INTERNAL FLOW                        |
+---------------------------------------------------------------+
|                                                               |
|  1. Look up the email by query_id                             |
|                      |                                        |
|  2. If it has a conversation_id:                              |
|     Fetch ALL emails in that conversation thread              |
|     (grouped by Graph API conversation_id)                    |
|                      |                                        |
|  3. If no conversation_id:                                    |
|     Return just the single email as its own chain             |
|                      |                                        |
|  4. Fetch attachments for all emails in the chain             |
|                      |                                        |
|  5. Return MailChainResponse                                  |
|                                                               |
+---------------------------------------------------------------+
```

### Successful Response (200)

```json
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
            "sender": {"name": "Rajesh Kumar", "email": "rajesh@technova.com"},
            "subject": "Re: Invoice query",
            "body": "Following up on my earlier email...",
            "timestamp": "2026-04-11T14:00:00+05:30",
            "attachments": [],
            "thread_status": "EXISTING_OPEN"
        }
    ],
    "status": "New",
    "priority": "High"
}
```

### Error Responses

```
+--------+---------------------------------------------+-------------------+
| Status | Body                                        | Cause             |
+--------+---------------------------------------------+-------------------+
|  401   | {"detail":"Not authenticated"}              | No/bad token      |
|  404   | {"detail":"Email chain not found for        | Wrong query_id    |
|        |  query_id: VQ-2026-9999"}                   |                   |
|  503   | {"detail":"Email dashboard service is       | Service not       |
|        |  not available"}                            | initialized       |
+--------+---------------------------------------------+-------------------+
```

---

## 14. GET Attachment Download

**Full path:** `GET /emails/{query_id}/attachments/{attachment_id}/download`

**Purpose:** Get a temporary download URL for an email attachment.

### Request

```
GET /emails/VQ-2026-0001/attachments/att-001/download
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

### What Happens Inside

```
+---------------------------------------------------------------+
|  GET .../download  INTERNAL FLOW                              |
+---------------------------------------------------------------+
|                                                               |
|  1. Look up attachment in PostgreSQL:                         |
|     SELECT attachment_id, filename, s3_key                     |
|     FROM intake.email_attachments                              |
|     WHERE attachment_id = $1                                   |
|                      |                                        |
|           +----------+----------+                             |
|           |                     |                             |
|        Not found             Found                            |
|           |                     |                             |
|        404 "Attachment     2. Check if s3_key exists           |
|         not found"             |                              |
|                          +-----+------+                       |
|                          |            |                       |
|                       No s3_key    Has s3_key                 |
|                          |            |                       |
|                       404 error   3. Generate presigned URL    |
|                                      from S3 connector        |
|                                      (valid for 1 hour)       |
|                                         |                     |
|                                   4. Return URL + metadata    |
|                                                               |
+---------------------------------------------------------------+
```

### Successful Response (200)

```json
{
    "attachment_id": "att-001",
    "filename": "invoice.pdf",
    "download_url": "https://vqms-data-store.s3.amazonaws.com/attachments/VQ-2026-0001/att-001_invoice.pdf?X-Amz-...",
    "expires_in_seconds": 3600
}
```

---

## 15. POST /webhooks/ms-graph

**Purpose:** Receive email notifications from Microsoft Graph API.

This endpoint is called by Microsoft, not by humans. It handles
two scenarios: validation handshake and email notifications.

### Validation Handshake

When we first subscribe to email notifications, Microsoft sends
a validation request to confirm we own the webhook URL.

```
POST /webhooks/ms-graph?validationToken=abc123xyz
```

Response: `200 OK` with body `abc123xyz` (plain text)

### Email Notification

When a new email arrives, Microsoft sends a notification.

```
POST /webhooks/ms-graph
Content-Type: application/json

{
    "value": [
        {
            "resource": "Users/vendor-support@company.com/Messages/AAMk123..."
        }
    ]
}
```

### What Happens Inside

```
+---------------------------------------------------------------+
|  POST /webhooks/ms-graph  INTERNAL FLOW                       |
+---------------------------------------------------------------+
|                                                               |
|  1. Check for validationToken query param                     |
|                      |                                        |
|           +----------+----------+                             |
|           |                     |                             |
|     Has token              No token                           |
|           |                     |                             |
|     Return token as        2. Parse notification body         |
|     plain text                  |                             |
|     (handshake done)       3. For each notification:          |
|                                 |                             |
|                            4. Extract message_id from         |
|                               resource path:                  |
|                               Users/.../Messages/{id}         |
|                                 |                             |
|                            5. Call email_intake.process_email  |
|                                 |                             |
|                          +------+------+                      |
|                          |      |      |                      |
|                       Success  Dup   Error                    |
|                          |      |      |                      |
|                        (log)  (skip)  (log)                   |
|                                                               |
|  6. Return {"status": "accepted"}                             |
|                                                               |
+---------------------------------------------------------------+
```

### Responses

```
+--------+-----------------------------------+----------------------------+
| Status | Body                              | Cause                      |
+--------+-----------------------------------+----------------------------+
|  200   | "abc123xyz" (plain text)          | Validation handshake       |
|  200   | {"status":"accepted"}             | Notification processed     |
|  200   | {"status":"invalid_body"}         | Unparseable JSON body      |
+--------+-----------------------------------+----------------------------+
```

---

## 16. GET /health

**Purpose:** Check if the application is running and the database
is connected. Used by load balancers and monitoring systems.

### Request

```
GET /health
```

No authentication required.

### What Happens Inside

```
+---------------------------------------------------------------+
|  GET /health  INTERNAL FLOW                                   |
+---------------------------------------------------------------+
|                                                               |
|  1. Check if app.state.postgres exists                        |
|                      |                                        |
|  2. If yes: run postgres.health_check()                       |
|     (executes SELECT 1 to verify DB connection)               |
|                      |                                        |
|  3. Return status with database state                         |
|                                                               |
+---------------------------------------------------------------+
```

### Response (always 200)

```json
{
    "status": "healthy",
    "app": "vqms",
    "version": "0.1.0",
    "database": "connected"
}
```

If the database is down:

```json
{
    "status": "healthy",
    "app": "vqms",
    "version": "0.1.0",
    "database": "disconnected"
}
```

---

## 17. Security Headers

Every API response includes these security headers (added by
middleware in main.py). Swagger UI paths (/docs, /redoc) skip
CSP to allow their scripts to load.

```
+-------------------------------+-------------------------------------------+
| Header                        | What It Protects Against                  |
+-------------------------------+-------------------------------------------+
| Content-Security-Policy       | XSS (cross-site scripting) — only allows  |
|                               | scripts from our domain + nonce           |
+-------------------------------+-------------------------------------------+
| Server: hidden                | Hides server identity (default: uvicorn)  |
|                               | so attackers don't know our stack          |
+-------------------------------+-------------------------------------------+
| X-Content-Type-Options:       | Prevents browser from guessing file       |
| nosniff                       | types (MIME sniffing attacks)              |
+-------------------------------+-------------------------------------------+
| X-XSS-Protection:             | Legacy XSS filter for older browsers      |
| 1; mode=block                 | (IE, old Chrome)                          |
+-------------------------------+-------------------------------------------+
| X-Frame-Options: DENY         | Prevents clickjacking — our app can't     |
|                               | be embedded in iframes                    |
+-------------------------------+-------------------------------------------+
| Strict-Transport-Security     | Forces HTTPS for 1 year — prevents        |
|                               | downgrade attacks to HTTP                 |
+-------------------------------+-------------------------------------------+
| Referrer-Policy: no-referrer  | Don't leak our URLs when user clicks      |
|                               | links to external sites                   |
+-------------------------------+-------------------------------------------+
| Permissions-Policy            | Blocks browser APIs we don't use          |
|                               | (camera, microphone, geolocation)         |
+-------------------------------+-------------------------------------------+
| Cache-Control: no-store       | Never cache API responses — sensitive     |
| Pragma: no-cache              | vendor/email data stays private           |
+-------------------------------+-------------------------------------------+
```

---

## 18. Error Code Reference

Quick lookup for every HTTP status code the API returns:

```
+------+-------------------------+-------------------------------------------+
| Code | Meaning                 | When You'll See It                        |
+------+-------------------------+-------------------------------------------+
| 200  | OK                      | Successful GET, POST /auth/logout,        |
|      |                         | PUT /vendors, DELETE /vendors              |
+------+-------------------------+-------------------------------------------+
| 201  | Created                 | POST /queries or POST /vendors succeeded  |
+------+-------------------------+-------------------------------------------+
| 400  | Bad Request             | Malformed logout request                  |
+------+-------------------------+-------------------------------------------+
| 401  | Unauthorized            | No token, expired token, blacklisted      |
|      |                         | token, or invalid token                   |
+------+-------------------------+-------------------------------------------+
| 403  | Forbidden               | User role is not ADMIN for vendor CRUD    |
|      |                         | endpoints (GET/POST/PUT/DELETE /vendors)  |
+------+-------------------------+-------------------------------------------+
| 404  | Not Found               | Query ID doesn't exist, attachment not    |
|      |                         | found, email chain not found              |
+------+-------------------------+-------------------------------------------+
| 409  | Conflict                | Duplicate query submission (same vendor   |
|      |                         | + subject + description)                  |
+------+-------------------------+-------------------------------------------+
| 422  | Unprocessable Entity    | Validation failed: subject too short,     |
|      |                         | bad priority value, invalid filter,       |
|      |                         | no fields in update request               |
+------+-------------------------+-------------------------------------------+
| 502  | Bad Gateway             | Salesforce API call failed                |
+------+-------------------------+-------------------------------------------+
| 503  | Service Unavailable     | Database or service not connected at      |
|      |                         | startup time                              |
+------+-------------------------+-------------------------------------------+
```

---

## Quick Start: Testing All APIs in Order

```
STEP 1: Health check (no auth)
  GET /health

STEP 2: Login
  POST /auth/login
  Body: {"username_or_email":"admin_user","password":"admin123"}
  --> Save the "token" from the response

STEP 3: Use the token for all remaining requests
  Header: Authorization: Bearer <token>

STEP 4: List vendors (ADMIN only)
  GET /vendors

STEP 5: Create a vendor (ADMIN only)
  POST /vendors
  Body: {"name":"Test Vendor Corp","vendor_tier":"Silver",
         "billing_city":"Pune","billing_country":"India"}
  --> Save the "vendor_id" (e.g., V-026) and "salesforce_id"

STEP 6: Update a vendor (ADMIN only)
  PUT /vendors/V-026
  Body: {"vendor_tier":"Gold","website":"https://testvendor.com"}

STEP 7: Delete a vendor (ADMIN only)
  DELETE /vendors/V-026
  --> Permanently removes from Salesforce

STEP 8: Submit a query
  POST /queries
  Headers: X-Vendor-ID: 001al00002Ie1zsAAB
  Body: {"query_type":"invoice","subject":"Test query",
         "description":"Testing the query submission API",
         "priority":"LOW"}
  --> Save the "query_id" from the response

STEP 9: Check query status
  GET /queries/VQ-2026-XXXX
  Headers: X-Vendor-ID: 001al00002Ie1zsAAB

STEP 10: View email dashboard
  GET /emails
  GET /emails/stats

STEP 11: Logout
  POST /auth/logout
  --> Token is now blacklisted, can't be reused
```

### Using Swagger UI (http://localhost:8001/docs)

```
+-----------------------------------------------------------+
|                                                           |
|  1. Open http://localhost:8001/docs in your browser       |
|                                                           |
|  2. Click POST /auth/login                                |
|     Click "Try it out"                                    |
|     Paste this in the body:                               |
|     {"username_or_email":"admin_user","password":"admin123"} |
|     Click "Execute"                                       |
|     Copy the "token" value from the response              |
|                                                           |
|  3. Click the green "Authorize" button (top-right)        |
|     Paste the token (without quotes)                      |
|     Click "Authorize"                                     |
|     Click "Close"                                         |
|                                                           |
|  4. Now ALL endpoints will include your token             |
|     automatically. Try any endpoint!                      |
|                                                           |
+-----------------------------------------------------------+
```

---

*Generated for VQMS v0.1.0 — Hexaware Technologies*
*Last updated: 2026-04-14*
