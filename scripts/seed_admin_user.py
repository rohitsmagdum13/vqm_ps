"""One-time script to seed an admin user and a vendor user into
tbl_users and tbl_user_roles.

Connects to RDS via SSH tunnel, hashes each password with werkzeug,
and inserts each user and role if they don't already exist.

Usage: uv run python scripts/seed_admin_user.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

# Add src/ to Python path so imports work when run directly
sys.path.insert(0, ".")
sys.path.insert(0, "src")

import paramiko  # noqa: E402

# Patch for paramiko 4.0+ which removed DSSKey
# sshtunnel 0.4.0 still references it, causing AttributeError
if not hasattr(paramiko, "DSSKey"):
    paramiko.DSSKey = paramiko.RSAKey  # type: ignore[attr-defined]

import psycopg2  # noqa: E402
from sshtunnel import SSHTunnelForwarder  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

from config.settings import get_settings  # noqa: E402


@dataclass(frozen=True)
class SeedUser:
    """User credentials and role details for a single seeded account."""

    user_name: str
    password: str
    email: str
    tenant: str
    status: str
    role: str
    first_name: str
    last_name: str
    created_by: str = "system"


USERS_TO_SEED: tuple[SeedUser, ...] = (
    SeedUser(
        user_name="admin_user",
        password="admin123",
        email="admin@vqms.local",
        tenant="hexaware",
        status="ACTIVE",
        role="ADMIN",
        first_name="Admin",
        last_name="User",
    ),
    SeedUser(
        user_name="vendor_user",
        password="vendor123",
        email="vendor@vqms.local",
        tenant="hexaware",
        status="ACTIVE",
        role="VENDOR",
        first_name="Vendor",
        last_name="User",
    ),
    # Dummy vendor logins sourced from vendor_contacts.csv (V-001, V-002, V-003)
    SeedUser(
        user_name="sneha.singh",
        password="vendor_user123",
        email="sneha.singh@acmeindustrial.com",
        tenant="hexaware",
        status="ACTIVE",
        role="VENDOR",
        first_name="Sneha",
        last_name="Singh",
    ),
    SeedUser(
        user_name="dinesh.chauhan",
        password="vendor_user123",
        email="dinesh.chauhan@technova.io",
        tenant="hexaware",
        status="ACTIVE",
        role="VENDOR",
        first_name="Dinesh",
        last_name="Chauhan",
    ),
    SeedUser(
        user_name="deepak.reddy",
        password="vendor_user123",
        email="deepak.reddy@swiftlogfreight.com",
        tenant="hexaware",
        status="ACTIVE",
        role="VENDOR",
        first_name="Deepak",
        last_name="Reddy",
    ),
)


def seed_user(cur, user: SeedUser) -> tuple[bool, bool]:
    """Insert a user and their role if they don't already exist.

    Returns a tuple (user_inserted, role_inserted).
    """
    hashed_password = generate_password_hash(user.password)
    print(f"[{user.user_name}] Password hashed ({len(hashed_password)} chars)")

    user_inserted = False
    role_inserted = False

    # Check if user exists
    cur.execute(
        "SELECT id FROM public.tbl_users WHERE user_name = %s",
        (user.user_name,),
    )
    if cur.fetchone():
        print(f"[{user.user_name}] already exists in tbl_users — skipping insert")
    else:
        cur.execute(
            "INSERT INTO public.tbl_users (user_name, email_id, tenant, password, status) "
            "VALUES (%s, %s, %s, %s, %s)",
            (user.user_name, user.email, user.tenant, hashed_password, user.status),
        )
        user_inserted = True
        print(f"[{user.user_name}] inserted into tbl_users")

    # Check if role exists
    cur.execute(
        "SELECT slno FROM public.tbl_user_roles WHERE user_name = %s",
        (user.user_name,),
    )
    if cur.fetchone():
        print(f"[{user.user_name}] role already exists — skipping tbl_user_roles insert")
    else:
        cur.execute(
            "INSERT INTO public.tbl_user_roles "
            "(first_name, last_name, email_id, user_name, tenant, role, created_by, created_date) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())",
            (
                user.first_name,
                user.last_name,
                user.email,
                user.user_name,
                user.tenant,
                user.role,
                user.created_by,
            ),
        )
        role_inserted = True
        print(f"[{user.user_name}] inserted role '{user.role}' into tbl_user_roles")

    return user_inserted, role_inserted


def main() -> None:
    """Seed configured users into RDS via SSH tunnel."""
    settings = get_settings()

    # Establish SSH tunnel to bastion
    key_path = str(Path(settings.ssh_private_key_path))
    print(f"Opening SSH tunnel to {settings.ssh_host}:{settings.ssh_port} ...")

    tunnel = SSHTunnelForwarder(
        (settings.ssh_host, settings.ssh_port),
        ssh_username=settings.ssh_username,
        ssh_pkey=key_path,
        remote_bind_address=(settings.rds_host or settings.postgres_host, settings.rds_port),
        local_bind_address=("127.0.0.1",),
    )
    tunnel.start()
    print(f"SSH tunnel open — local port {tunnel.local_bind_port}")

    # Connect to PostgreSQL through the tunnel using psycopg2
    conn = psycopg2.connect(
        host="127.0.0.1",
        port=tunnel.local_bind_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
    )
    cur = conn.cursor()
    print(f"Connected to PostgreSQL database '{settings.postgres_db}'\n")

    results: list[tuple[SeedUser, bool, bool]] = []

    try:
        for user in USERS_TO_SEED:
            user_inserted, role_inserted = seed_user(cur, user)
            results.append((user, user_inserted, role_inserted))
            print()

        conn.commit()
        print("Transaction committed.\n")

        # Summary
        print("--- Summary ---")
        for user, user_inserted, role_inserted in results:
            u = "INSERTED" if user_inserted else "SKIPPED (already exists)"
            r = "INSERTED" if role_inserted else "SKIPPED (already exists)"
            print(f"  {user.user_name:15s}  tbl_users: {u:28s}  tbl_user_roles: {r}")

    except Exception as exc:
        conn.rollback()
        print(f"\nError: {exc}")
        print("Transaction rolled back.")
        raise

    finally:
        cur.close()
        conn.close()
        tunnel.stop()
        print("\nConnection closed. SSH tunnel stopped.")


if __name__ == "__main__":
    main()
