"""Script: check_db.py

Verify PostgreSQL connectivity via SSH tunnel to RDS.

Tests:
  1. SSH tunnel establishment to bastion host
  2. asyncpg connection pool creation
  3. Simple SELECT 1 health check
  4. Schema listing (shows what's been migrated)
  5. Table listing per schema

Usage:
    uv run python scripts/check_db.py
"""

from __future__ import annotations

import asyncio
import sys
import time

# Add src/ to Python path so imports work when run directly
sys.path.insert(0, ".")
sys.path.insert(0, "src")

from config.settings import get_settings  # noqa: E402
from db.connection import PostgresConnector  # noqa: E402
from utils.logger import LoggingSetup  # noqa: E402


def print_header(text: str) -> None:
    """Print a section header."""
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}\n")


def print_check(name: str, passed: bool, detail: str = "") -> None:
    """Print a check result."""
    status = "[PASS]" if passed else "[FAIL]"
    suffix = f" — {detail}" if detail else ""
    print(f"  {status} {name}{suffix}")


async def check_db() -> None:
    """Run all PostgreSQL connectivity checks."""
    LoggingSetup.configure()
    settings = get_settings()

    print_header("VQMS — PostgreSQL Database Check")

    # Show connection target
    if settings.ssh_host and settings.ssh_private_key_path:
        print("  Mode:     SSH tunnel via bastion")
        print(f"  Bastion:  {settings.ssh_host}:{settings.ssh_port}")
        print(f"  RDS:      {settings.rds_host}:{settings.rds_port}")
    else:
        print("  Mode:     Direct connection")
        print(f"  Host:     {settings.postgres_host}:{settings.postgres_port}")
    print(f"  Database: {settings.postgres_db}")
    print(f"  User:     {settings.postgres_user}")
    print()

    pg = PostgresConnector(settings)

    # --- Check 1: Connect (SSH tunnel + pool) ---
    try:
        start = time.perf_counter()
        await pg.connect()
        elapsed = (time.perf_counter() - start) * 1000
        print_check("Connect (SSH tunnel + pool)", True, f"{elapsed:.0f}ms")
    except Exception as e:
        print_check("Connect (SSH tunnel + pool)", False, str(e))
        return

    try:
        # --- Check 2: Health check (SELECT 1) ---
        try:
            start = time.perf_counter()
            healthy = await pg.health_check()
            elapsed = (time.perf_counter() - start) * 1000
            print_check("Health check (SELECT 1)", healthy, f"{elapsed:.0f}ms")
        except Exception as e:
            print_check("Health check (SELECT 1)", False, str(e))

        # --- Check 3: PostgreSQL version ---
        try:
            row = await pg.fetchrow("SELECT version() AS ver")
            version = row["ver"] if row else "unknown"
            # Truncate to first line for readability
            version_short = version.split(",")[0] if version else "unknown"
            print_check("PostgreSQL version", True, version_short)
        except Exception as e:
            print_check("PostgreSQL version", False, str(e))

        # --- Check 4: pgvector extension ---
        try:
            row = await pg.fetchrow(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
            )
            if row:
                print_check("pgvector extension", True, f"v{row['extversion']}")
            else:
                print_check("pgvector extension", False, "Not installed")
        except Exception as e:
            print_check("pgvector extension", False, str(e))

        # --- Check 5: List schemas ---
        try:
            schemas = await pg.fetch(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast', 'public') "
                "ORDER BY schema_name"
            )
            schema_names = [r["schema_name"] for r in schemas]
            if schema_names:
                print_check("Custom schemas", True, ", ".join(schema_names))
            else:
                print_check("Custom schemas", False, "None found — run migrations first")
        except Exception as e:
            print_check("Custom schemas", False, str(e))

        # --- Check 6: List tables per schema ---
        try:
            tables = await pg.fetch(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_schema NOT IN ('pg_catalog', 'information_schema', 'public') "
                "ORDER BY table_schema, table_name"
            )
            if tables:
                print(f"\n  Tables ({len(tables)} total):")
                current_schema = ""
                for t in tables:
                    schema = t["table_schema"]
                    if schema != current_schema:
                        current_schema = schema
                        print(f"    [{schema}]")
                    print(f"      {t['table_name']}")
            else:
                print("\n  No tables found — run migrations first.")
        except Exception as e:
            print_check("Table listing", False, str(e))

    finally:
        await pg.disconnect()

    print(f"\n{'=' * 60}\n")


def main() -> None:
    """Run the check."""
    asyncio.run(check_db())


if __name__ == "__main__":
    main()
