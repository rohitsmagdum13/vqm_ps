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
