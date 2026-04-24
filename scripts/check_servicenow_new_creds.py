"""Script: check_servicenow_new_creds.py

Verify the new ServiceNow credentials (Hexaware Hong Kong demo 5) without
touching .env. Credentials are hardcoded in this file so that .env quoting
issues with the '$' character cannot cause false negatives.

Tests:
  1. Basic connectivity + auth (GET /api/now/table/incident?sysparm_limit=1)
  2. Self-user lookup (GET /api/now/table/sys_user?user_name=...)

Usage:
    uv run python scripts/check_servicenow_new_creds.py
"""

from __future__ import annotations

import asyncio
import sys
import time

import httpx

# --- Hardcoded credentials as provided by user ---
SERVICENOW_INSTANCE_NAME: str = "hexawaretechnologieshongkongltddemo5"
SERVICENOW_USERNAME: str = "ArunkumarV@hexaware.com"
SERVICENOW_PASSWORD: str = "Hex@BP$_2025"
SERVICENOW_BASE_URL: str = f"https://{SERVICENOW_INSTANCE_NAME}.service-now.com"


def print_header(text: str) -> None:
    """Print a section header."""
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}\n")


def print_check(name: str, passed: bool, detail: str = "") -> None:
    """Print a check result line."""
    status = "[PASS]" if passed else "[FAIL]"
    suffix = f" - {detail}" if detail else ""
    print(f"  {status} {name}{suffix}")


def mask_password(password: str) -> str:
    """Return a safe-to-print representation of a password."""
    if not password:
        return "(empty)"
    if len(password) <= 4:
        return "*" * len(password)
    return f"{password[0]}{'*' * (len(password) - 2)}{password[-1]}"


async def check_servicenow() -> int:
    """Run ServiceNow connectivity checks against the hardcoded credentials.

    Returns:
        0 if everything critical passed, 1 otherwise.
    """
    print_header("VQMS - ServiceNow New Credentials Check (bypasses .env)")
    print(f"  Base URL:  {SERVICENOW_BASE_URL}")
    print(f"  Username:  {SERVICENOW_USERNAME}")
    print(
        f"  Password:  {mask_password(SERVICENOW_PASSWORD)} "
        f"(len={len(SERVICENOW_PASSWORD)})"
    )
    print()

    all_passed = True

    async with httpx.AsyncClient(
        auth=(SERVICENOW_USERNAME, SERVICENOW_PASSWORD),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=30.0,
        follow_redirects=False,
    ) as client:

        # --- Check 1: Basic connectivity + auth (list 1 incident) ---
        try:
            start = time.perf_counter()
            response = await client.get(
                f"{SERVICENOW_BASE_URL}/api/now/table/incident",
                params={
                    "sysparm_limit": "1",
                    "sysparm_fields": "number,sys_id,short_description,state",
                },
            )
            elapsed = (time.perf_counter() - start) * 1000

            if response.status_code == 200:
                data = response.json()
                records = data.get("result", []) or []
                print_check(
                    "Connectivity + auth (GET /incident)",
                    True,
                    f"HTTP 200, {len(records)} record(s), {elapsed:.0f}ms",
                )
                for rec in records:
                    print(
                        f"          {rec.get('number', '?')} "
                        f"(state={rec.get('state', '?')}): "
                        f"{rec.get('short_description', '')[:60]}"
                    )
            elif response.status_code == 401:
                www_auth = response.headers.get("www-authenticate", "(not present)")
                x_is_sso = response.headers.get("x-is-logged-in", "?")
                body_preview = response.text[:200].replace("\n", " ")
                print_check(
                    "Connectivity + auth (GET /incident)",
                    False,
                    "HTTP 401 Unauthorized",
                )
                print(f"          WWW-Authenticate: {www_auth}")
                print(f"          X-Is-Logged-In:   {x_is_sso}")
                print(f"          Body: {body_preview}")
                all_passed = False
            elif response.status_code in (302, 303, 307, 308):
                location = response.headers.get("location", "(not present)")
                print_check(
                    "Connectivity + auth (GET /incident)",
                    False,
                    f"HTTP {response.status_code} redirect to {location[:120]}",
                )
                print(
                    "          A redirect usually means the instance uses "
                    "SSO (Azure AD / Okta)"
                )
                print(
                    "          and basic auth is disabled for REST. "
                    "Ask admin for an OAuth client."
                )
                all_passed = False
            elif response.status_code == 403:
                print_check(
                    "Connectivity + auth (GET /incident)",
                    False,
                    "HTTP 403 Forbidden - user lacks read on incident table",
                )
                all_passed = False
            else:
                print_check(
                    "Connectivity + auth (GET /incident)",
                    False,
                    f"HTTP {response.status_code}: {response.text[:150]}",
                )
                all_passed = False
        except Exception as e:  # noqa: BLE001
            print_check(
                "Connectivity + auth (GET /incident)",
                False,
                f"{type(e).__name__}: {e}",
            )
            all_passed = False

        # --- Check 2: Self-user lookup ---
        try:
            start = time.perf_counter()
            response = await client.get(
                f"{SERVICENOW_BASE_URL}/api/now/table/sys_user",
                params={
                    "sysparm_limit": "1",
                    "sysparm_query": f"user_name={SERVICENOW_USERNAME}",
                    "sysparm_fields": "user_name,name,email,active,roles",
                },
            )
            elapsed = (time.perf_counter() - start) * 1000

            if response.status_code == 200:
                data = response.json()
                records = data.get("result", []) or []
                if records:
                    user = records[0]
                    print_check("Self-user lookup", True, f"{elapsed:.0f}ms")
                    print(f"          user_name: {user.get('user_name', '?')}")
                    print(f"          name:      {user.get('name', '?')}")
                    print(f"          email:     {user.get('email', '?')}")
                    print(f"          active:    {user.get('active', '?')}")
                else:
                    print_check(
                        "Self-user lookup",
                        True,
                        "reachable but no sys_user row matched "
                        "(may lack read on sys_user)",
                    )
            else:
                print_check(
                    "Self-user lookup",
                    False,
                    f"HTTP {response.status_code}: {response.text[:150]}",
                )
        except Exception as e:  # noqa: BLE001
            print_check("Self-user lookup", False, f"{type(e).__name__}: {e}")

    print(f"\n{'=' * 60}\n")

    if all_passed:
        print("  [OK] ServiceNow is reachable and auth is working.")
    else:
        print("  [ERROR] One or more critical checks failed - see above.")
        print()
        print("  If the browser login at")
        print(f"    {SERVICENOW_BASE_URL}")
        print("  works but this script returns 401 or redirects to an SSO")
        print("  login page, the instance has disabled basic auth for REST.")
        print("  In that case you need an OAuth Application Registry entry")
        print("  (client_id / client_secret) from the ServiceNow admin.")
    print()

    return 0 if all_passed else 1


def main() -> None:
    """Entry point."""
    exit_code = asyncio.run(check_servicenow())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
