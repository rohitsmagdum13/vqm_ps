"""Module: cache/pg_cache.py

PostgreSQL-based cache helpers for VQMS.

Provides generic key-value cache operations against the
cache.kv_store table. Used by the auth service for JWT
token blacklisting (logout invalidation).

All functions accept a PostgresConnector instance — they do
NOT create their own connections. The connector is passed in
from the caller (service or route handler).

Table: cache.kv_store (created in migration 009)
Columns: key (VARCHAR 512 UNIQUE), value (TEXT), cached_at, expires_at
"""

from __future__ import annotations

from datetime import timedelta

import structlog

from db.connection import PostgresConnector
from utils.helpers import TimeHelper

logger = structlog.get_logger(__name__)

# Token blacklist TTL matches JWT lifetime so blacklisted
# tokens are cleaned up after they would have expired anyway
AUTH_BLACKLIST_TTL_SECONDS = 1800


def auth_blacklist_key(token_jti: str) -> tuple[str, int]:
    """Build cache key and TTL for token blacklist.

    Key pattern: vqms:auth:blacklist:<jti>
    TTL: 1800 seconds (matches JWT lifetime).
    """
    return f"vqms:auth:blacklist:{token_jti}", AUTH_BLACKLIST_TTL_SECONDS


async def set_with_ttl(
    pg: PostgresConnector,
    key: str,
    value: str,
    ttl_seconds: int,
) -> None:
    """Insert or update a key-value pair with TTL expiry.

    Uses INSERT ON CONFLICT DO UPDATE so the same key can be
    re-blacklisted (e.g., after token refresh).
    """
    now = TimeHelper.ist_now()
    expires_at = now + timedelta(seconds=ttl_seconds)

    await pg.execute(
        "INSERT INTO cache.kv_store (key, value, cached_at, expires_at) "
        "VALUES ($1, $2, $3, $4) "
        "ON CONFLICT (key) DO UPDATE SET value = $2, expires_at = $4",
        key,
        value,
        now,
        expires_at,
    )


async def exists_key(pg: PostgresConnector, key: str) -> bool:
    """Check if a key exists in cache without fetching value.

    Returns False if the key doesn't exist or has expired.
    """
    now = TimeHelper.ist_now()
    row = await pg.fetchrow(
        "SELECT 1 FROM cache.kv_store "
        "WHERE key = $1 AND (expires_at IS NULL OR expires_at > $2) "
        "LIMIT 1",
        key,
        now,
    )
    return row is not None


async def cleanup_expired(pg: PostgresConnector) -> int:
    """Delete expired entries from cache.kv_store.

    Returns the number of rows deleted. Called by background
    cleanup task every 15 minutes.
    """
    result = await pg.execute(
        "DELETE FROM cache.kv_store WHERE expires_at IS NOT NULL AND expires_at < $1",
        TimeHelper.ist_now(),
    )
    # asyncpg returns "DELETE N" where N is the count
    count = int(result.split()[-1]) if result else 0
    if count > 0:
        logger.info("Cache cleanup: deleted expired kv_store entries", count=count)
    return count
