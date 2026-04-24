"""Module: db/connection/client.py

PostgreSQL client initialization, SSH tunnel, and pool management.

Manages SSH tunnel to bastion host and asyncpg connection pool.
Supports two connection modes:
- LOCAL DEV: SSH tunnel + PEM file to reach RDS via bastion
- DEPLOYMENT: Direct DATABASE_URL for same-VPC connectivity
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
from utils.log_types import LOG_TYPE_INTEGRATION

logger = structlog.get_logger(__name__)


class PostgresClient:
    """Base PostgreSQL client with SSH tunnel and pool management.

    Handles:
    - SSH tunnel establishment to bastion host
    - asyncpg connection pool creation (from host/port or DATABASE_URL)
    - connect/disconnect lifecycle
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
                log_type=LOG_TYPE_INTEGRATION,
                tool="postgresql",
            )
        else:
            self._start_tunnel()
            await self._create_pool()
            connection_mode = "SSH tunnel" if self._tunnel else "direct (no tunnel)"
            logger.info(
                "PostgreSQL connector connected",
                log_type=LOG_TYPE_INTEGRATION,
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
            logger.info(
                "Connection pool closed",
                log_type=LOG_TYPE_INTEGRATION,
                tool="postgresql",
            )

        if self._tunnel is not None:
            self._tunnel.stop()
            self._tunnel = None
            logger.info(
                "SSH tunnel closed",
                log_type=LOG_TYPE_INTEGRATION,
                tool="postgresql",
            )

    def _get_pool(self) -> asyncpg.Pool:
        """Return the connection pool, raising if not connected."""
        if self._pool is None:
            msg = "PostgresConnector is not connected. Call connect() first."
            raise RuntimeError(msg)
        return self._pool

    def _start_tunnel(self) -> None:
        """Start the SSH tunnel to the bastion host."""
        settings = self._settings

        if not settings.ssh_host or not settings.ssh_private_key_path:
            # If SSH is not configured, connect directly (for local dev with port-forwarding)
            logger.info(
                "SSH tunnel not configured — connecting directly to PostgreSQL",
                log_type=LOG_TYPE_INTEGRATION,
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
            log_type=LOG_TYPE_INTEGRATION,
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
