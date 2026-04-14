"""One-time script to seed an admin user into tbl_users and tbl_user_roles.

Connects to RDS via SSH tunnel, hashes the password with werkzeug,
inserts the user and role if they don't already exist.

Usage: uv run python scripts/seed_admin_user.py
"""

from __future__ import annotations

import sys
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

# --- Admin user details ---
USER_NAME = "admin_user"
PASSWORD = "admin123"
EMAIL = "admin@vqms.local"
TENANT = "hexaware"
STATUS = "ACTIVE"
ROLE = "ADMIN"
FIRST_NAME = "Admin"
LAST_NAME = "User"
CREATED_BY = "system"


def main() -> None:
    """Seed the admin user into RDS via SSH tunnel."""
    settings = get_settings()

    # 1. Hash the password
    hashed_password = generate_password_hash(PASSWORD)
    print(f"Password hashed ({len(hashed_password)} chars)")

    # 2. Establish SSH tunnel to bastion
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

    # 3. Connect to PostgreSQL through the tunnel using psycopg2
    conn = psycopg2.connect(
        host="127.0.0.1",
        port=tunnel.local_bind_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
    )
    cur = conn.cursor()
    print(f"Connected to PostgreSQL database '{settings.postgres_db}'\n")

    user_inserted = False
    role_inserted = False

    try:
        # 4. Check if user exists
        cur.execute(
            "SELECT id FROM public.tbl_users WHERE user_name = %s",
            (USER_NAME,),
        )
        if cur.fetchone():
            print(f"User '{USER_NAME}' already exists — skipping tbl_users insert")
        else:
            cur.execute(
                "INSERT INTO public.tbl_users (user_name, email_id, tenant, password, status) "
                "VALUES (%s, %s, %s, %s, %s)",
                (USER_NAME, EMAIL, TENANT, hashed_password, STATUS),
            )
            user_inserted = True
            print(f"Inserted user '{USER_NAME}' into public.tbl_users")

        # 5. Check if role exists
        cur.execute(
            "SELECT slno FROM public.tbl_user_roles WHERE user_name = %s",
            (USER_NAME,),
        )
        if cur.fetchone():
            print(f"Role for '{USER_NAME}' already exists — skipping tbl_user_roles insert")
        else:
            cur.execute(
                "INSERT INTO public.tbl_user_roles "
                "(first_name, last_name, email_id, user_name, tenant, role, created_by, created_date) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())",
                (FIRST_NAME, LAST_NAME, EMAIL, USER_NAME, TENANT, ROLE, CREATED_BY),
            )
            role_inserted = True
            print(f"Inserted role '{ROLE}' for '{USER_NAME}' into public.tbl_user_roles")

        # 6. Commit the transaction
        conn.commit()
        print("\nTransaction committed.")

        # 7. Summary
        print("\n--- Summary ---")
        print(f"  tbl_users:      {'INSERTED' if user_inserted else 'SKIPPED (already exists)'}")
        print(f"  tbl_user_roles: {'INSERTED' if role_inserted else 'SKIPPED (already exists)'}")

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
