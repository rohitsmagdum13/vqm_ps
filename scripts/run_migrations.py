"""Script: run_migrations.py

Run all SQL migrations against the VQMS PostgreSQL database.

Connects via SSH tunnel (or direct), then executes each migration
file in src/db/migrations/ in order. Uses IF NOT EXISTS / IF EXISTS
guards so migrations are safe to re-run.

Uses PostgresConnector which handles SSH tunnel setup, psycopg2
multi-statement execution, and structured logging.

Usage:
    uv run python scripts/run_migrations.py
    uv run python scripts/run_migrations.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Add src/ to Python path so imports work when run directly
sys.path.insert(0, ".")
sys.path.insert(0, "src")

from config.settings import get_settings  # noqa: E402
from db.connection import PostgresConnector  # noqa: E402
from utils.logger import LoggingSetup  # noqa: E402

# Migration files live here
MIGRATIONS_DIR = Path("src/db/migrations")


async def run_migrations(dry_run: bool = False) -> None:
    """Connect to PostgreSQL and run all migration SQL files."""
    LoggingSetup.configure()
    settings = get_settings()

    # --- List available migrations ---
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_files:
        print(f"No .sql files found in {MIGRATIONS_DIR}")
        return

    print(f"\nFound {len(migration_files)} migration file(s):")
    for f in migration_files:
        print(f"  - {f.name}")

    if dry_run:
        print("\n[DRY RUN] Would execute the above migrations. Exiting.")
        return

    # --- Connect via PostgresConnector (handles SSH tunnel) ---
    pg = PostgresConnector(settings)
    await pg.connect()

    try:
        print(f"\nConnected to '{settings.postgres_db}'\n")

        # Run migrations using psycopg2 (handles multi-statement SQL)
        pg.run_migrations_sync(str(MIGRATIONS_DIR))

        # --- Verify: list schemas ---
        schemas = await pg.fetch(
            "SELECT schema_name FROM information_schema.schemata "
            "WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast', 'public') "
            "ORDER BY schema_name"
        )
        print(f"\nSchemas: {[r['schema_name'] for r in schemas]}")

        # --- Verify: list tables ---
        tables = await pg.fetch(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema NOT IN ('pg_catalog', 'information_schema', 'public') "
            "ORDER BY table_schema, table_name"
        )
        if tables:
            print("\nTables:")
            current_schema = ""
            for t in tables:
                schema = t["table_schema"]
                if schema != current_schema:
                    current_schema = schema
                    print(f"\n  [{schema}]")
                print(f"    {t['table_name']}")
        else:
            print("No tables found.")

        print("\nMigrations complete.")

    except Exception:
        print("\n[ERROR] Migration failed — see logs above.")
        raise
    finally:
        await pg.disconnect()


def main() -> None:
    """Parse args and run."""
    parser = argparse.ArgumentParser(description="Run VQMS database migrations")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List migration files without executing them",
    )
    args = parser.parse_args()

    asyncio.run(run_migrations(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
