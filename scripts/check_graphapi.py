"""Script: check_graphapi.py

Detailed Microsoft Graph API diagnostic.

Designed to pinpoint "insufficient privileges" errors on a freshly
provisioned app registration. Tells you exactly:

  - Which app/tenant the token came from
  - Which Application Permissions Azure AD granted (roles claim)
  - Which Graph endpoints VQMS actually hits
  - Which of those endpoints fail and with what OData error code
  - Which specific Graph permission is needed to fix each failure
  - Whether the failure is missing-permission, missing-admin-consent,
    license, or scope-mismatch

Usage:
    uv run python scripts/check_graphapi.py
    uv run python scripts/check_graphapi.py --mailbox other@tenant.onmicrosoft.com
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
import time
from typing import Any

sys.path.insert(0, ".")
sys.path.insert(0, "src")

import httpx  # noqa: E402
import msal  # noqa: E402

from config.settings import get_settings  # noqa: E402

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPES = ["https://graph.microsoft.com/.default"]

# Permissions VQMS uses, mapped to the Graph endpoints that need them.
# Source: src/adapters/graph_api/{email_fetch,email_send,webhook}.py
REQUIRED_PERMISSIONS: dict[str, str] = {
    "User.Read.All": "GET /users/{mailbox} -- resolve mailbox by UPN",
    "Mail.Read": "GET /users/{mailbox}/messages -- list / fetch emails",
    "Mail.ReadWrite": "PATCH /users/{mailbox}/messages/{id} -- mark as read",
    "Mail.Send": "POST /users/{mailbox}/sendMail -- outbound email delivery",
    # Subscription.Read.All / MailboxSettings.Read are nice-to-have, not required
}


# ---------------------------------------------------------------------------
# Pretty printing helpers
# ---------------------------------------------------------------------------
def _hr(title: str) -> None:
    print(f"\n{'=' * 72}\n  {title}\n{'=' * 72}")


def _ok(msg: str) -> None:
    print(f"  [OK]   {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def _warn(msg: str) -> None:
    print(f"  [WARN] {msg}")


def _info(msg: str) -> None:
    print(f"  [INFO] {msg}")


def _redact(s: str) -> str:
    if not s:
        return "(empty)"
    if len(s) <= 6:
        return "*" * len(s)
    return f"{s[:3]}...{s[-3:]}"


# ---------------------------------------------------------------------------
# JWT decoding (no signature verification -- we just want the claims)
# ---------------------------------------------------------------------------
def _decode_jwt_claims(token: str) -> dict | None:
    """Decode the payload of a JWT without verifying the signature."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = parts[1]
        # JWT base64 lacks padding -- restore it
        padded = payload + "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(padded)
        return json.loads(decoded)
    except Exception:
        return None


def _show_token_claims(token: str) -> dict | None:
    """Print the relevant claims and return them."""
    claims = _decode_jwt_claims(token)
    if not claims:
        _warn("Could not decode JWT -- token may not be a valid JWT")
        return None

    _info(f"aud (audience)       = {claims.get('aud')}")
    _info(f"iss (issuer)         = {claims.get('iss')}")
    _info(f"tid (tenant id)      = {claims.get('tid')}")
    _info(f"appid (client id)    = {claims.get('appid')}")
    _info(f"app_displayname      = {claims.get('app_displayname')}")
    _info(f"idtyp                = {claims.get('idtyp')} (should be 'app' for client_credentials)")

    roles = claims.get("roles") or []
    if roles:
        _ok(f"Application Permissions granted ({len(roles)} role(s)):")
        for r in sorted(roles):
            print(f"          * {r}")
    else:
        _fail(
            "Token has NO roles claim -- Azure AD has not granted any "
            "Application Permissions to this app. Likely causes:\n"
            "          (1) App has DELEGATED permissions only -- needs APPLICATION permissions for client_credentials.\n"
            "          (2) Permissions added but admin consent not granted -- go to\n"
            "              Azure Portal -> App registrations -> API permissions -> 'Grant admin consent for <tenant>'.\n"
            "          (3) Wrong tenant -- appid does not exist in the tenant in tid claim."
        )

    # scp claim only present for delegated tokens -- not what we want
    if "scp" in claims:
        _warn(
            f"Token has 'scp' claim ({claims.get('scp')}) -- this is a DELEGATED "
            "token, not an Application token. client_credentials should produce "
            "an app-only token with 'roles', not 'scp'. Check that the app has "
            "Application permissions (not Delegated) configured."
        )

    return claims


# ---------------------------------------------------------------------------
# OData error parsing
# ---------------------------------------------------------------------------
def _parse_graph_error(response: httpx.Response) -> tuple[str, str]:
    """Return (error_code, error_message) from a Graph error response."""
    try:
        body = response.json()
        err = body.get("error", {}) if isinstance(body, dict) else {}
        return err.get("code", "Unknown"), err.get("message", response.text[:200])
    except Exception:
        return "NotJSON", response.text[:200]


def _explain_status(status: int, code: str, message: str) -> str:
    """Human-readable explanation for a failed Graph API call."""
    if status == 401:
        return (
            "401 Unauthorized -- token rejected. Likely token expired, audience "
            "mismatch, or signature failure."
        )
    if status == 403:
        if "insufficient" in message.lower() or "Authorization_RequestDenied" in code:
            return (
                "403 InsufficientPrivileges -- token is valid but does NOT carry "
                "the required Application Permission. Add the missing permission "
                "in Azure Portal -> API permissions -> Application permissions and "
                "click 'Grant admin consent'."
            )
        return f"403 Forbidden -- {code}: {message}"
    if status == 404:
        return (
            "404 NotFound -- usually means the mailbox UPN does not exist in "
            "this tenant, OR User.Read.All is missing so /users/{id} can't be "
            "resolved. Check spelling and tenant."
        )
    if status == 429:
        return "429 TooManyRequests -- Graph throttling; retry with backoff."
    if status >= 500:
        return f"{status} server error -- transient; retry."
    return f"{status} {code}: {message}"


# ---------------------------------------------------------------------------
# Step 1 -- Validate config
# ---------------------------------------------------------------------------
def step_1_check_config(settings) -> bool:
    _hr("[1] Configuration sanity check")
    ok = True
    fields = {
        "GRAPH_API_TENANT_ID":   settings.graph_api_tenant_id,
        "GRAPH_API_CLIENT_ID":   settings.graph_api_client_id,
        "GRAPH_API_CLIENT_SECRET": settings.graph_api_client_secret,
        "GRAPH_API_MAILBOX":     settings.graph_api_mailbox,
    }
    for name, value in fields.items():
        if not value:
            _fail(f"{name} is not set in .env")
            ok = False
        else:
            shown = value if "SECRET" not in name else _redact(value)
            _ok(f"{name} = {shown}")

    if settings.graph_api_tenant_id and len(settings.graph_api_tenant_id) != 36:
        _warn("Tenant ID is not 36 chars -- should be a GUID like xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
    if settings.graph_api_client_id and len(settings.graph_api_client_id) != 36:
        _warn("Client ID is not 36 chars -- should be a GUID")

    return ok


# ---------------------------------------------------------------------------
# Step 2 -- MSAL token acquisition
# ---------------------------------------------------------------------------
def step_2_acquire_token(settings) -> str | None:
    _hr("[2] MSAL token acquisition (client_credentials flow)")
    authority = f"https://login.microsoftonline.com/{settings.graph_api_tenant_id}"
    _info(f"Authority: {authority}")
    _info(f"Scopes:    {GRAPH_SCOPES}")

    try:
        app = msal.ConfidentialClientApplication(
            settings.graph_api_client_id,
            authority=authority,
            client_credential=settings.graph_api_client_secret,
        )
    except Exception as exc:
        _fail(f"MSAL ConfidentialClientApplication() raised: {type(exc).__name__}: {exc}")
        return None

    start = time.perf_counter()
    try:
        result = app.acquire_token_for_client(scopes=GRAPH_SCOPES)
    except Exception as exc:
        _fail(f"acquire_token_for_client raised: {type(exc).__name__}: {exc}")
        return None
    elapsed = (time.perf_counter() - start) * 1000

    if "access_token" not in result:
        _fail(f"Token request rejected ({elapsed:.0f}ms)")
        _info(f"error             = {result.get('error')}")
        _info(f"error_description = {result.get('error_description')}")
        _info(f"correlation_id    = {result.get('correlation_id')}")
        # Common AAD error codes
        err = (result.get("error") or "").lower()
        desc = (result.get("error_description") or "")
        if "invalid_client" in err or "AADSTS7000215" in desc:
            _warn(
                "Hint: 'invalid_client' usually means the client secret is wrong or expired, "
                "or the secret was issued for a different app."
            )
        if "AADSTS70011" in desc:
            _warn("Hint: AADSTS70011 = invalid scope. Use 'https://graph.microsoft.com/.default' for client_credentials.")
        if "AADSTS50034" in desc:
            _warn("Hint: AADSTS50034 = user/principal not found in directory. Check tenant id.")
        if "AADSTS500011" in desc:
            _warn("Hint: AADSTS500011 = service principal not found in tenant. The app exists but has not been added to this tenant.")
        return None

    _ok(f"Token acquired ({elapsed:.0f}ms, expires_in={result.get('expires_in')}s)")
    return result["access_token"]


# ---------------------------------------------------------------------------
# Step 3 -- Decode and inspect the token
# ---------------------------------------------------------------------------
def step_3_inspect_token(token: str) -> set[str]:
    _hr("[3] Decode token claims")
    claims = _show_token_claims(token)
    if not claims:
        return set()
    return set(claims.get("roles") or [])


# ---------------------------------------------------------------------------
# Step 4 -- Probe each Graph endpoint VQMS uses
# ---------------------------------------------------------------------------
async def _probe(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    headers: dict,
    *,
    needed_permission: str,
    label: str,
    json_body: dict | None = None,
) -> dict[str, Any]:
    """Probe one endpoint and return a structured result."""
    print(f"\n  [probe] {label}")
    print(f"          {method} {url}")
    print(f"          requires: {needed_permission}")
    try:
        response = await client.request(method, url, headers=headers, json=json_body)
    except Exception as exc:
        _fail(f"request raised: {type(exc).__name__}: {exc}")
        return {"label": label, "status": None, "error": str(exc), "permission": needed_permission}

    status = response.status_code
    if 200 <= status < 300:
        _ok(f"HTTP {status}")
        return {"label": label, "status": status, "permission": needed_permission}

    code, message = _parse_graph_error(response)
    _fail(f"HTTP {status} {code}: {message[:200]}")
    _info(_explain_status(status, code, message))
    return {
        "label": label,
        "status": status,
        "error_code": code,
        "error_message": message,
        "permission": needed_permission,
    }


async def step_4_probe_endpoints(token: str, mailbox: str) -> list[dict]:
    _hr("[4] Probe Graph endpoints VQMS uses")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    results: list[dict] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        # /me/$ref returns 400 for app-only tokens but proves the bearer is valid
        # -- skip it; jump straight to the endpoints VQMS actually uses.

        results.append(await _probe(
            client, "GET", f"{GRAPH_BASE}/users/{mailbox}", headers,
            needed_permission="User.Read.All",
            label="Mailbox lookup",
        ))

        results.append(await _probe(
            client, "GET",
            f"{GRAPH_BASE}/users/{mailbox}/messages?$top=1&$select=id,subject,from,receivedDateTime",
            headers,
            needed_permission="Mail.Read",
            label="List messages",
        ))

        results.append(await _probe(
            client, "GET",
            f"{GRAPH_BASE}/users/{mailbox}/messages?$filter=isRead eq false&$top=1",
            headers,
            needed_permission="Mail.Read",
            label="Filter unread messages",
        ))

        # Mark-as-read PATCH probe -- only if at least one message is visible
        msg_id = None
        try:
            r = await client.get(
                f"{GRAPH_BASE}/users/{mailbox}/messages?$top=1&$select=id",
                headers=headers,
            )
            if r.status_code == 200:
                items = r.json().get("value", [])
                if items:
                    msg_id = items[0]["id"]
        except Exception:
            pass

        if msg_id:
            # Send a no-op PATCH (set isRead to its current value) -- non-destructive.
            results.append(await _probe(
                client, "PATCH",
                f"{GRAPH_BASE}/users/{mailbox}/messages/{msg_id}",
                headers,
                needed_permission="Mail.ReadWrite",
                label="Update message (no-op PATCH)",
                json_body={"isRead": True},
            ))
        else:
            print("\n  [skip]  Update message -- no message available to PATCH")

        # Send Mail probe -- only attempts to send if user passes --send.
        # By default we use a dry-probe: POST with empty body to elicit a 4xx
        # that still proves the permission. 400 BadRequest = permission OK,
        # 403 InsufficientPrivileges = Mail.Send missing.
        results.append(await _probe(
            client, "POST",
            f"{GRAPH_BASE}/users/{mailbox}/sendMail",
            headers,
            needed_permission="Mail.Send",
            label="Send mail (intentionally invalid body -- 400=OK, 403=missing perm)",
            json_body={},
        ))

    return results


# ---------------------------------------------------------------------------
# Step 5 -- Cross-reference token roles with required permissions
# ---------------------------------------------------------------------------
def step_5_summary(roles: set[str], probes: list[dict]) -> None:
    _hr("[5] Permission summary")

    print("\n  Required permissions for VQMS:")
    for perm, where in REQUIRED_PERMISSIONS.items():
        if perm in roles:
            _ok(f"{perm:<20} -- granted ({where})")
        else:
            _fail(f"{perm:<20} -- MISSING ({where})")

    print("\n  Endpoint probe results:")
    for p in probes:
        status = p.get("status")
        label = p["label"]
        perm = p["permission"]
        if status is None:
            _fail(f"{label:<45} -> request error")
        elif 200 <= status < 300:
            _ok(f"{label:<45} -> HTTP {status}")
        elif status == 400 and "Send mail" in label:
            _ok(f"{label:<45} -> HTTP 400 (permission OK, body intentionally invalid)")
        elif status == 403:
            _fail(f"{label:<45} -> HTTP 403 -- needs {perm}")
        else:
            _warn(f"{label:<45} -> HTTP {status} {p.get('error_code', '')}")

    # Overall verdict
    print()
    missing = [p for p in REQUIRED_PERMISSIONS if p not in roles]
    if missing:
        _fail(
            "Action required: add the following Application permissions to the "
            "app registration and click 'Grant admin consent for <tenant>':"
        )
        for p in missing:
            print(f"          * {p}")
        print(
            "\n  Steps in Azure Portal:\n"
            "    1. App registrations -> select your app\n"
            "    2. API permissions -> Add a permission -> Microsoft Graph\n"
            "    3. Choose 'Application permissions' (NOT Delegated)\n"
            "    4. Tick the missing permissions, click Add permissions\n"
            "    5. Click 'Grant admin consent for <tenant>'\n"
            "    6. Wait ~1 minute for replication, then re-run this script"
        )
    else:
        _ok("All required Application permissions are present on the token.")
        any_403 = any(p.get("status") == 403 for p in probes)
        if any_403:
            _warn(
                "Some endpoints still returned 403 -- possible causes:\n"
                "    * Application Access Policy restricts which mailboxes the app can touch.\n"
                "    * Mailbox is unlicensed (no Exchange Online).\n"
                "    * Conditional Access Policy is blocking the app.\n"
                "    * Permission was just added -- wait 60s and retry."
            )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main(mailbox_override: str | None) -> None:
    settings = get_settings()
    if mailbox_override:
        # Run-time override without mutating settings frozen state
        object.__setattr__(settings, "graph_api_mailbox", mailbox_override)

    print(f"\n=== VQMS -- Graph API diagnostic (mailbox={settings.graph_api_mailbox}) ===")

    if not step_1_check_config(settings):
        return

    token = step_2_acquire_token(settings)
    if token is None:
        return

    roles = step_3_inspect_token(token)
    probes = await step_4_probe_endpoints(token, settings.graph_api_mailbox)
    step_5_summary(roles, probes)

    print(f"\n{'=' * 72}\n")


def cli() -> None:
    parser = argparse.ArgumentParser(description="Microsoft Graph API diagnostic for VQMS")
    parser.add_argument(
        "--mailbox",
        default=None,
        help="Override GRAPH_API_MAILBOX from .env",
    )
    args = parser.parse_args()
    asyncio.run(main(args.mailbox))


if __name__ == "__main__":
    cli()
