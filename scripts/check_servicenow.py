"""Script: check_servicenow.py

Verify ServiceNow connectivity and auth for VQMS.

Tests:
  1. URL resolution (instance_url vs instance_name + credentials present)
  2. Basic connectivity + auth (GET /api/now/table/incident?sysparm_limit=1)
  3. Read-your-own-user check (GET /api/now/table/sys_user?user_name=...)
  4. Optional: fetch a specific incident if --incident is passed

Uses the real ServiceNowConnector so it exercises the same code path
the application uses.

Usage:
    uv run python scripts/check_servicenow.py
    uv run python scripts/check_servicenow.py --incident INC0010001
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

# Add src/ to Python path so imports work when run directly
sys.path.insert(0, ".")
sys.path.insert(0, "src")

from config.settings import get_settings  # noqa: E402
from adapters.servicenow import (  # noqa: E402
    ServiceNowConnector,
    ServiceNowConnectorError,
)
from utils.logger import LoggingSetup  # noqa: E402


def print_header(text: str) -> None:
    """Print a section header."""
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}\n")


def print_check(name: str, passed: bool, detail: str = "") -> None:
    """Print a check result line."""
    status = "[PASS]" if passed else "[FAIL]"
    suffix = f" — {detail}" if detail else ""
    print(f"  {status} {name}{suffix}")


def mask_password(password: str | None) -> str:
    """Return a safe-to-print representation of a password."""
    if not password:
        return "(not set)"
    if len(password) <= 4:
        return "*" * len(password)
    return f"{password[0]}{'*' * (len(password) - 2)}{password[-1]}"


async def check_servicenow(incident_number: str | None = None) -> int:
    """Run all ServiceNow connectivity checks.

    Returns:
        0 if everything critical passed, 1 otherwise. Useful for CI.
    """
    LoggingSetup.configure()
    settings = get_settings()

    print_header("VQMS — ServiceNow Connectivity Check")
    print(f"  Instance URL:  {settings.servicenow_instance_url or '(not set)'}")
    print(f"  Instance Name: {settings.servicenow_instance_name or '(not set)'}")
    print(f"  Username:      {settings.servicenow_username or '(not set)'}")
    print(f"  Password:      {mask_password(settings.servicenow_password)}")
    print(f"  Assignment Gr: {settings.servicenow_assignment_group or '(not set)'}")
    print()

    # --- Check 0: Credentials present ---
    if not settings.servicenow_username or not settings.servicenow_password:
        print_check(
            "Credentials configured",
            False,
            "SERVICENOW_USERNAME / SERVICENOW_PASSWORD missing in .env",
        )
        return 1
    print_check("Credentials configured", True)

    # --- Check 1: URL resolution via the adapter ---
    connector = ServiceNowConnector(settings)
    try:
        resolved = connector._resolve_base_url()
        print_check("URL resolution", True, resolved)
    except ServiceNowConnectorError as e:
        print_check("URL resolution", False, str(e))
        print()
        print("  Hint: set either SERVICENOW_INSTANCE_URL (full URL) or")
        print("        SERVICENOW_INSTANCE_NAME (short name, e.g. 'dev123456')")
        print("        in your .env file, then re-run this script.")
        return 1

    all_passed = True

    try:
        client = connector._get_client()

        # --- Check 2: Basic connectivity + auth (list 1 incident) ---
        try:
            start = time.perf_counter()
            response = await client.get(
                f"{connector._base_url}/api/now/table/incident",
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
                print_check(
                    "Connectivity + auth (GET /incident)",
                    False,
                    "HTTP 401 Unauthorized — check username / password",
                )
                all_passed = False
            elif response.status_code == 403:
                print_check(
                    "Connectivity + auth (GET /incident)",
                    False,
                    "HTTP 403 Forbidden — user lacks read on incident table",
                )
                all_passed = False
            else:
                print_check(
                    "Connectivity + auth (GET /incident)",
                    False,
                    f"HTTP {response.status_code}: {response.text[:150]}",
                )
                all_passed = False
        except Exception as e:
            print_check(
                "Connectivity + auth (GET /incident)",
                False,
                f"{type(e).__name__}: {e}",
            )
            all_passed = False

        # --- Check 3: Self-user lookup (confirms auth identity) ---
        try:
            start = time.perf_counter()
            response = await client.get(
                f"{connector._base_url}/api/now/table/sys_user",
                params={
                    "sysparm_limit": "1",
                    "sysparm_query": f"user_name={settings.servicenow_username}",
                    "sysparm_fields": "user_name,name,email,active,roles",
                },
            )
            elapsed = (time.perf_counter() - start) * 1000

            if response.status_code == 200:
                data = response.json()
                records = data.get("result", []) or []
                if records:
                    user = records[0]
                    print_check(
                        "Self-user lookup",
                        True,
                        f"{elapsed:.0f}ms",
                    )
                    print(f"          user_name: {user.get('user_name', '?')}")
                    print(f"          name:      {user.get('name', '?')}")
                    print(f"          email:     {user.get('email', '?')}")
                    print(f"          active:    {user.get('active', '?')}")
                else:
                    # 200 + empty result means either the user name doesn't
                    # match an sys_user row, or the account has no read access
                    # on sys_user. Not always fatal for ticket ops.
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
                # Non-critical — ticket create/read may still work.
        except Exception as e:
            print_check("Self-user lookup", False, f"{type(e).__name__}: {e}")

        # --- Check 4: Optional specific-incident fetch ---
        if incident_number:
            try:
                start = time.perf_counter()
                response = await client.get(
                    f"{connector._base_url}/api/now/table/incident",
                    params={
                        "sysparm_limit": "1",
                        "sysparm_query": f"number={incident_number}",
                        "sysparm_fields": (
                            "number,sys_id,state,short_description,"
                            "priority,assignment_group,opened_at"
                        ),
                    },
                )
                elapsed = (time.perf_counter() - start) * 1000

                if response.status_code == 200:
                    records = response.json().get("result", []) or []
                    if records:
                        rec = records[0]
                        print_check(
                            f"Fetch incident {incident_number}",
                            True,
                            f"{elapsed:.0f}ms",
                        )
                        print(f"          number:   {rec.get('number', '?')}")
                        print(f"          state:    {rec.get('state', '?')}")
                        print(f"          priority: {rec.get('priority', '?')}")
                        print(
                            f"          summary:  "
                            f"{rec.get('short_description', '')[:80]}"
                        )
                    else:
                        print_check(
                            f"Fetch incident {incident_number}",
                            False,
                            "incident not found",
                        )
                        all_passed = False
                else:
                    print_check(
                        f"Fetch incident {incident_number}",
                        False,
                        f"HTTP {response.status_code}: {response.text[:150]}",
                    )
                    all_passed = False
            except Exception as e:
                print_check(
                    f"Fetch incident {incident_number}",
                    False,
                    f"{type(e).__name__}: {e}",
                )
                all_passed = False

    finally:
        await connector.close()

    print(f"\n{'=' * 60}\n")

    if all_passed:
        print("  [OK] ServiceNow is reachable and auth is working.")
    else:
        print("  [ERROR] One or more critical checks failed — see above.")
    print()

    return 0 if all_passed else 1


def main() -> None:
    """Parse args and run the check."""
    parser = argparse.ArgumentParser(
        description="Verify ServiceNow connectivity and auth.",
    )
    parser.add_argument(
        "--incident",
        dest="incident",
        default=None,
        help=(
            "Optional ServiceNow incident number to fetch as an extra check "
            "(e.g. INC0010001)."
        ),
    )
    args = parser.parse_args()

    exit_code = asyncio.run(check_servicenow(incident_number=args.incident))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
