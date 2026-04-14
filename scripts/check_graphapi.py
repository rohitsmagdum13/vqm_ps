"""Script: check_graphapi.py

Verify Microsoft Graph API connectivity and mailbox access.

Tests:
  1. MSAL token acquisition (client_credentials flow)
  2. Mailbox access (GET /users/{mailbox})
  3. List recent messages (GET /users/{mailbox}/messages?$top=3)
  4. Unread message count

Uses the real GraphAPIConnector to test the same code path
the application uses.

Usage:
    uv run python scripts/check_graphapi.py
"""

from __future__ import annotations

import asyncio
import sys
import time

# Add src/ to Python path so imports work when run directly
sys.path.insert(0, ".")
sys.path.insert(0, "src")

from config.settings import get_settings  # noqa: E402
from adapters.graph_api import GraphAPIConnector  # noqa: E402
from utils.logger import LoggingSetup  # noqa: E402


def print_header(text: str) -> None:
    """Print a section header."""
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}\n")


def print_check(name: str, passed: bool, detail: str = "") -> None:
    """Print a check result."""
    status = "[PASS]" if passed else "[FAIL]"
    suffix = f" — {detail}" if detail else ""
    print(f"  {status} {name}{suffix}")


async def check_graphapi() -> None:
    """Run all Microsoft Graph API connectivity checks."""
    LoggingSetup.configure()
    settings = get_settings()

    print_header("VQMS — Microsoft Graph API Check")
    print(f"  Tenant ID:  {settings.graph_api_tenant_id or '(not set)'}")
    print(f"  Client ID:  {settings.graph_api_client_id or '(not set)'}")
    print(f"  Mailbox:    {settings.graph_api_mailbox}")
    print()

    # Validate required settings
    if not settings.graph_api_tenant_id or not settings.graph_api_client_id:
        print("  [SKIP] Graph API credentials not configured in .env")
        return

    graph = GraphAPIConnector(settings)

    try:
        # --- Check 1: MSAL Token Acquisition ---
        try:
            start = time.perf_counter()
            token = await graph._acquire_token(correlation_id="check-graphapi")
            elapsed = (time.perf_counter() - start) * 1000

            if token:
                # Show first/last chars for verification without exposing full token
                preview = f"{token[:10]}...{token[-10:]}"
                print_check("MSAL token acquisition", True, f"{elapsed:.0f}ms")
                print(f"          Token: {preview}")
            else:
                print_check("MSAL token acquisition", False, "No token returned")
                return
        except Exception as e:
            print_check("MSAL token acquisition", False, str(e))
            return

        # --- Check 2: Mailbox Access ---
        try:
            start = time.perf_counter()
            http_client = await graph._get_http_client()
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            mailbox_url = f"https://graph.microsoft.com/v1.0/users/{settings.graph_api_mailbox}"
            response = await http_client.get(mailbox_url, headers=headers)
            elapsed = (time.perf_counter() - start) * 1000

            if response.status_code == 200:
                user_data = response.json()
                display_name = user_data.get("displayName", "unknown")
                mail = user_data.get("mail", "unknown")
                print_check("Mailbox access", True, f"{elapsed:.0f}ms")
                print(f"          Display Name: {display_name}")
                print(f"          Mail:         {mail}")
            else:
                print_check(
                    "Mailbox access",
                    False,
                    f"HTTP {response.status_code}: {response.text[:100]}",
                )
        except Exception as e:
            print_check("Mailbox access", False, str(e))

        # --- Check 3: List Recent Messages ---
        try:
            start = time.perf_counter()
            messages_url = (
                f"https://graph.microsoft.com/v1.0/users/{settings.graph_api_mailbox}"
                "/messages?$top=3&$orderby=receivedDateTime desc"
                "&$select=id,subject,from,receivedDateTime,isRead,hasAttachments"
            )
            response = await http_client.get(messages_url, headers=headers)
            elapsed = (time.perf_counter() - start) * 1000

            if response.status_code == 200:
                data = response.json()
                messages = data.get("value", [])
                print_check("List recent messages", True, f"{len(messages)} message(s), {elapsed:.0f}ms")
                for i, msg in enumerate(messages, 1):
                    sender = msg.get("from", {}).get("emailAddress", {})
                    print(f"          [{i}] {msg.get('subject', '(no subject)')}")
                    print(f"              From: {sender.get('name', '?')} <{sender.get('address', '?')}>")
                    print(f"              Date: {msg.get('receivedDateTime', '?')}")
                    print(f"              Read: {msg.get('isRead', '?')}")
            else:
                print_check("List recent messages", False, f"HTTP {response.status_code}")
        except Exception as e:
            print_check("List recent messages", False, str(e))

        # --- Check 4: Unread Count ---
        try:
            messages = await graph.list_unread_messages(
                top=50, correlation_id="check-graphapi"
            )
            unread_count = len(messages) if messages else 0
            print_check("Unread message count", True, f"{unread_count} unread")
        except Exception as e:
            print_check("Unread message count", False, str(e))

    finally:
        await graph.close()

    print(f"\n{'=' * 60}\n")


def main() -> None:
    """Run the check."""
    asyncio.run(check_graphapi())


if __name__ == "__main__":
    main()
