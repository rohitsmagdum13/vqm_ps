"""Diagnose PostgreSQL connection issues.

Tries every plausible connection path and reports which one works:

  1. Show the resolved settings — including whether DATABASE_URL still
     contains literal ${VAR} placeholders (pydantic-settings does NOT
     interpolate env-var references inside other env-var values).
  2. TCP-probe the RDS endpoint directly — confirms it is unreachable
     from outside the VPC, which is why a manually built DSN fails.
  3. Try a manual DSN connection (no tunnel) — this is what the user's
     snippet does. Expected to fail with timeout or connection refused
     when run from outside the VPC.
  4. Try DATABASE_URL connection — fails if the env var contains
     unresolved placeholders.
  5. Try SSH-tunnel + manual DSN — should work.
  6. Try the production PostgresConnector path (SSH tunnel + host/port
     params, NOT a DSN) — this is what the rest of the app uses.

Usage:
    uv run python scripts/check_db_connection.py
"""

from __future__ import annotations

import asyncio
import socket
import sys
from pathlib import Path

sys.path.insert(0, ".")
sys.path.insert(0, "src")

import asyncpg  # noqa: E402
import paramiko  # noqa: E402

# Patch paramiko 4.0+ DSSKey removal before sshtunnel import
if not hasattr(paramiko, "DSSKey"):
    paramiko.DSSKey = paramiko.RSAKey  # type: ignore[attr-defined]
from sshtunnel import SSHTunnelForwarder  # noqa: E402

from config.settings import get_settings  # noqa: E402
from db.connection import PostgresConnector  # noqa: E402
from utils.logger import LoggingSetup  # noqa: E402


def _redact(secret: str) -> str:
    if not secret:
        return "(empty)"
    if len(secret) <= 4:
        return "*" * len(secret)
    return secret[:2] + "*" * (len(secret) - 4) + secret[-2:]


def _ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def _info(msg: str) -> None:
    print(f"  [INFO] {msg}")


def _step_1_show_settings(s) -> None:
    print("\n[1] Resolved settings")
    _info(f"postgres_host         = {s.postgres_host}")
    _info(f"postgres_port         = {s.postgres_port}")
    _info(f"postgres_db           = {s.postgres_db}")
    _info(f"postgres_user         = {s.postgres_user}")
    _info(f"postgres_password     = {_redact(s.postgres_password)}")
    _info(f"postgres_pool_min/max = {s.postgres_pool_min} / {s.postgres_pool_max}")
    _info(f"database_url          = {s.database_url}")
    if s.database_url and "${" in s.database_url:
        _fail(
            "DATABASE_URL contains literal '${...}' — pydantic-settings does "
            "NOT expand $VAR references inside env values. Either inline the "
            "values or build the DSN in code from the individual fields."
        )
    _info(f"ssh_host              = {s.ssh_host}")
    _info(f"ssh_port              = {s.ssh_port}")
    _info(f"ssh_username          = {s.ssh_username}")
    _info(f"ssh_private_key_path  = {s.ssh_private_key_path}")
    _info(f"rds_host              = {s.rds_host}")
    _info(f"rds_port              = {s.rds_port}")


def _step_2_tcp_probe(s) -> None:
    print("\n[2] TCP probe — is RDS reachable from this machine?")
    host = s.postgres_host
    port = s.postgres_port
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5.0)
    try:
        sock.connect((host, port))
        _ok(f"TCP connect to {host}:{port} succeeded — RDS is publicly reachable")
    except (TimeoutError, OSError) as exc:
        _fail(f"TCP connect to {host}:{port} failed: {exc}")
        _info("This is expected if RDS is in a private subnet — you MUST tunnel through the bastion.")
    finally:
        sock.close()


async def _step_3_manual_dsn_no_tunnel(s) -> None:
    print("\n[3] Manual DSN, no tunnel — replicates the user's snippet")
    dsn = (
        f"postgresql://{s.postgres_user}:"
        f"{s.postgres_password}@"
        f"{s.postgres_host}:"
        f"{s.postgres_port}/"
        f"{s.postgres_db}"
    )
    _info(f"DSN = postgresql://{s.postgres_user}:***@{s.postgres_host}:{s.postgres_port}/{s.postgres_db}")
    try:
        pool = await asyncio.wait_for(
            asyncpg.create_pool(dsn=dsn, min_size=1, max_size=2, command_timeout=10),
            timeout=15.0,
        )
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT current_database() AS db, current_user AS usr, version() AS v")
            _ok(f"Connected directly! db={row['db']!r}, user={row['usr']!r}")
            _info(f"Server: {row['v']}")
        await pool.close()
    except (TimeoutError, OSError) as exc:
        _fail(f"Direct DSN failed: {type(exc).__name__}: {exc}")
        _info("This is expected when RDS is private — tunnel is required.")
    except asyncpg.PostgresError as exc:
        _fail(f"asyncpg error: {type(exc).__name__}: {exc}")
    except Exception as exc:
        _fail(f"Unexpected error: {type(exc).__name__}: {exc}")


async def _step_4_database_url(s) -> None:
    print("\n[4] DATABASE_URL connection")
    if not s.database_url:
        _info("DATABASE_URL not set — skipping")
        return
    dsn = s.database_url.replace("postgresql+asyncpg://", "postgresql://")
    if "${" in dsn:
        _fail("DSN still contains literal '${...}' — would never connect. Skipping attempt.")
        return
    _info(f"DSN (sanitized): {dsn.replace(s.postgres_password, '***') if s.postgres_password else dsn}")
    try:
        pool = await asyncio.wait_for(
            asyncpg.create_pool(dsn=dsn, min_size=1, max_size=2, command_timeout=10),
            timeout=15.0,
        )
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT current_database() AS db")
            _ok(f"Connected via DATABASE_URL — db={row['db']!r}")
        await pool.close()
    except Exception as exc:
        _fail(f"DATABASE_URL connect failed: {type(exc).__name__}: {exc}")


async def _step_5_tunnel_plus_dsn(s) -> None:
    print("\n[5] SSH tunnel + manual DSN")
    if not s.ssh_host or not s.ssh_private_key_path:
        _info("SSH not configured — skipping")
        return
    key_path = str(Path(s.ssh_private_key_path))
    tunnel = SSHTunnelForwarder(
        (s.ssh_host, s.ssh_port),
        ssh_username=s.ssh_username,
        ssh_pkey=key_path,
        remote_bind_address=(s.rds_host or s.postgres_host, s.rds_port),
        local_bind_address=("127.0.0.1",),
    )
    try:
        tunnel.start()
        local_port = tunnel.local_bind_port
        _ok(f"SSH tunnel established on 127.0.0.1:{local_port}")

        dsn = (
            f"postgresql://{s.postgres_user}:"
            f"{s.postgres_password}@"
            f"127.0.0.1:{local_port}/"
            f"{s.postgres_db}"
        )
        _info(f"DSN = postgresql://{s.postgres_user}:***@127.0.0.1:{local_port}/{s.postgres_db}")
        try:
            pool = await asyncio.wait_for(
                asyncpg.create_pool(dsn=dsn, min_size=1, max_size=2, command_timeout=10),
                timeout=15.0,
            )
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT current_database() AS db, current_user AS usr"
                )
                _ok(f"Connected through tunnel! db={row['db']!r}, user={row['usr']!r}")
            await pool.close()
        except Exception as exc:
            _fail(f"Tunnel+DSN connect failed: {type(exc).__name__}: {exc}")
    except Exception as exc:
        _fail(f"SSH tunnel failed: {type(exc).__name__}: {exc}")
    finally:
        try:
            tunnel.stop()
        except Exception:
            pass


async def _step_6_postgres_connector(s) -> None:
    print("\n[6] Production path — PostgresConnector(settings).connect()")
    pg = PostgresConnector(s)
    try:
        await pg.connect()
        row = await pg.fetchrow("SELECT current_database() AS db, version() AS v")
        _ok(f"Connected via PostgresConnector — db={row['db']!r}")
        _info(f"Server: {row['v'][:80]}...")
    except Exception as exc:
        _fail(f"PostgresConnector failed: {type(exc).__name__}: {exc}")
    finally:
        try:
            await pg.disconnect()
        except Exception:
            pass


async def main() -> None:
    LoggingSetup.configure()
    settings = get_settings()
    print("=" * 70)
    print("  Postgres connection diagnostic")
    print("=" * 70)

    _step_1_show_settings(settings)
    _step_2_tcp_probe(settings)
    await _step_3_manual_dsn_no_tunnel(settings)
    await _step_4_database_url(settings)
    await _step_5_tunnel_plus_dsn(settings)
    await _step_6_postgres_connector(settings)

    print("\n" + "=" * 70)
    print("  Done.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
