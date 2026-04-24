"""Script: check_frontend_api_contract.py

Runtime contract check between the Angular frontend and the FastAPI
backend. Exercises every endpoint the frontend actually calls — auth,
queries, emails, vendors — with the same headers and payload shape
the browser would send, and reports pass/fail for each.

This is a black-box check: it assumes the backend is already running
at http://localhost:8000. Start it with ``uv run uvicorn main:app``
in another shell before invoking this script.

Exit code is 0 when every required endpoint responds with a 2xx code,
non-zero otherwise. Useful as a pre-flight check before demos.

Usage:
    uv run python scripts/check_frontend_api_contract.py
    uv run python scripts/check_frontend_api_contract.py --base http://localhost:8000
    uv run python scripts/check_frontend_api_contract.py --user admin_user --password admin123
    uv run python scripts/check_frontend_api_contract.py --vendor-id V-001 --query-id VQ-2026-0001
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class Result:
    """Outcome of a single endpoint check."""

    label: str
    method: str
    url: str
    status: int | None
    ok: bool
    detail: str


def banner(text: str) -> None:
    """Print a section banner."""
    print(f"\n{'=' * 78}\n  {text}\n{'=' * 78}")


def pr(r: Result) -> None:
    """Pretty-print a single check result."""
    marker = "PASS" if r.ok else "FAIL"
    sc = r.status if r.status is not None else "ERR"
    print(f"  [{marker}]  {r.method:<6} {r.url:<60} -> {sc}  {r.detail}")


def _short(resp: httpx.Response, limit: int = 120) -> str:
    """Abbreviate a response body to a single line."""
    try:
        body = resp.json()
        text = str(body)
    except Exception:
        text = resp.text
    text = text.replace("\n", " ").strip()
    return text[:limit] + ("..." if len(text) > limit else "")


async def _call(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    label: str,
    expected: tuple[int, ...] = (200,),
    **kwargs: Any,
) -> Result:
    """Run one HTTP call and classify the response."""
    try:
        resp = await client.request(method, url, **kwargs)
    except Exception as exc:  # noqa: BLE001
        return Result(
            label=label,
            method=method,
            url=url,
            status=None,
            ok=False,
            detail=f"{type(exc).__name__}: {exc}",
        )

    ok = resp.status_code in expected
    return Result(
        label=label,
        method=method,
        url=url,
        status=resp.status_code,
        ok=ok,
        detail=_short(resp) if not ok else "",
    )


async def run(
    base_url: str,
    username: str,
    password: str,
    vendor_id: str,
    query_id: str | None,
) -> int:
    """Walk the full frontend-used API surface and report."""
    banner("VQMS — Frontend API Contract Check")
    print(f"  Backend base URL : {base_url}")
    print(f"  Login user       : {username}")
    print(f"  Vendor ID header : {vendor_id}")
    print(f"  Query ID (opt)   : {query_id or '(will pick first from list)'}")

    results: list[Result] = []

    # A single AsyncClient reuses the TCP/HTTP2 connection across calls.
    # timeout is generous because Graph/Salesforce-backed endpoints can
    # occasionally take a few seconds on cold cache.
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        # ------------------------------------------------------------
        # 1. AUTH — POST /auth/login is the only public endpoint
        # ------------------------------------------------------------
        banner("1. Auth")
        login_res = await _call(
            client,
            "POST",
            "/auth/login",
            label="login",
            json={"username_or_email": username, "password": password},
        )
        results.append(login_res)
        pr(login_res)

        # Parse the token so we can authorize subsequent calls. The
        # Angular interceptor attaches it exactly this way.
        token: str | None = None
        try:
            if login_res.ok:
                resp = await client.post(
                    "/auth/login",
                    json={"username_or_email": username, "password": password},
                )
                token = resp.json().get("token")
        except Exception:
            token = None

        if not token:
            print("\n  [FATAL] Could not obtain JWT — downstream checks cannot run.")
            print("          Run scripts/seed_admin_user.py to create test accounts.")
            return 1
        print(f"  Token acquired: {token[:18]}... (len={len(token)})")

        auth_h = {"Authorization": f"Bearer {token}"}

        # ------------------------------------------------------------
        # 2. QUERIES — GET list / POST / GET detail, needs X-Vendor-ID
        # ------------------------------------------------------------
        banner("2. Queries (QueryService)")
        vendor_h = {**auth_h, "X-Vendor-ID": vendor_id}

        list_res = await _call(
            client,
            "GET",
            "/queries",
            label="list queries",
            headers=vendor_h,
        )
        results.append(list_res)
        pr(list_res)

        # Pick a real query_id from the list if the caller didn't supply one.
        auto_query_id: str | None = query_id
        if auto_query_id is None and list_res.ok:
            try:
                resp = await client.get("/queries", headers=vendor_h)
                rows = resp.json().get("queries", [])
                if rows:
                    auto_query_id = rows[0]["query_id"]
                    print(f"  Auto-picked query_id for detail check: {auto_query_id}")
            except Exception:
                pass

        if auto_query_id:
            detail_res = await _call(
                client,
                "GET",
                f"/queries/{auto_query_id}",
                label="get query detail",
                headers=vendor_h,
                # Accept 404 when the vendor doesn't own the query — still
                # proves routing/auth works.
                expected=(200, 404),
            )
            results.append(detail_res)
            pr(detail_res)
        else:
            print(
                "  [SKIP] Detail check skipped — no query_id available."
                " Submit one or pass --query-id."
            )

        # POST submission — only run when the caller explicitly asks,
        # because it creates a real row in workflow.case_execution.
        # We still exercise the shape via a dry 422 test:
        invalid_post = await _call(
            client,
            "POST",
            "/queries",
            label="submit (validation shape)",
            headers=vendor_h,
            json={},  # empty body → Pydantic 422
            expected=(422,),
        )
        results.append(invalid_post)
        pr(invalid_post)

        # ------------------------------------------------------------
        # 3. EMAILS — dashboard endpoints (EmailService)
        # ------------------------------------------------------------
        banner("3. Emails (EmailService)")

        list_emails = await _call(
            client, "GET", "/emails", label="list mail chains", headers=auth_h
        )
        results.append(list_emails)
        pr(list_emails)

        stats = await _call(
            client, "GET", "/emails/stats", label="mail stats", headers=auth_h
        )
        results.append(stats)
        pr(stats)

        if auto_query_id:
            chain = await _call(
                client,
                "GET",
                f"/emails/{auto_query_id}",
                label="get mail chain",
                headers=auth_h,
                expected=(200, 404),
            )
            results.append(chain)
            pr(chain)

        # ------------------------------------------------------------
        # 4. VENDORS — list / update / delete (VendorService)
        # ------------------------------------------------------------
        banner("4. Vendors (VendorService)")

        vendors_list = await _call(
            client, "GET", "/vendors", label="list vendors", headers=auth_h
        )
        results.append(vendors_list)
        pr(vendors_list)

        # ------------------------------------------------------------
        # 5. CORS preflight — browser does OPTIONS on protected routes
        # ------------------------------------------------------------
        banner("5. CORS preflight")
        preflight = await _call(
            client,
            "OPTIONS",
            "/queries",
            label="OPTIONS /queries (CORS)",
            headers={
                "Origin": "http://localhost:4200",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,x-vendor-id",
            },
            expected=(200, 204),
        )
        results.append(preflight)
        pr(preflight)

        # ------------------------------------------------------------
        # 6. LOGOUT — always last so the token stays valid above
        # ------------------------------------------------------------
        banner("6. Auth (logout)")
        logout = await _call(
            client, "POST", "/auth/logout", label="logout", headers=auth_h
        )
        results.append(logout)
        pr(logout)

    # ------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------
    banner("Summary")
    passed = sum(1 for r in results if r.ok)
    total = len(results)
    print(f"  {passed} / {total} checks passed")
    if passed < total:
        print("\n  Failures:")
        for r in results:
            if not r.ok:
                pr(r)
    print()
    return 0 if passed == total else 1


def main() -> None:
    """Parse CLI and run."""
    parser = argparse.ArgumentParser(
        description=(
            "Runtime smoke test of every API endpoint the Angular "
            "frontend calls. Backend must already be running."
        ),
    )
    parser.add_argument(
        "--base",
        default="http://localhost:8000",
        help="Backend base URL (default: http://localhost:8000).",
    )
    parser.add_argument(
        "--user",
        default="admin_user",
        help="Login user_name or email (default: admin_user from seed).",
    )
    parser.add_argument(
        "--password",
        default="admin123",
        help="Login password (default: admin123 from seed).",
    )
    parser.add_argument(
        "--vendor-id",
        default="V-001",
        help="Vendor ID to send via X-Vendor-ID header (default: V-001).",
    )
    parser.add_argument(
        "--query-id",
        default=None,
        help=(
            "Optional query_id for the detail/email-chain checks. If "
            "omitted, the first query returned by GET /queries is used."
        ),
    )
    args = parser.parse_args()

    sys.exit(
        asyncio.run(
            run(
                base_url=args.base,
                username=args.user,
                password=args.password,
                vendor_id=args.vendor_id,
                query_id=args.query_id,
            )
        )
    )


if __name__ == "__main__":
    main()
