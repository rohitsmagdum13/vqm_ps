"""Module: connectors/postgres.py

PostgreSQL connector with two connection modes for VQMS.

Mode 1 — LOCAL DEV (SSH tunnel + PEM file):
    When ssh_host is set in .env, the connector establishes an SSH
    tunnel through a bastion host to reach RDS.
    Flow: local machine -> SSH tunnel to bastion -> bastion forwards to RDS

Mode 2 — DEPLOYMENT (DATABASE_URL):
    When ssh_host is empty and database_url is set in .env, the connector
    connects directly using the URL. This is for deployment environments
    (ECS/EC2) that sit in the same VPC as RDS.

The connector auto-detects which mode to use based on the settings:
    - ssh_host is set          -> Mode 1 (SSH tunnel)
    - ssh_host is empty + database_url is set -> Mode 2 (direct URL)
    - both empty               -> Mode 1 fallback (direct to localhost)

Usage:
    from connectors.postgres import PostgresConnector
    from config import get_settings

    connector = PostgresConnector(get_settings())
    await connector.connect()
    rows = await connector.fetch("SELECT 1 AS test")
    await connector.disconnect()
"""

from __future__ import annotations

from pathlib import Path

import asyncpg
import paramiko
import structlog

# Patch for paramiko 4.0+ which removed DSSKey
# sshtunnel 0.4.0 still references it, causing AttributeError
if not hasattr(paramiko, "DSSKey"):
    paramiko.DSSKey = paramiko.RSAKey  # type: ignore[attr-defined]

from sshtunnel import SSHTunnelForwarder  # noqa: E402

from config.settings import Settings
from utils.helpers import TimeHelper

logger = structlog.get_logger(__name__)


class PostgresConnector:
    """PostgreSQL connector with SSH tunnel and async connection pool.

    Handles:
    - SSH tunnel establishment to bastion host
    - asyncpg connection pool management
    - CRUD helpers for all schemas
    - Idempotency check (INSERT ON CONFLICT DO NOTHING)
    - Cache read/write with expires_at TTL checking
    - Migration runner for SQL files
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize with application settings.

        Does NOT connect to the database. Call connect() to
        establish the SSH tunnel and connection pool.
        """
        self._settings = settings
        self._tunnel: SSHTunnelForwarder | None = None
        self._pool: asyncpg.Pool | None = None

    @property
    def _use_direct_url(self) -> bool:
        """True when we should connect via DATABASE_URL instead of SSH tunnel.

        Direct URL is used when:
        1. ssh_host is NOT set (no tunnel needed), AND
        2. database_url IS set (we have a connection string)
        """
        has_ssh = bool(self._settings.ssh_host and self._settings.ssh_private_key_path)
        has_url = bool(self._settings.database_url)
        return (not has_ssh) and has_url

    async def connect(self) -> None:
        """Establish connection to PostgreSQL.

        Auto-detects the connection mode:
        - If ssh_host is set: starts SSH tunnel, then creates pool via tunnel
        - If database_url is set (no ssh_host): connects directly via URL
        - Neither: falls back to direct connection using host/port fields
        """
        if self._use_direct_url:
            await self._create_pool_from_url()
            logger.info(
                "PostgreSQL connector connected via DATABASE_URL (direct)",
                tool="postgresql",
            )
        else:
            self._start_tunnel()
            await self._create_pool()
            connection_mode = "SSH tunnel" if self._tunnel else "direct (no tunnel)"
            logger.info(
                "PostgreSQL connector connected",
                tool="postgresql",
                mode=connection_mode,
            )

    async def disconnect(self) -> None:
        """Close the connection pool and SSH tunnel.

        Always close the pool first, then the tunnel.
        """
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("Connection pool closed", tool="postgresql")

        if self._tunnel is not None:
            self._tunnel.stop()
            self._tunnel = None
            logger.info("SSH tunnel closed", tool="postgresql")

    async def execute(self, query: str, *args) -> str:
        """Execute a SQL statement and return the status string.

        Args:
            query: SQL query with $1, $2, ... placeholders.
            *args: Values for the placeholders.

        Returns:
            Command status string (e.g., "INSERT 0 1", "CREATE TABLE").
        """
        pool = self._get_pool()
        async with pool.acquire() as conn:
            return await conn.execute(query, *args)

    async def fetch(self, query: str, *args) -> list[dict]:
        """Execute a query and return all rows as dicts.

        Args:
            query: SQL query with $1, $2, ... placeholders.
            *args: Values for the placeholders.

        Returns:
            List of row dicts.
        """
        pool = self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows]

    async def fetchrow(self, query: str, *args) -> dict | None:
        """Execute a query and return the first row as a dict.

        Args:
            query: SQL query with $1, $2, ... placeholders.
            *args: Values for the placeholders.

        Returns:
            Row dict, or None if no rows.
        """
        pool = self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
            return dict(row) if row else None

    async def check_idempotency(self, key: str, source: str, correlation_id: str) -> bool:
        """Check if a key already exists; insert if not.

        Uses INSERT ON CONFLICT DO NOTHING for atomic check-and-insert.
        This prevents the same email or query from being processed twice.

        Args:
            key: Unique key (e.g., Exchange message_id or portal query hash).
            source: Origin — "email" or "portal".
            correlation_id: Tracing ID for this request.

        Returns:
            True if the key was NEW (inserted successfully).
            False if the key already EXISTS (duplicate detected).
        """
        pool = self._get_pool()
        async with pool.acquire() as conn:
            # INSERT ON CONFLICT DO NOTHING returns "INSERT 0 0" for conflicts
            # and "INSERT 0 1" for new inserts
            result = await conn.execute(
                """
                INSERT INTO cache.idempotency_keys (key, source, correlation_id)
                VALUES ($1, $2, $3)
                ON CONFLICT (key) DO NOTHING
                """,
                key,
                source,
                correlation_id,
            )
            # "INSERT 0 1" means 1 row was inserted (new key)
            # "INSERT 0 0" means 0 rows were inserted (duplicate)
            is_new = result.endswith("1")
            if not is_new:
                logger.info(
                    "Duplicate key detected",
                    tool="postgresql",
                    key=key,
                    source=source,
                    correlation_id=correlation_id,
                )
            return is_new

    async def cache_read(self, table: str, key_column: str, key_value: str) -> dict | None:
        """Read a cached value, respecting expires_at TTL.

        Returns None if the key doesn't exist or has expired.

        Args:
            table: Full table name (e.g., "cache.vendor_cache").
            key_column: Column name to match (e.g., "vendor_id").
            key_value: Value to look up.

        Returns:
            The cache_data/state_data JSONB as a dict, or None.
        """
        now = TimeHelper.ist_now()
        row = await self.fetchrow(
            f"SELECT * FROM {table} WHERE {key_column} = $1 AND expires_at > $2",  # noqa: S608
            key_value,
            now,
        )
        return row if row else None

    def run_migrations_sync(self, migrations_dir: str) -> None:
        """Execute all SQL migration files in order (synchronous).

        Uses psycopg2 (not asyncpg) because psycopg2 handles
        multi-statement SQL scripts natively. This is only used
        for migrations, not for application queries.

        Supports both connection modes:
        - SSH tunnel / direct host: uses host/port/user/password fields
        - DATABASE_URL: uses the URL directly (for deployment)

        Args:
            migrations_dir: Path to the directory containing .sql files.
        """
        import psycopg2

        migrations_path = Path(migrations_dir)
        sql_files = sorted(migrations_path.glob("*.sql"))

        if not sql_files:
            logger.warning(
                "No migration files found", tool="postgresql", migrations_dir=migrations_dir
            )
            return

        if self._use_direct_url:
            # Deployment mode: connect via DATABASE_URL
            dsn = self._settings.database_url or ""
            # psycopg2 understands plain postgresql:// but not +asyncpg
            dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")
            conn = psycopg2.connect(dsn)
            logger.info("Migrations: connecting via DATABASE_URL", tool="postgresql")
        else:
            # Local dev mode: connect via SSH tunnel or direct host
            if self._tunnel is not None:
                host = "127.0.0.1"
                port = self._tunnel.local_bind_port
            else:
                host = self._settings.postgres_host
                port = self._settings.postgres_port

            conn = psycopg2.connect(
                host=host,
                port=port,
                dbname=self._settings.postgres_db,
                user=self._settings.postgres_user,
                password=self._settings.postgres_password,
            )
            logger.info(
                "Migrations: connecting via host/port",
                tool="postgresql",
                host=host,
                port=port,
            )

        conn.autocommit = True

        try:
            with conn.cursor() as cur:
                for sql_file in sql_files:
                    logger.info(
                        "Running migration", tool="postgresql", migration=sql_file.name
                    )
                    sql = sql_file.read_text(encoding="utf-8")
                    cur.execute(sql)
                    logger.info(
                        "Migration completed", tool="postgresql", migration=sql_file.name
                    )
        finally:
            conn.close()

    async def health_check(self) -> bool:
        """Verify the database connection is alive.

        Returns:
            True if a simple SELECT 1 succeeds, False otherwise.
        """
        try:
            result = await self.fetchrow("SELECT 1 AS ok")
            return result is not None and result.get("ok") == 1
        except Exception:
            logger.exception("Health check failed", tool="postgresql")
            return False

    # --- Private methods ---

    def _start_tunnel(self) -> None:
        """Start the SSH tunnel to the bastion host."""
        settings = self._settings

        if not settings.ssh_host or not settings.ssh_private_key_path:
            # If SSH is not configured, connect directly (for local dev with port-forwarding)
            logger.info(
                "SSH tunnel not configured — connecting directly to PostgreSQL",
                tool="postgresql",
            )
            return

        # Normalize Windows backslash paths
        key_path = str(Path(settings.ssh_private_key_path))

        self._tunnel = SSHTunnelForwarder(
            (settings.ssh_host, settings.ssh_port),
            ssh_username=settings.ssh_username,
            ssh_pkey=key_path,
            remote_bind_address=(settings.rds_host or settings.postgres_host, settings.rds_port),
            local_bind_address=("127.0.0.1",),
        )
        self._tunnel.start()
        logger.info(
            "SSH tunnel established",
            tool="postgresql",
            local_port=self._tunnel.local_bind_port,
            rds_host=settings.rds_host,
            rds_port=settings.rds_port,
        )

    async def _create_pool(self) -> None:
        """Create the asyncpg connection pool using host/port fields.

        Connects to localhost on the tunnel's local port (if tunnel is active)
        or directly to postgres_host (if no tunnel).
        """
        settings = self._settings

        if self._tunnel is not None:
            host = "127.0.0.1"
            port = self._tunnel.local_bind_port
        else:
            host = settings.postgres_host
            port = settings.postgres_port

        self._pool = await asyncpg.create_pool(
            host=host,
            port=port,
            database=settings.postgres_db,
            user=settings.postgres_user,
            password=settings.postgres_password,
            min_size=settings.postgres_pool_min,
            max_size=settings.postgres_pool_max,
        )

    async def _create_pool_from_url(self) -> None:
        """Create the asyncpg connection pool from DATABASE_URL.

        Used in deployment environments where the app sits in the
        same VPC as RDS and can connect directly without SSH tunnel.

        DATABASE_URL format: postgresql+asyncpg://user:pass@host:5432/dbname
        asyncpg needs the plain format: postgresql://user:pass@host:5432/dbname
        """
        settings = self._settings
        dsn = settings.database_url or ""

        # asyncpg does not understand the "+asyncpg" dialect suffix
        # that SQLAlchemy uses, so strip it out
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")

        self._pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=settings.postgres_pool_min,
            max_size=settings.postgres_pool_max,
        )

    def _get_pool(self) -> asyncpg.Pool:
        """Return the connection pool, raising if not connected."""
        if self._pool is None:
            msg = "PostgresConnector is not connected. Call connect() first."
            raise RuntimeError(msg)
        return self._pool
