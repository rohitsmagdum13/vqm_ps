# Auth Middleware — Windows CMD Test Guide

End-to-end manual test walkthrough for the pure-ASGI `AuthMiddleware`
using Windows `cmd.exe`. Uses the built-in `curl.exe` that ships with
Windows 10/11.

> **Key cmd quirks**
> - Use `\"` inside `-d "..."` for JSON (single quotes don't work in cmd).
> - Store the token with `set TOKEN=...` — no spaces around `=`.
> - Line continuation is `^`, not `\`. This guide avoids it by keeping
>   each curl call on one line.

---

## Prerequisite — start the server

In **one** cmd window:

```cmd
uv run uvicorn main:app --reload --port 8000
```

Leave that running. Open a **second** cmd window for the tests below.

Admin credentials (from [scripts/seed_admin_user.py:51-59](../scripts/seed_admin_user.py#L51-L59)):

| field    | value        |
|----------|--------------|
| username | `admin_user` |
| password | `admin123`   |

---

## Test 1 — Health (skip-path, no auth)

```cmd
curl -i http://localhost:8000/health
```

**Expected:** `HTTP/1.1 200 OK` + body.

---

## Test 2 — No token → 401 with CORS headers (THE fix)

```cmd
curl -i -H "Origin: http://localhost:4200" http://localhost:8000/vendors
```

**Expected — look for both the status and the CORS headers:**

```
HTTP/1.1 401 Unauthorized
content-type: application/json
access-control-allow-origin: http://localhost:4200
access-control-allow-credentials: true
vary: Origin
...

{"detail":"Not authenticated"}
```

Before the pure-ASGI rewrite, those `access-control-*` lines were
missing on a 401 because `BaseHTTPMiddleware` short-circuited the
stack. Their presence now = the trap is fixed.

---

## Test 3 — Bad token → 401 with CORS headers

```cmd
curl -i -H "Origin: http://localhost:4200" -H "Authorization: Bearer not-a-real-jwt" http://localhost:8000/vendors
```

**Expected:**

```
HTTP/1.1 401 Unauthorized
access-control-allow-origin: http://localhost:4200
...
{"detail":"Invalid or expired token"}
```

---

## Test 4 — CORS preflight (OPTIONS must pass through, not 401)

```cmd
curl -i -X OPTIONS http://localhost:8000/vendors -H "Origin: http://localhost:4200" -H "Access-Control-Request-Method: GET" -H "Access-Control-Request-Headers: authorization,content-type"
```

**Expected:** `HTTP/1.1 200 OK` (NOT 401) with
`access-control-allow-methods` and `access-control-allow-headers`
headers.

---

## Test 5 — Login as admin

JSON in cmd needs backslash-escaped double quotes:

```cmd
curl -i -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" -d "{\"username_or_email\": \"admin_user\", \"password\": \"admin123\"}"
```

**Expected response body (abbreviated):**

```json
{"token":"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...LONG...","user_name":"admin_user","full_name":"Admin User","email":"admin@vqms.local","role":"ADMIN","tenant":"hexaware","vendor_id":null}
```

Copy the `token` value — just the string between the quotes, no
`Bearer ` prefix, no quotes.

---

## Test 6 — Store token in a cmd variable

Paste the copied token after `=` (no quotes, no spaces around `=`):

```cmd
set TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbl91c2VyIi...rest-of-token
```

Verify it's set:

```cmd
echo %TOKEN%
```

---

## Test 7 — Authenticated call to an admin-only endpoint

```cmd
curl -i -H "Authorization: Bearer %TOKEN%" http://localhost:8000/vendors
```

**Expected:** `HTTP/1.1 200 OK` with a JSON array of vendors from
Salesforce.

If instead you get `403 Admin access required. Your role: unauthenticated`,
that means `scope["state"]` isn't flowing to `request.state.role`.
Passing this test proves the pure-ASGI middleware correctly populates
downstream state.

---

## Test 8 — Other admin-gated endpoints

```cmd
curl -i -H "Authorization: Bearer %TOKEN%" http://localhost:8000/dashboard/kpis
curl -i -H "Authorization: Bearer %TOKEN%" http://localhost:8000/triage/queue
curl -i -H "Authorization: Bearer %TOKEN%" http://localhost:8000/admin/metrics
```

All should return `200`.

---

## Test 9 — Logout → token becomes invalid

```cmd
curl -i -X POST -H "Authorization: Bearer %TOKEN%" http://localhost:8000/auth/logout
```

**Expected:** `200` + `{"message":"Logged out successfully"}`.

Now reuse the same token — it should be rejected:

```cmd
curl -i -H "Origin: http://localhost:4200" -H "Authorization: Bearer %TOKEN%" http://localhost:8000/vendors
```

**Expected:** `401 Invalid or expired token` **with**
`access-control-allow-origin` header present. Proves both the
blacklist lookup works AND the 401+CORS path is intact.

---

## Test 10 — Token auto-refresh (`X-New-Token` header)

Mint a near-expiry admin token in a cmd window:

```cmd
uv run python -c "import time; from jose import jwt; from config.settings import get_settings; s=get_settings(); print(jwt.encode({'sub':'admin_user','role':'ADMIN','tenant':'hexaware','exp':time.time()+60,'iat':time.time()-1740,'jti':'cmd-test'}, s.jwt_secret_key, algorithm='HS256'))"
```

Copy the printed token, then:

```cmd
set REFRESH_TOKEN=<paste-the-new-token-here>
curl -i -H "Authorization: Bearer %REFRESH_TOKEN%" http://localhost:8000/vendors
```

**Expected:** `HTTP/1.1 200 OK`, and in the response headers look for:

```
x-new-token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
access-control-expose-headers: X-New-Token
```

The `expose-headers` line comes from
[app/middleware.py:34](../app/middleware.py#L34) and is what lets
browser JS actually read the refreshed token.

---

## Checklist — what you should see

| Test | Command summary                          | Expected status              | CORS headers present?  |
|------|------------------------------------------|------------------------------|------------------------|
| 1    | `GET /health`                            | 200                          | n/a (no Origin sent)   |
| 2    | `GET /vendors` no token, with Origin     | 401                          | yes                    |
| 3    | `GET /vendors` bad token, with Origin    | 401                          | yes                    |
| 4    | `OPTIONS /vendors` preflight             | 200                          | yes                    |
| 5    | `POST /auth/login` admin creds           | 200                          | —                      |
| 7    | `GET /vendors` with admin token          | 200                          | —                      |
| 8    | admin-gated endpoints                    | 200                          | —                      |
| 9    | `POST /auth/logout` then reuse           | 200 then 401                 | yes on 401             |
| 10   | near-expiry token                        | 200 + `x-new-token` header   | —                      |

---

## Common Windows cmd gotchas

### "Invalid JSON" on login

cmd's outer `"..."` with inner `\"...\"` is required. Single quotes
won't work. If it still fails, save the JSON to `login.json` and use
`-d @login.json`:

```cmd
echo {"username_or_email": "admin_user", "password": "admin123"} > login.json
curl -i -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" -d @login.json
```

### `%TOKEN%` shows nothing

`set` can't have spaces around `=`. Use `set TOKEN=eyJ...`, never
`set TOKEN = eyJ...`.

### `curl` not found

Windows 10 1803+ / Windows 11 ships `curl.exe` in `C:\Windows\System32`.
If it's missing, install via `winget install curl.curl` or use
PowerShell's `Invoke-WebRequest` instead.

### Response body seems empty

`curl -i` shows headers followed by a blank line then the body.
Scroll up — the body is at the bottom after all the headers.

---

## One-shot copy-paste block

For a quick full sweep (skip the admin-only endpoints if you don't
care about them), paste this into a second cmd window once the server
is running — then follow the prompts to insert tokens where needed.

```cmd
:: 1. Health
curl -i http://localhost:8000/health

:: 2. No token with Origin → 401 + CORS
curl -i -H "Origin: http://localhost:4200" http://localhost:8000/vendors

:: 3. Bad token with Origin → 401 + CORS
curl -i -H "Origin: http://localhost:4200" -H "Authorization: Bearer not-a-real-jwt" http://localhost:8000/vendors

:: 4. CORS preflight
curl -i -X OPTIONS http://localhost:8000/vendors -H "Origin: http://localhost:4200" -H "Access-Control-Request-Method: GET" -H "Access-Control-Request-Headers: authorization,content-type"

:: 5. Login as admin (copy token from response)
curl -i -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" -d "{\"username_or_email\": \"admin_user\", \"password\": \"admin123\"}"

:: 6. Store token (replace <token> with the copied value)
:: set TOKEN=<token>

:: 7. Authenticated admin call
:: curl -i -H "Authorization: Bearer %TOKEN%" http://localhost:8000/vendors

:: 8. Other admin-gated endpoints
:: curl -i -H "Authorization: Bearer %TOKEN%" http://localhost:8000/dashboard/kpis
:: curl -i -H "Authorization: Bearer %TOKEN%" http://localhost:8000/triage/queue
:: curl -i -H "Authorization: Bearer %TOKEN%" http://localhost:8000/admin/metrics

:: 9. Logout + reuse
:: curl -i -X POST -H "Authorization: Bearer %TOKEN%" http://localhost:8000/auth/logout
:: curl -i -H "Origin: http://localhost:4200" -H "Authorization: Bearer %TOKEN%" http://localhost:8000/vendors
```
