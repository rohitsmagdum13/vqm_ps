"""Package: db/connection

PostgreSQL connector for VQMS — split into focused modules.

The PostgresConnector class combines:
- PostgresClient: SSH tunnel, pool management, connect/disconnect
- QueryMixin: execute, fetch, fetchrow, idempotency, cache read
- HealthMixin: health check and migration runner

Re-exports so existing imports like
``from db.connection import PostgresConnector`` keep working.
"""

from db.connection.client import PostgresClient
from db.connection.health import HealthMixin
from db.connection.queries import QueryMixin
from config.settings import Settings


class PostgresConnector(PostgresClient, QueryMixin, HealthMixin):
    """Full PostgreSQL connector combining all operations.

    Inherits from:
    - PostgresClient: SSH tunnel, pool management, connect/disconnect
    - QueryMixin: execute, fetch, fetchrow, check_idempotency, cache_read
    - HealthMixin: health_check, run_migrations_sync
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize with application settings."""
        super().__init__(settings)


__all__ = ["PostgresConnector"]
