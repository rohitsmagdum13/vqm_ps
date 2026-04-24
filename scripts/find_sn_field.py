"""Script: find_sn_field.py

Discover the actual column name behind a ServiceNow field *label*.

ServiceNow lets admins rename the label of a column but keeps the
underlying name stable. "Affected User" might be rendered by any of:
  - caller_id
  - u_affected_user
  - u_end_user
  - u_affected_person
  - u_impacted_user
...etc. The actual column name comes from sys_dictionary. This script
queries sys_dictionary for any row whose ``column_label`` matches the
search term on the given table (default: incident).

Usage:
    uv run python scripts/find_sn_field.py
    uv run python scripts/find_sn_field.py --label "Affected User"
    uv run python scripts/find_sn_field.py --label Affected --table incident
"""

from __future__ import annotations

import argparse
import asyncio
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "src")

from adapters.servicenow import ServiceNowConnector  # noqa: E402
from config.settings import get_settings  # noqa: E402
from utils.logger import LoggingSetup  # noqa: E402


def header(text: str) -> None:
    print(f"\n{'=' * 72}\n  {text}\n{'=' * 72}\n")


async def run(label: str, table: str) -> int:
    """Query sys_dictionary for any column matching ``label`` on ``table``."""
    LoggingSetup.configure()
    settings = get_settings()

    sn = ServiceNowConnector(settings)
    try:
        base_url = sn._resolve_base_url()
    except Exception as exc:  # noqa: BLE001
        print(f"  [ERROR] Could not resolve ServiceNow URL: {exc}")
        return 1

    header(f"Looking for columns labeled LIKE '{label}' on table '{table}'")
    print(f"  Instance: {base_url}\n")

    client = sn._get_client()

    # sys_dictionary is ServiceNow's schema catalog. `name` = table name,
    # `element` = column name, `column_label` = the UI label.
    response = await client.get(
        f"{base_url}/api/now/table/sys_dictionary",
        params={
            "sysparm_query": (
                f"name={table}^column_labelLIKE{label}^internal_type=reference"
            ),
            "sysparm_fields": "element,column_label,reference,mandatory,active",
            "sysparm_display_value": "true",
            "sysparm_limit": "20",
        },
    )

    if response.status_code != 200:
        print(f"  HTTP {response.status_code}: {response.text[:250]}")
        await sn.close()
        return 1

    rows = response.json().get("result", []) or []

    if not rows:
        header("No matching reference columns found")
        print(
            f"  Nothing in sys_dictionary has column_label matching "
            f"'{label}' on table '{table}'.\n"
            "\n  Possibilities:\n"
            "    - The label is spelled differently ('End User', 'Impacted User'?)\n"
            "    - The API user lacks read access on sys_dictionary\n"
            "    - The field is a string, not a reference — rerun without"
            " the internal_type=reference clause\n"
        )
        await sn.close()
        return 0

    header(f"{len(rows)} match(es) — use the 'element' name in the adapter")
    for r in rows:
        element = r.get("element") or "?"
        col_label = r.get("column_label") or "?"
        ref_table = r.get("reference") or "(not a reference)"
        print(f"  column      : {element}")
        print(f"  UI label    : {col_label}")
        print(f"  references  : {ref_table}")
        print(f"  mandatory   : {r.get('mandatory')}")
        print(f"  active      : {r.get('active')}")
        print()

    print(
        "  To make VQMS populate one of these, add to .env:\n"
        "    SERVICENOW_AFFECTED_USER_FIELD=<column name from above>\n"
        "  and re-deploy. The adapter will set it to the same user\n"
        "  value it uses for caller_id.\n"
    )

    await sn.close()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover the real column name behind a ServiceNow field label.",
    )
    parser.add_argument(
        "--label",
        default="Affected",
        help="Substring of the UI column label to match (default: 'Affected').",
    )
    parser.add_argument(
        "--table",
        default="incident",
        help="Table name to search (default: incident).",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(run(label=args.label, table=args.table)))


if __name__ == "__main__":
    main()
