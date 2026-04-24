"""Script: find_vqms_tickets.py

Find every ServiceNow incident created by VQMS on the instance the
current ``.env`` points at. Bypasses the ServiceNow UI entirely so
differences in default filter views don't hide tickets.

Every VQMS-created ticket carries:
- ``caller_id`` set to the display name of SERVICENOW_USERNAME
- A work-notes entry starting with "Created by VQMS"
- A ``u_vqms_query_id`` custom field (when the column exists on the
  target instance; silently dropped if it doesn't)

We query by the work-notes marker because it's the most portable
signal — custom fields are often missing on corporate instances,
but the activity log entry always lands.

Usage:
    uv run python scripts/find_vqms_tickets.py
    uv run python scripts/find_vqms_tickets.py --limit 20
    uv run python scripts/find_vqms_tickets.py --since-hours 48
"""

from __future__ import annotations

import argparse
import asyncio
import sys

# Add src/ to Python path so imports work when run directly
sys.path.insert(0, ".")
sys.path.insert(0, "src")

from adapters.servicenow import ServiceNowConnector  # noqa: E402
from config.settings import get_settings  # noqa: E402
from utils.logger import LoggingSetup  # noqa: E402


def print_header(text: str) -> None:
    """Print a section header."""
    print(f"\n{'=' * 78}\n  {text}\n{'=' * 78}\n")


async def run(limit: int, since_hours: int) -> int:
    """Fetch recent VQMS-created incidents from the current instance."""
    LoggingSetup.configure()
    settings = get_settings()

    sn = ServiceNowConnector(settings)
    try:
        base_url = sn._resolve_base_url()
    except Exception as exc:  # noqa: BLE001
        print(f"  [ERROR] Could not resolve ServiceNow base URL: {exc}")
        return 1

    # Caller display name the adapter would have stamped on tickets
    # created with the current .env credentials.
    username = (settings.servicenow_username or "").strip()
    caller_display = await sn.resolve_user_display_name(username)

    print_header("VQMS - Find Incidents by VQMS work-notes marker")
    print(f"  Instance:        {base_url}")
    print(f"  Auth user:       {username}")
    print(f"  Adapter caller:  {caller_display or '(could not resolve)'}")
    print(f"  Since:           last {since_hours}h")
    print(f"  Limit:           {limit}")
    print()

    client = sn._get_client()

    # We look for two things in parallel:
    # 1. Tickets where work_notes CONTAINS 'Created by VQMS' — the
    #    definitive marker the adapter writes on every ticket.
    # 2. The broader set of tickets whose caller matches the current
    #    SERVICENOW_USERNAME — a sanity check that tickets exist at
    #    all, even if the work-notes contains filter returns 0.
    soql_marker = (
        f"work_notesCONTAINSCreated by VQMS^"
        f"sys_created_on>=javascript:gs.hoursAgoStart({since_hours})"
    )
    soql_caller = (
        f"caller_id.user_name={username}^"
        f"sys_created_on>=javascript:gs.hoursAgoStart({since_hours})"
    )

    for label, query in [
        ("A. Tickets with 'Created by VQMS' in work_notes", soql_marker),
        ("B. Tickets where caller is the current API user", soql_caller),
    ]:
        print_header(label)
        response = await client.get(
            f"{base_url}/api/now/table/incident",
            params={
                "sysparm_query": query,
                "sysparm_fields": (
                    "number,sys_id,short_description,state,"
                    "caller_id,u_vqms_query_id,sys_created_on"
                ),
                "sysparm_display_value": "true",
                "sysparm_limit": str(limit),
            },
        )
        if response.status_code != 200:
            print(f"  [WARN] HTTP {response.status_code}: {response.text[:200]}")
            continue

        rows = response.json().get("result", []) or []
        if not rows:
            print("  (no tickets matched)")
            continue

        print(f"  {len(rows)} ticket(s) found:\n")
        for r in rows:
            # sysparm_display_value=true returns reference fields as
            # {"display_value": "...", "link": "..."} dicts. Normalise
            # everything to a plain string before formatting.
            def _text(v: object) -> str:
                if isinstance(v, dict):
                    return str(v.get("display_value") or "?")
                return str(v) if v not in (None, "") else "?"

            print(
                f"  {_text(r.get('number')):<15} "
                f"state={_text(r.get('state')):<12} "
                f"caller={_text(r.get('caller_id')):<30} "
                f"created={_text(r.get('sys_created_on'))}\n"
                f"                  "
                f"vqms_query_id={_text(r.get('u_vqms_query_id'))}\n"
                f"                  "
                f"{(_text(r.get('short_description')))[:90]}\n"
            )

    await sn.close()

    print_header("What to do with these results")
    print(
        "  - Query A returning 0 on office but >0 on personal =>"
        "\n    The office instance probably strips unknown fields but the"
        "\n    work_notes marker should always land. Zero here means no"
        "\n    VQMS ticket was created — check the pipeline logs for"
        "\n    ServiceNow errors."
    )
    print(
        "\n  - Query A returning >0 and Query B returning >0 =>"
        "\n    Tickets exist. In the UI, filter by 'Caller = Arun' (or"
        "\n    whichever caller display the adapter prints above) instead"
        "\n    of 'Affected User = Arun'. VQMS does not populate Affected"
        "\n    User; it populates Caller only."
    )
    print(
        "\n  - Query A zero but Query B >0 =>"
        "\n    Tickets exist but the adapter's work_notes marker was not"
        "\n    honored — unusual, but the instance might be stripping"
        "\n    work_notes on create."
    )
    print()
    return 0


def main() -> None:
    """Parse CLI and run."""
    parser = argparse.ArgumentParser(
        description=(
            "List ServiceNow incidents created by VQMS on the instance "
            "the current .env points at."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum incidents to list per query (default: 10).",
    )
    parser.add_argument(
        "--since-hours",
        type=int,
        default=48,
        help="Only include tickets created in the last N hours (default: 48).",
    )
    args = parser.parse_args()

    sys.exit(asyncio.run(run(limit=args.limit, since_hours=args.since_hours)))


if __name__ == "__main__":
    main()
