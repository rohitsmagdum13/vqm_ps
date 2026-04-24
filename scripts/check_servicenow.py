"""Script: check_servicenow.py

Verify ServiceNow connectivity and auth for VQMS.

Tests:
  1. URL resolution (instance_url vs instance_name + credentials present)
  2. Basic connectivity + auth (GET /api/now/table/incident?sysparm_limit=1)
  3. Read-your-own-user check (GET /api/now/table/sys_user?user_name=...)
  4. Optional: fetch a specific incident if --incident is passed

Uses the real ServiceNowConnector so it exercises the same code path
the application uses — OR, with --username/--password, uses raw httpx
to bypass .env parsing entirely (useful for ruling out dotenv quoting
issues with special characters like $ in the password).

Usage:
    uv run python scripts/check_servicenow.py
    uv run python scripts/check_servicenow.py --incident INC0010001
    uv run python scripts/check_servicenow.py --username admin --password "MyPass!"
    uv run python scripts/check_servicenow.py --instance dev123456 \
        --username admin --password "MyPass!"
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

import httpx

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


def build_base_url_from_inputs(
    instance_url: str | None,
    instance_name: str | None,
) -> str:
    """Mirror the adapter's URL resolution, for CLI-override mode."""
    url = (instance_url or "").strip()
    if url:
        return url.rstrip("/")
    name = (instance_name or "").strip()
    if name:
        short = name
        if "://" in short:
            short = short.split("://", 1)[1]
        short = short.split("/", 1)[0].split(".", 1)[0].rstrip("/")
        if short:
            return f"https://{short}.service-now.com"
    raise ValueError(
        "Provide either --instance-url (full URL) or --instance (short name) "
        "on the CLI, or configure one of them in .env"
    )


async def fetch_oauth_token(
    base_url: str,
    username: str,
    password: str,
    client_id: str,
    client_secret: str,
) -> tuple[str | None, str]:
    """Get an OAuth2 access token via the password grant type.

    Returns (token, detail_or_error). token is None on failure and
    detail_or_error holds the reason for display.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as token_client:
            resp = await token_client.post(
                f"{base_url}/oauth_token.do",
                data={
                    "grant_type": "password",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "username": username,
                    "password": password,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if resp.status_code == 200:
            payload = resp.json()
            return payload.get("access_token"), "OK"
        return None, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


async def check_servicenow(
    incident_number: str | None = None,
    *,
    cli_username: str | None = None,
    cli_password: str | None = None,
    cli_instance_url: str | None = None,
    cli_instance_name: str | None = None,
    use_oauth: bool = False,
) -> int:
    """Run all ServiceNow connectivity checks.

    If cli_username/cli_password are provided, they override whatever is in
    .env and the script uses a raw httpx.AsyncClient (skipping the adapter's
    settings object). This rules out dotenv quoting issues.

    Returns:
        0 if everything critical passed, 1 otherwise. Useful for CI.
    """
    LoggingSetup.configure()
    settings = get_settings()

    using_cli_overrides = any(
        v is not None
        for v in (cli_username, cli_password, cli_instance_url, cli_instance_name)
    )

    # Resolve effective values (CLI wins over .env)
    eff_username = cli_username if cli_username is not None else settings.servicenow_username
    eff_password = cli_password if cli_password is not None else settings.servicenow_password
    eff_instance_url = (
        cli_instance_url
        if cli_instance_url is not None
        else settings.servicenow_instance_url
    )
    eff_instance_name = (
        cli_instance_name
        if cli_instance_name is not None
        else settings.servicenow_instance_name
    )

    print_header("VQMS — ServiceNow Connectivity Check")
    src = "CLI override" if using_cli_overrides else ".env"
    print(f"  Config source: {src}")
    print(f"  Instance URL:  {eff_instance_url or '(not set)'}")
    print(f"  Instance Name: {eff_instance_name or '(not set)'}")
    print(f"  Username:      {eff_username or '(not set)'}")
    print(
        f"  Password:      {mask_password(eff_password)} "
        f"(len={len(eff_password) if eff_password else 0})"
    )
    print()

    # --- Check 0: Credentials present ---
    if not eff_username or not eff_password:
        print_check(
            "Credentials configured",
            False,
            "username / password missing (pass --username/--password or set in .env)",
        )
        return 1
    print_check("Credentials configured", True)

    # Warn if password contains $ and came from .env — some dotenv loaders
    # interpret $foo as variable expansion and strip it.
    if (
        not using_cli_overrides
        and eff_password
        and "$" in eff_password
        and settings.servicenow_password == eff_password
    ):
        print(
            "  [WARN] Password from .env contains a '$'. If auth fails, your "
            ".env loader\n"
            "         may be expanding it. Try one of:\n"
            "           - Re-run this script with --password "
            "\"<the-literal-password>\"\n"
            "           - In .env, escape: SERVICENOW_PASSWORD='<pw>'  "
            "(single quotes, no angle brackets)"
        )

    # --- Check 1: URL resolution ---
    if using_cli_overrides:
        try:
            base_url = build_base_url_from_inputs(eff_instance_url, eff_instance_name)
            print_check("URL resolution", True, base_url)
        except ValueError as e:
            print_check("URL resolution", False, str(e))
            return 1
        connector = None
    else:
        connector = ServiceNowConnector(settings)
        try:
            base_url = connector._resolve_base_url()
            print_check("URL resolution", True, base_url)
        except ServiceNowConnectorError as e:
            print_check("URL resolution", False, str(e))
            print()
            print("  Hint: set either SERVICENOW_INSTANCE_URL (full URL) or")
            print("        SERVICENOW_INSTANCE_NAME (short name, e.g. 'dev123456')")
            print("        in your .env file, then re-run this script.")
            return 1

    all_passed = True

    # --- OAuth path (optional) ---
    if use_oauth:
        client_id = settings.servicenow_client_id
        client_secret = settings.servicenow_client_secret
        if not client_id or not client_secret:
            print_check(
                "OAuth token request",
                False,
                "SERVICENOW_CLIENT_ID / SERVICENOW_CLIENT_SECRET not set",
            )
            return 1
        token, detail = await fetch_oauth_token(
            base_url, eff_username, eff_password, client_id, client_secret
        )
        if not token:
            print_check("OAuth token request", False, detail)
            print()
            print("  Hint: register an OAuth Application Registry entry in")
            print("        ServiceNow (System OAuth > Application Registry)")
            print("        with grant_type = password, then set")
            print("        SERVICENOW_CLIENT_ID and SERVICENOW_CLIENT_SECRET.")
            return 1
        print_check(
            "OAuth token request",
            True,
            f"token={token[:8]}...{token[-4:]} (len={len(token)})",
        )
        client = httpx.AsyncClient(
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            timeout=30.0,
        )
    # When CLI overrides are in use, build a fresh httpx client with the
    # overridden credentials. Otherwise use the adapter's client.
    elif using_cli_overrides:
        client = httpx.AsyncClient(
            auth=(eff_username, eff_password),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
    else:
        assert connector is not None
        client = connector._get_client()

    try:

        # --- Check 2: Basic connectivity + auth (list 1 incident) ---
        try:
            start = time.perf_counter()
            response = await client.get(
                f"{base_url}/api/now/table/incident",
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
                # Surface the WWW-Authenticate header — this is the server
                # telling us which auth scheme it expects. "Basic" means basic
                # auth IS enabled and the creds are wrong. Anything else
                # (Bearer, SSO redirect, OAuth) means basic auth is disabled.
                www_auth = response.headers.get(
                    "www-authenticate", "(not present)"
                )
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
                f"{base_url}/api/now/table/sys_user",
                params={
                    "sysparm_limit": "1",
                    "sysparm_query": f"user_name={eff_username}",
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
                    f"{base_url}/api/now/table/incident",
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
        if use_oauth or using_cli_overrides:
            await client.aclose()
        elif connector is not None:
            await connector.close()

    print(f"\n{'=' * 60}\n")

    if all_passed:
        print("  [OK] ServiceNow is reachable and auth is working.")
    else:
        print("  [ERROR] One or more critical checks failed — see above.")
        print()
        print("  If browser login works but the API returns 401, the most")
        print("  likely cause is that the instance has disabled basic auth")
        print("  for REST (common on corporate/SSO-protected instances).")
        print()
        print("  Next steps, in order:")
        print("    1. Check the WWW-Authenticate header printed above. If it")
        print("       says anything other than 'Basic realm=...', basic auth")
        print("       is NOT what the server wants.")
        print("    2. Ask your ServiceNow admin to either:")
        print("         (a) enable basic auth for REST, OR")
        print("         (b) create an OAuth Application Registry entry so you")
        print("             can use --oauth. You'll get a client_id and")
        print("             client_secret to put in .env. Then re-run with:")
        print("               uv run python scripts/check_servicenow.py --oauth")
        print("    3. Confirm your user has the 'rest_service' or")
        print("       'web_service_admin' role (View > Roles on your user).")
        print(f"    4. Browser login sanity check: visit {base_url}/")
        print("       then /api/now/table/incident?sysparm_limit=1 directly")
        print("       from the same browser tab. If that returns JSON, your")
        print("       user CAN use REST — it's the auth scheme that's wrong.")
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
    parser.add_argument(
        "--username",
        dest="username",
        default=None,
        help="Override the username from .env. Useful to rule out .env parsing.",
    )
    parser.add_argument(
        "--password",
        dest="password",
        default=None,
        help=(
            "Override the password from .env. Wrap in double quotes if it "
            "contains special characters."
        ),
    )
    parser.add_argument(
        "--instance",
        dest="instance",
        default=None,
        help=(
            "Override the instance short name from .env "
            "(e.g. 'dev123456' for https://dev123456.service-now.com)."
        ),
    )
    parser.add_argument(
        "--instance-url",
        dest="instance_url",
        default=None,
        help="Override the full instance URL from .env.",
    )
    parser.add_argument(
        "--oauth",
        dest="use_oauth",
        action="store_true",
        help=(
            "Authenticate via OAuth2 password grant instead of HTTP Basic. "
            "Requires SERVICENOW_CLIENT_ID and SERVICENOW_CLIENT_SECRET in "
            ".env (from System OAuth > Application Registry on the instance)."
        ),
    )
    args = parser.parse_args()

    exit_code = asyncio.run(
        check_servicenow(
            incident_number=args.incident,
            cli_username=args.username,
            cli_password=args.password,
            cli_instance_url=args.instance_url,
            cli_instance_name=args.instance,
            use_oauth=args.use_oauth,
        )
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
