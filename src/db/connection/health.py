"""Module: db/connection/health.py

Health check and migration runner for the PostgreSQL connector.

Provides database health verification and synchronous SQL
migration execution using psycopg2.
"""

from __future__ import annotations

from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


class HealthMixin:
    """Health check and migration methods for the PostgreSQL connector.

    Mixed into PostgresConnector. Expects self.fetchrow(),
    self._settings, self._tunnel, and self._use_direct_url
    from PostgresClient/QueryMixin.
    """

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
