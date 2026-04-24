"""Script: inspect_ticket.py

Dump every user/state/filter-relevant field of a single ServiceNow
incident so we can see *exactly* why it does or doesn't match a given
UI filter.

Returns BOTH the display_value (what the UI renders) AND the raw
sys_id (what the database actually stores). The two can diverge —
for example, if the adapter writes ``caller_id = "Arun"`` but the
display name "Arun" resolves ambiguously (multiple users with that
name), ServiceNow may leave the field blank even though the POST
returned 201 Created.

Usage:
    uv run python scripts/inspect_ticket.py INC0010017
    uv run python scripts/inspect_ticket.py --compare-user ArunkumarV@hexaware.com INC0010017
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "src")

from adapters.servicenow import ServiceNowConnector  # noqa: E402
from config.settings import get_settings  # noqa: E402
from utils.logger import LoggingSetup  # noqa: E402


def header(text: str) -> None:
    print(f"\n{'=' * 78}\n  {text}\n{'=' * 78}\n")


def _show(label: str, value: object) -> None:
    """Print a field that may be a display_value/link dict or a scalar."""
    if isinstance(value, dict):
        disp = value.get("display_value") or ""
        link = value.get("link") or ""
        print(f"  {label:<25} display='{disp}'")
        print(f"  {'':<25} sys_id-link={link}")
    else:
        rendered = value if value not in (None, "") else "(empty)"
        print(f"  {label:<25} {rendered}")


async def run(number: str, compare_user: str | None) -> int:
    """Fetch a ticket by number and print all user/state/filter fields."""
    LoggingSetup.configure()
    settings = get_settings()

    sn = ServiceNowConnector(settings)
    try:
        base_url = sn._resolve_base_url()
    except Exception as exc:  # noqa: BLE001
        print(f"  [ERROR] Could not resolve ServiceNow URL: {exc}")
        return 1

    header(f"Inspecting incident {number}")
    print(f"  Instance: {base_url}\n")

    client = sn._get_client()

    # --- Fetch the ticket with both display values AND raw values ---
    # Two calls: one with display_value=true (what the UI sees), one
    # without (raw sys_ids). That's the only way to tell whether a
    # reference field actually has a resolved link vs a dangling
    # display-only string.
    response = await client.get(
        f"{base_url}/api/now/table/incident",
        params={
            "sysparm_query": f"number={number}",
            "sysparm_display_value": "all",  # include both
            "sysparm_limit": "1",
        },
    )
    if response.status_code != 200:
        print(f"  HTTP {response.status_code}: {response.text[:250]}")
        await sn.close()
        return 1

    rows = response.json().get("result", []) or []
    if not rows:
        print(f"  No incident found with number={number}")
        await sn.close()
        return 1

    rec = rows[0]

    # --- Relevant fields for filter matching ---
    header("Filter-relevant fields")
    for key in (
        "number",
        "sys_id",
        "active",
        "state",
        "caller_id",
        "opened_by",
        "assigned_to",
        "assignment_group",
        "u_affected_user",
        "u_vqms_query_id",
        "sys_created_on",
        "short_description",
    ):
        _show(key, rec.get(key))

    # --- Does caller_id.value resolve to a real sys_user? ---
    caller_raw = rec.get("caller_id")
    if isinstance(caller_raw, dict):
        caller_display = caller_raw.get("display_value") or ""
        caller_link = caller_raw.get("link") or ""
        header("caller_id diagnostic")
        print(f"  caller_id.display_value : {caller_display!r}")
        print(f"  caller_id.link          : {caller_link!r}")
        if not caller_link:
            print(
                "\n  [PROBLEM] The caller_id display is set but there is no"
                "\n  link to a sys_user record — the reference is UNRESOLVED."
                "\n  That's why the 'Affected User = <name>' filter won't"
                "\n  match: the UI filter compares sys_user sys_ids, not"
                "\n  free-text display names."
                "\n\n  Most common cause: multiple sys_user rows share that"
                "\n  display name (e.g. 'Arun'), so ServiceNow refuses to"
                "\n  pick one automatically."
            )
        else:
            print(
                "\n  [OK] caller_id resolves to a real sys_user. The filter"
                "\n  should match — try refreshing the UI list view."
            )

    # --- Optionally compare against the user .env thinks is the caller ---
    if compare_user:
        header(f"Cross-check: sys_user lookup for '{compare_user}'")
        resp = await client.get(
            f"{base_url}/api/now/table/sys_user",
            params={
                "sysparm_query": f"user_name={compare_user}",
                "sysparm_fields": "sys_id,user_name,name,email,active",
                "sysparm_limit": "5",
            },
        )
        if resp.status_code == 200:
            users = resp.json().get("result", []) or []
            if not users:
                print(f"  No sys_user with user_name='{compare_user}'")
            for u in users:
                print(json.dumps(u, indent=2, ensure_ascii=False))

            # Also find how many users share the display NAME (not user_name).
            # This is the real litmus test: if >1 user has name='Arun',
            # the display-value POST will leave caller_id unresolved.
            if users:
                display_name = users[0].get("name", "")
                if display_name:
                    resp2 = await client.get(
                        f"{base_url}/api/now/table/sys_user",
                        params={
                            "sysparm_query": f"name={display_name}",
                            "sysparm_fields": "sys_id,user_name,name",
                            "sysparm_limit": "10",
                        },
                    )
                    homonyms = resp2.json().get("result", []) or []
                    header(f"Users sharing display name '{display_name}'")
                    print(f"  Count: {len(homonyms)}")
                    for u in homonyms:
                        print(
                            f"    - sys_id={u.get('sys_id')[:12]}...  "
                            f"user_name={u.get('user_name')}  "
                            f"name={u.get('name')}"
                        )
                    if len(homonyms) > 1:
                        print(
                            "\n  [PROBLEM] More than one user shares the "
                            f"display name '{display_name}'."
                            "\n  When the adapter POSTs caller_id='"
                            f"{display_name}' with "
                            "sysparm_input_display_value=true, "
                            "ServiceNow"
                            "\n  cannot pick which sys_user to link to and "
                            "leaves caller_id unresolved."
                            "\n\n  Fix: change the adapter to POST the sys_id"
                            " directly, or switch to"
                            "\n  sysparm_input_display_value=false and look "
                            "up the sys_id before POST."
                        )
                    elif len(homonyms) == 1:
                        print(
                            "\n  [OK] Only one user has this display name. "
                            "The display-value POST should resolve cleanly."
                        )
        else:
            print(f"  HTTP {resp.status_code}: {resp.text[:250]}")

    await sn.close()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dump every filter-relevant field of a ServiceNow incident.",
    )
    parser.add_argument(
        "number",
        help="Incident number, e.g. INC0010017",
    )
    parser.add_argument(
        "--compare-user",
        default=None,
        help=(
            "Look up this sys_user.user_name and check whether its display "
            "name collides with other users — a common reason the "
            "'Affected User' filter fails to match."
        ),
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(run(number=args.number, compare_user=args.compare_user)))


if __name__ == "__main__":
    main()
