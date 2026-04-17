"""Module: db/connection/queries.py

Database query operations for the PostgreSQL connector.

Handles all CRUD operations: execute, fetch, fetchrow,
idempotency checks, and cache reads with TTL support.
"""

from __future__ import annotations

import structlog

from utils.helpers import TimeHelper

logger = structlog.get_logger(__name__)


class QueryMixin:
    """Database query methods for the PostgreSQL connector.

    Mixed into PostgresConnector. Expects self._get_pool()
    from PostgresClient.
    """

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
