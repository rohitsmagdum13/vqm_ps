"""End-to-end verification for the vendor_category routing change.

Exercises every layer that was modified, against real services:

  1. Run migration 020 (idempotent) — adds vendor_name, vendor_tier,
     vendor_category columns to cache.vendor_cache.
  2. Verify the columns exist by querying information_schema.
  3. Hit Salesforce find_vendor_by_id for a known vendor — confirm
     Category__c is now in the returned record.
  4. Build a VendorProfile from the Salesforce record — confirm
     vendor_category lands on the model.
  5. Write the profile via ContextLoadingNode._write_vendor_cache —
     confirm cache.vendor_cache row has the new columns populated.
  6. Read the cache row back via cache_read — confirm the dedicated
     columns are returned and a profile rebuilt from the row keeps
     vendor_category intact.
  7. Render query_analysis_v1.j2 with the loaded vendor — confirm
     the Vendor Category line and routing-rules section are present.
  8. Run resolve_assignment_group() over a primary, secondary, and
     fallback case — confirm the 6-group taxonomy resolves correctly.

Usage:
    uv run python scripts/verify_vendor_category_flow.py [VENDOR_ID]

VENDOR_ID defaults to V-001. Pass any active Vendor_ID__c to test
with different category values.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
sys.path.insert(0, "src")

from config.settings import get_settings  # noqa: E402
from db.connection import PostgresConnector  # noqa: E402
from adapters.salesforce import SalesforceConnector  # noqa: E402
from orchestration.nodes.context_loading import ContextLoadingNode  # noqa: E402
from orchestration.nodes.routing import (  # noqa: E402
    VALID_ASSIGNMENT_GROUPS,
    resolve_assignment_group,
)
from orchestration.prompts.prompt_manager import PromptManager  # noqa: E402
from utils.logger import LoggingSetup  # noqa: E402

MIGRATIONS_DIR = Path("src/db/migrations")


def _ok(msg: str) -> None:
    print(f"  [PASS] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")
    raise SystemExit(1)


def _info(msg: str) -> None:
    print(f"  [INFO] {msg}")


async def _step_1_run_migration(pg: PostgresConnector) -> None:
    print("\n[1] Running migrations (idempotent)...")
    pg.run_migrations_sync(str(MIGRATIONS_DIR))
    _ok("Migrations executed")


async def _step_2_verify_columns(pg: PostgresConnector) -> None:
    print("\n[2] Verifying cache.vendor_cache columns exist...")
    rows = await pg.fetch(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'cache' AND table_name = 'vendor_cache'
        ORDER BY ordinal_position
        """
    )
    columns = {r["column_name"]: r["data_type"] for r in rows}
    for col in ("vendor_name", "vendor_tier", "vendor_category"):
        if col not in columns:
            _fail(f"column {col} missing from cache.vendor_cache")
        _ok(f"cache.vendor_cache.{col} :: {columns[col]}")


async def _step_3_salesforce_lookup(
    sf: SalesforceConnector, vendor_id: str
) -> dict:
    print(f"\n[3] Hitting Salesforce find_vendor_by_id('{vendor_id}')...")
    record = await sf.find_vendor_by_id(vendor_id, correlation_id="verify-flow")
    if record is None:
        _fail(f"Salesforce returned no record for {vendor_id}")
    _info(f"raw record keys = {sorted(record.keys())}")
    if "Category__c" not in record:
        _fail("Category__c missing from Salesforce record — SOQL not updated?")
    _ok(f"Category__c present: {record.get('Category__c')!r}")
    _ok(f"Vendor_Tier__c       : {record.get('Vendor_Tier__c')!r}")
    _ok(f"Name                 : {record.get('Name')!r}")
    return record


async def _step_4_build_profile(node: ContextLoadingNode, sf_record: dict, vendor_id: str):
    print("\n[4] Building VendorProfile from Salesforce record...")
    profile = node._build_vendor_profile_from_salesforce(sf_record, vendor_id)
    _ok(f"profile.vendor_id       = {profile.vendor_id}")
    _ok(f"profile.vendor_name     = {profile.vendor_name}")
    _ok(f"profile.tier.tier_name  = {profile.tier.tier_name}")
    _ok(f"profile.vendor_category = {profile.vendor_category!r}")
    return profile


async def _step_5_write_cache(node: ContextLoadingNode, profile) -> None:
    print("\n[5] Writing profile via ContextLoadingNode._write_vendor_cache...")
    await node._write_vendor_cache(profile, "verify-flow")
    _ok("cache write executed without raising")


async def _step_6_read_cache(pg: PostgresConnector, vendor_id: str):
    print("\n[6] Reading cache.vendor_cache row back...")
    row = await pg.fetchrow(
        """
        SELECT vendor_id, vendor_name, vendor_tier, vendor_category,
               cache_data, expires_at
        FROM cache.vendor_cache
        WHERE vendor_id = $1
        """,
        vendor_id,
    )
    if row is None:
        _fail(f"no cache row for {vendor_id} after write")
    _ok(f"vendor_id       = {row['vendor_id']}")
    _ok(f"vendor_name     = {row['vendor_name']}")
    _ok(f"vendor_tier     = {row['vendor_tier']}")
    _ok(f"vendor_category = {row['vendor_category']!r}")

    blob = row["cache_data"]
    if isinstance(blob, str):
        blob = json.loads(blob)
    _info(f"cache_data.vendor_category = {blob.get('vendor_category')!r}")
    if blob.get("vendor_category") != row["vendor_category"]:
        _fail("cache_data.vendor_category != column vendor_category")
    _ok("JSONB blob and column agree on vendor_category")
    return row


async def _step_6b_rebuild_from_cache(node: ContextLoadingNode, row) -> None:
    print("\n[6b] Rebuilding VendorProfile from cache row...")
    profile = node._build_vendor_profile(dict(row))
    if profile.vendor_category is None:
        _fail("rebuilt profile lost vendor_category")
    _ok(f"rebuilt profile.vendor_category = {profile.vendor_category!r}")
    _ok(f"rebuilt profile.tier.tier_name  = {profile.tier.tier_name}")


def _step_7_render_prompt(profile) -> None:
    print("\n[7] Rendering query_analysis_v1.j2 with the profile...")
    pm = PromptManager()
    rendered = pm.render(
        "query_analysis_v1.j2",
        vendor_name=profile.vendor_name,
        vendor_tier=profile.tier.tier_name,
        vendor_category=profile.vendor_category or "Unknown",
        query_subject="Test invoice not paid for INV-12345",
        query_body="Hi, our invoice INV-12345 has not been paid. Please advise.",
        attachment_text="",
        recent_interactions=[],
        query_source="email",
    )
    needles = [
        "Vendor Category:",
        profile.vendor_category or "Unknown",
        "Vendor Finance – AP & Invoicing",
        "Vendor Support",
        "Routing Rules for `suggested_category`",
    ]
    for needle in needles:
        if needle in rendered:
            _ok(f"prompt contains: {needle!r}")
        else:
            _fail(f"prompt missing: {needle!r}")


def _step_8_resolver() -> None:
    print("\n[8] Spot-checking resolve_assignment_group()...")
    cases = [
        (("INVOICE_PAYMENT", "Office Supplies"), "Vendor Finance – AP & Invoicing"),
        (("TECHNICAL_SUPPORT", "IT Services"), "Vendor IT Services"),
        (("DELIVERY_SHIPMENT", "Logistics"), "Vendor Logistics Management"),
        (("ONBOARDING", "Consulting"), "Vendor Consulting Services"),
        (("WHATEVER", None), "Vendor Support"),
    ]
    for (intent, category), expected in cases:
        actual = resolve_assignment_group(intent, category)
        if actual == expected:
            _ok(f"({intent!r}, {category!r}) -> {actual!r}")
        else:
            _fail(f"({intent!r}, {category!r}) expected {expected!r}, got {actual!r}")
    if "Vendor Support" not in VALID_ASSIGNMENT_GROUPS:
        _fail("VALID_ASSIGNMENT_GROUPS missing 'Vendor Support'")
    _ok(f"VALID_ASSIGNMENT_GROUPS has {len(VALID_ASSIGNMENT_GROUPS)} entries")


async def main(vendor_id: str) -> None:
    LoggingSetup.configure()
    settings = get_settings()

    pg = PostgresConnector(settings)
    sf = SalesforceConnector(settings)
    node = ContextLoadingNode(postgres=pg, salesforce=sf, settings=settings)

    print(f"=== verify_vendor_category_flow (vendor_id={vendor_id}) ===")
    await pg.connect()
    try:
        await _step_1_run_migration(pg)
        await _step_2_verify_columns(pg)
        sf_record = await _step_3_salesforce_lookup(sf, vendor_id)
        profile = await _step_4_build_profile(node, sf_record, vendor_id)
        await _step_5_write_cache(node, profile)
        row = await _step_6_read_cache(pg, vendor_id)
        await _step_6b_rebuild_from_cache(node, row)
        _step_7_render_prompt(profile)
        _step_8_resolver()
        print("\n=== ALL CHECKS PASSED ===\n")
    finally:
        await pg.disconnect()


if __name__ == "__main__":
    vid = sys.argv[1] if len(sys.argv) > 1 else "V-001"
    asyncio.run(main(vid))
