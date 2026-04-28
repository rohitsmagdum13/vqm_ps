# VQMS Lessons Learned

_Record mistakes, corrections, and rules to prevent repeating them._

## 2026-04-12 — paramiko 4.0 breaks sshtunnel 0.4.0
**Mistake:** Used sshtunnel without checking paramiko compatibility. paramiko 4.0 removed `DSSKey`, causing `AttributeError`.
**Correction:** Added a monkey-patch in `connectors/postgres.py` before importing sshtunnel: `if not hasattr(paramiko, "DSSKey"): paramiko.DSSKey = paramiko.RSAKey`.
**Rule:** When using sshtunnel, always patch paramiko 4.0+ DSSKey removal before import.

## 2026-04-12 — pgvector extension needs explicit schema on RDS
**Mistake:** `CREATE EXTENSION IF NOT EXISTS vector` failed with "no schema has been selected to create in" because the RDS database had no `public` schema.
**Correction:** Changed to `CREATE SCHEMA IF NOT EXISTS public; CREATE EXTENSION IF NOT EXISTS vector SCHEMA public;`
**Rule:** Always create the public schema before installing extensions on RDS if the database might not have one.

## 2026-04-12 — Use psycopg2 for migrations, not asyncpg
**Mistake:** asyncpg `execute()` has trouble with multi-statement SQL scripts containing DDL across schemas.
**Correction:** Use psycopg2 (synchronous) with `autocommit=True` for running migration SQL files. Keep asyncpg for application queries.
**Rule:** Migrations use `run_migrations_sync()` via psycopg2. Application queries use asyncpg pool.

## 2026-04-12 — MSAL does OIDC discovery even with validate_authority=False
**Mistake:** Created MSAL ConfidentialClientApplication in GraphAPIConnector.__init__ with a fake test tenant ID. MSAL makes a real HTTP call to login.microsoftonline.com during init, which fails in tests.
**Correction:** Made MSAL app creation lazy via _get_msal_app() — only created on first token acquisition. Tests mock _msal_app directly before any call.
**Rule:** Never create MSAL apps eagerly in __init__. Use lazy initialization so tests can inject mocks before the real OIDC discovery happens.

## 2026-04-12 — "filename" is a reserved Python LogRecord attribute
**Mistake:** Used `extra={"filename": filename}` in logger calls. Python's logging module uses "filename" internally for the source file name, causing `KeyError: "Attempt to overwrite 'filename' in LogRecord"`.
**Correction:** Renamed to `extra={"file_name": filename}` to avoid collision with LogRecord reserved attributes.
**Rule:** Never use these keys in logging `extra` dicts: message, asctime, filename, funcName, levelname, levelno, lineno, module, name, pathname, process, processName, thread, threadName.

## 2026-04-12 — Existing tables may have different schemas
**Mistake:** Ran `CREATE TABLE IF NOT EXISTS` against a database with pre-existing tables from a previous attempt that had different column definitions. This caused confusing errors.
**Correction:** Added `000_reset_schemas.sql` that drops all VQMS schemas before recreating them.
**Rule:** Always include a reset migration (000) during development. For production, use proper migration versioning (alembic).

## 2026-04-28 — Cache layer needs dedicated columns, not just JSONB
**Mistake:** Original `cache.vendor_cache` schema stored everything in a single `cache_data` JSONB blob. When routing started needing `vendor_category` for secondary rules, every read had to parse the blob, and ad-hoc DB inspection / reporting could not filter by tier or category without a JSONB extract.
**Correction:** Migration 020 promotes `vendor_name`, `vendor_tier`, `vendor_category` to top-level columns (with indexes on tier and category). Both write paths (`auth._warm_vendor_cache` on login and `ContextLoadingNode._write_vendor_cache` on pipeline cache miss) populate the columns and the JSONB blob in one UPSERT. `_build_vendor_profile` reads top-level columns first and falls back to the blob, so old rows still work.
**Rule:** When a JSONB field becomes load-bearing for routing, auth, or reporting, denormalize it into a column. Keep the JSONB as the full record; treat the columns as a projection. Always populate both in the same write so they cannot drift.

## 2026-04-28 — Trust LLM routing output only when it lands in the canonical taxonomy
**Mistake:** Initial routing tried to use the LLM's `suggested_category` directly as `assigned_team`. A hallucinated name (e.g., the old "finance-ops" team that no longer exists) would silently send tickets to a non-routable group.
**Correction:** Defined `VALID_ASSIGNMENT_GROUPS` as the source of truth (13 sub-team names across 6 families). `RoutingNode` trusts `suggested_category` only when it's in this set; otherwise the deterministic `resolve_assignment_group(intent, vendor_category)` resolver runs and always returns a valid name (default `Vendor Support`).
**Rule:** Never let LLM free-text drive a downstream system call without validating against an enumerated allowlist. Provide a deterministic fallback that always returns a sane default.

## 2026-04-28 — Verify schema + routing changes against real RDS, not just unit tests
**Mistake:** It's tempting to ship a schema change with green pytest and call it done. Unit tests use mocks; they don't catch a typo in the SOQL select, an UPSERT clause that targets a missing column, or a Salesforce field that returns `None` for some real vendors.
**Correction:** Wrote `scripts/verify_vendor_category_flow.py` that runs migration 020, queries `information_schema` for the new columns, hits real Salesforce for two vendors, writes via the actual `_write_vendor_cache` path, reads back from `cache.vendor_cache`, renders the prompt, and exercises the resolver. Confirmed `Category__c='IT Services'` for V-002 and `'Raw Materials'` for V-001 land correctly in the DB columns.
**Rule:** For changes that span schema + adapter + node + DB write, ship a verify script that exercises every layer against real services. Run it before declaring the change done. Ten seconds of real Salesforce + RDS calls catches bugs that 500 mocked unit tests miss.
