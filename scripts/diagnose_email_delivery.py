"""Diagnose why outbound admin emails are being blocked by Microsoft 365.

Triggered by the 5.7.708 NDR ("Access denied, traffic not accepted from
this IP") on a send through Graph API's /sendMail endpoint. The send
itself succeeds (Graph returns 202) but Exchange Online's outbound
filter then refuses to relay externally.

This script pulls every signal we can grab without admin-portal access:

  1.  Token acquisition + scope inspection (proves the app registration
      is valid and what Graph permissions it actually carries).
  2.  Mailbox metadata via Graph /users/{mailbox} — confirms the
      mailbox exists, is licensed, and isn't soft-deleted.
  3.  Recent items in SentItems — was the message actually delivered
      to the local sent items folder?
  4.  Recent items in Inbox — did we receive an NDR / bounce email
      from postmaster@outlook.com?
  5.  Public DNS — SPF, DMARC, and DKIM selectors of the sender domain.
      Most 5.7.708 from Graph trace back to a missing or broken DKIM.
  6.  Recent rows from intake.admin_outbound_emails (our DB tracking
      table) — confirms whether the row was marked SENT or FAILED
      and shows the recipient + correlation_id.

Each check runs independently. A failure (e.g. insufficient Graph
permissions) is reported but does NOT abort the rest of the run.

Usage:
    uv run python scripts/diagnose_email_delivery.py
    uv run python scripts/diagnose_email_delivery.py --to vendor@gmail.com

Output is a structured report with PASS / FAIL / SKIP indicators and a
"Likely root cause" summary at the bottom.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
from dataclasses import dataclass, field
from typing import Any

# Add src/ to Python path so config / db imports work when run directly.
sys.path.insert(0, ".")
sys.path.insert(0, "src")

import httpx  # noqa: E402
import msal  # noqa: E402
import structlog  # noqa: E402

from config.settings import get_settings  # noqa: E402

logger = structlog.get_logger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPES = ["https://graph.microsoft.com/.default"]


# ----------------------------------------------------------------------
# Output helpers
# ----------------------------------------------------------------------


@dataclass
class CheckResult:
    """Result of a single diagnostic check."""

    name: str
    status: str  # PASS | FAIL | SKIP | INFO
    detail: str = ""
    raw: Any = None


@dataclass
class Report:
    """Collected results across all diagnostic checks."""

    results: list[CheckResult] = field(default_factory=list)

    def add(self, name: str, status: str, detail: str = "", raw: Any = None) -> None:
        self.results.append(CheckResult(name=name, status=status, detail=detail, raw=raw))

    def by_status(self, status: str) -> list[CheckResult]:
        return [r for r in self.results if r.status == status]


def _hr(title: str = "") -> None:
    bar = "=" * 70
    if title:
        print(f"\n{bar}\n  {title}\n{bar}")
    else:
        print(bar)


def _line(check: CheckResult) -> None:
    icon = {"PASS": "[OK]", "FAIL": "[FAIL]", "SKIP": "[SKIP]", "INFO": "[INFO]"}.get(
        check.status, f"[{check.status}]"
    )
    print(f"  {icon:<8} {check.name}")
    if check.detail:
        for line in check.detail.split("\n"):
            print(f"           {line}")


# ----------------------------------------------------------------------
# Check 1 — Token + scopes
# ----------------------------------------------------------------------


async def check_token_and_scopes(settings, report: Report) -> str | None:
    """Acquire an MSAL token and decode it to inspect what scopes it carries."""
    _hr("1. Graph API app registration — token + scopes")

    if not all(
        [settings.graph_api_tenant_id, settings.graph_api_client_id, settings.graph_api_client_secret]
    ):
        report.add(
            "App registration credentials present",
            "FAIL",
            "graph_api_tenant_id / graph_api_client_id / graph_api_client_secret missing in .env",
        )
        _line(report.results[-1])
        return None

    report.add("App registration credentials present", "PASS")
    _line(report.results[-1])

    authority = f"https://login.microsoftonline.com/{settings.graph_api_tenant_id}"
    app = msal.ConfidentialClientApplication(
        settings.graph_api_client_id,
        authority=authority,
        client_credential=settings.graph_api_client_secret,
    )
    result = await asyncio.to_thread(app.acquire_token_for_client, scopes=GRAPH_SCOPES)

    if "access_token" not in result:
        report.add(
            "Token acquisition",
            "FAIL",
            f"MSAL error: {result.get('error')} — {result.get('error_description', '')[:200]}",
        )
        _line(report.results[-1])
        return None

    token: str = result["access_token"]
    report.add(
        "Token acquisition",
        "PASS",
        f"Token type: {result.get('token_type')}, expires_in: {result.get('expires_in')}s",
    )
    _line(report.results[-1])

    # Decode the JWT body (no signature verification — we just want the claims)
    try:
        body_b64 = token.split(".")[1]
        body_b64 += "=" * (-len(body_b64) % 4)  # pad
        body = json.loads(base64.urlsafe_b64decode(body_b64))
        roles = body.get("roles", [])
        scp = body.get("scp", "")
        app_id = body.get("appid")
        tenant_id = body.get("tid")
        detail = (
            f"appid: {app_id}\n"
            f"tenant: {tenant_id}\n"
            f"roles (Application permissions): {roles or '(none)'}\n"
            f"scp (Delegated): {scp or '(none)'}"
        )
        # Mail.Send is the minimum we need
        if "Mail.Send" in roles:
            report.add("Mail.Send Application permission", "PASS", detail)
        else:
            report.add(
                "Mail.Send Application permission",
                "FAIL",
                detail
                + "\nFix: Azure portal -> App registrations -> API permissions -> "
                + "Add Mail.Send (Application), then 'Grant admin consent'.",
            )
        _line(report.results[-1])

        # Bonus checks for diagnostics — these are "would be nice"
        for needed, why in [
            ("Mail.Read", "to read NDR bounce messages from inbox"),
            ("User.Read.All", "to read mailbox metadata (license, status)"),
            ("MailboxSettings.Read", "to read sender mailbox settings"),
        ]:
            if needed in roles:
                report.add(f"{needed} permission", "PASS", why)
            else:
                report.add(f"{needed} permission", "SKIP", f"not granted — {why} unavailable")
            _line(report.results[-1])

    except Exception as exc:
        report.add("JWT scope decode", "FAIL", str(exc))
        _line(report.results[-1])

    return token


# ----------------------------------------------------------------------
# Check 2 — Mailbox metadata
# ----------------------------------------------------------------------


async def check_mailbox(token: str, mailbox: str, report: Report) -> None:
    """GET /users/{mailbox} — confirms the mailbox is alive."""
    _hr("2. Sender mailbox metadata")
    print(f"  mailbox: {mailbox}")

    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(f"{GRAPH_BASE}/users/{mailbox}", headers=headers)
    if r.status_code == 200:
        u = r.json()
        detail = (
            f"id:                {u.get('id')}\n"
            f"displayName:       {u.get('displayName')}\n"
            f"userPrincipalName: {u.get('userPrincipalName')}\n"
            f"accountEnabled:    {u.get('accountEnabled')}\n"
            f"mail:              {u.get('mail')}\n"
            f"mailNickname:      {u.get('mailNickname')}"
        )
        report.add("Mailbox exists and is readable", "PASS", detail)
    elif r.status_code == 403:
        report.add(
            "Mailbox exists and is readable",
            "SKIP",
            "Graph returned 403 — User.Read.All permission not granted. "
            "Cannot verify mailbox metadata, but Mail.Send still works.",
        )
    elif r.status_code == 404:
        report.add(
            "Mailbox exists and is readable",
            "FAIL",
            f"GET /users/{mailbox} returned 404 — the mailbox does NOT exist or "
            "the UPN is wrong. Check GRAPH_API_MAILBOX in .env.",
        )
    else:
        report.add(
            "Mailbox exists and is readable",
            "FAIL",
            f"HTTP {r.status_code}: {r.text[:300]}",
        )
    _line(report.results[-1])


# ----------------------------------------------------------------------
# Check 3 — Recent SentItems
# ----------------------------------------------------------------------


async def check_sent_items(token: str, mailbox: str, report: Report) -> None:
    """List the 5 most recent items in SentItems."""
    _hr("3. Recent items in mailbox SentItems")

    headers = {"Authorization": f"Bearer {token}"}
    url = (
        f"{GRAPH_BASE}/users/{mailbox}/mailFolders/SentItems/messages"
        "?$top=5&$select=subject,toRecipients,sentDateTime,bodyPreview"
        "&$orderby=sentDateTime desc"
    )
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url, headers=headers)

    if r.status_code != 200:
        if r.status_code == 403:
            report.add(
                "SentItems readable",
                "SKIP",
                "Mail.Read permission not granted — cannot list sent items.",
            )
        else:
            report.add("SentItems readable", "FAIL", f"HTTP {r.status_code}: {r.text[:300]}")
        _line(report.results[-1])
        return

    items = r.json().get("value", [])
    if not items:
        report.add(
            "SentItems readable",
            "INFO",
            "Folder is empty — either nothing has been sent, or saveToSentItems=False.",
        )
        _line(report.results[-1])
        return

    lines = []
    for m in items:
        recipients = ", ".join(
            t["emailAddress"]["address"] for t in m.get("toRecipients", [])
        )
        lines.append(f"- [{m.get('sentDateTime')}] {m.get('subject')} -> {recipients}")
    report.add(
        "SentItems readable",
        "PASS",
        f"Last {len(items)} sent items:\n" + "\n".join(lines),
    )
    _line(report.results[-1])


# ----------------------------------------------------------------------
# Check 4 — Recent NDRs / bounces in Inbox
# ----------------------------------------------------------------------


async def check_inbox_ndrs(token: str, mailbox: str, report: Report) -> None:
    """Find recent NDR / postmaster bounce messages in Inbox.

    We pull the latest 25 messages and filter client-side. Graph's
    $filter with multiple ``contains()`` clauses returns 400
    "InefficientFilter" so we deliberately avoid that path.
    """
    _hr("4. Recent NDR/bounce messages in Inbox")

    headers = {"Authorization": f"Bearer {token}"}
    url = (
        f"{GRAPH_BASE}/users/{mailbox}/messages"
        "?$top=25"
        "&$select=subject,from,receivedDateTime,bodyPreview,body"
        "&$orderby=receivedDateTime desc"
    )
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url, headers=headers)

    if r.status_code != 200:
        if r.status_code == 403:
            report.add(
                "NDR scan",
                "SKIP",
                "Mail.Read not granted — cannot scan inbox for bounces.",
            )
        else:
            report.add("NDR scan", "FAIL", f"HTTP {r.status_code}: {r.text[:300]}")
        _line(report.results[-1])
        return

    NDR_KEYWORDS = (
        "undeliverable",
        "delivery status notification",
        "delivery has failed",
        "mail delivery failed",
        "returned mail",
    )
    NDR_SENDER_PATTERNS = (
        "postmaster@",
        "mailer-daemon@",
        "microsoftexchange",
    )

    candidates = []
    for m in r.json().get("value", []):
        subject = (m.get("subject") or "").lower()
        sender = m.get("from", {}).get("emailAddress", {}).get("address", "").lower()
        if any(k in subject for k in NDR_KEYWORDS) or any(p in sender for p in NDR_SENDER_PATTERNS):
            candidates.append(m)

    if not candidates:
        report.add(
            "NDR scan",
            "PASS",
            "No NDR / bounce messages in the latest 25 inbox items.",
        )
        _line(report.results[-1])
        return

    lines = []
    error_codes_found = set()
    for m in candidates[:5]:
        sender = m.get("from", {}).get("emailAddress", {}).get("address", "?")
        body_text = (m.get("body", {}).get("content") or "").strip()
        # Normalize whitespace for the snippet
        body_snippet = " ".join(body_text.split())[:600]
        lines.append(f"- [{m.get('receivedDateTime')}] from {sender}")
        lines.append(f"    subject: {m.get('subject')}")
        lines.append(f"    body:    {body_snippet}")
        for code in (
            "5.7.708",
            "5.7.26",
            "5.7.1",
            "5.4.1",
            "550 5.1.1",
            "5.7.350",
            "5.2.121",
            "5.7.509",
            "5.7.510",
        ):
            if code in body_text or code in (m.get("subject") or ""):
                error_codes_found.add(code)

    detail = "\n".join(lines)
    if error_codes_found:
        detail += "\n\n  *** ERROR CODES detected: " + ", ".join(sorted(error_codes_found)) + " ***"
    report.add(
        "NDR scan",
        "INFO",
        f"Found {len(candidates)} bounce(s) (showing latest 5):\n{detail}",
    )
    _line(report.results[-1])


# ----------------------------------------------------------------------
# Check 5 — DNS records of sender domain
# ----------------------------------------------------------------------


def check_dns(mailbox: str, report: Report) -> None:
    """Look up SPF, DMARC, DKIM for the sender's domain."""
    _hr("5. Sender-domain DNS records (SPF / DMARC / DKIM)")

    if "@" not in mailbox:
        report.add("Parse sender domain", "FAIL", f"mailbox '{mailbox}' has no '@'")
        _line(report.results[-1])
        return
    domain = mailbox.split("@", 1)[1]
    print(f"  domain: {domain}")

    try:
        import dns.resolver  # type: ignore
    except ImportError:
        report.add(
            "DNS lookups",
            "SKIP",
            "dnspython not installed — install with `uv add dnspython`",
        )
        _line(report.results[-1])
        return

    # Corporate DNS often blocks external lookups. Use Google Public DNS
    # + Cloudflare as a fallback so we get a real answer regardless of
    # the workstation's resolver config.
    resolver = dns.resolver.Resolver(configure=False)
    resolver.nameservers = ["8.8.8.8", "1.1.1.1"]
    resolver.lifetime = 8.0
    resolver.timeout = 4.0

    # .onmicrosoft.com is a Microsoft-managed domain — you cannot publish
    # SPF / DKIM / DMARC records on it because you don't own the DNS zone.
    # Microsoft already publishes default records on its side. The check
    # is still useful (we read what Microsoft publishes) but we surface a
    # warning so the diagnosis is not "fix your DNS" when there's no DNS
    # to fix.
    if domain.endswith(".onmicrosoft.com"):
        report.add(
            "Sender domain is .onmicrosoft.com",
            "FAIL",
            "Microsoft restricts external delivery from default "
            ".onmicrosoft.com tenants. Even with SPF/DKIM/DMARC valid (managed "
            "by Microsoft), outbound to gmail.com / yahoo.com / etc. is "
            "throttled or blocked. This is the documented cause of 5.7.708 "
            "for new dev tenants and is policy, not config.\n\n"
            "Fix: add a custom domain to the M365 tenant (Microsoft Admin "
            "Center -> Settings -> Domains -> Add domain), verify it via "
            "DNS, set it as default, and switch GRAPH_API_MAILBOX to a "
            "user on the custom domain. Outbound delivery normalises after "
            "that.",
        )
        _line(report.results[-1])

    # --- SPF ---
    try:
        txts = resolver.resolve(domain, "TXT")
        spf_records = [
            "".join(s.decode() if isinstance(s, bytes) else s for s in r.strings)
            for r in txts
            if any((s.decode() if isinstance(s, bytes) else s).startswith("v=spf1") for s in r.strings)
        ]
        if spf_records:
            spf = spf_records[0]
            ok = "include:spf.protection.outlook.com" in spf
            report.add(
                "SPF record",
                "PASS" if ok else "FAIL",
                f"{spf}\n"
                + (
                    "OK — includes spf.protection.outlook.com"
                    if ok
                    else "MISSING include:spf.protection.outlook.com — Gmail/Yahoo "
                    "will reject mail from M365 unless this is added."
                ),
            )
        else:
            report.add(
                "SPF record",
                "FAIL",
                f"No 'v=spf1' TXT record found on {domain}. "
                "Add: v=spf1 include:spf.protection.outlook.com -all",
            )
    except Exception as exc:
        report.add("SPF record", "FAIL", f"DNS lookup failed: {exc}")
    _line(report.results[-1])

    # --- DMARC ---
    try:
        txts = resolver.resolve(f"_dmarc.{domain}", "TXT")
        dmarc = "".join(
            "".join(s.decode() if isinstance(s, bytes) else s for s in r.strings) for r in txts
        )
        report.add(
            "DMARC record",
            "PASS" if dmarc.startswith("v=DMARC1") else "FAIL",
            dmarc or "(empty)",
        )
    except dns.resolver.NXDOMAIN:
        report.add(
            "DMARC record",
            "FAIL",
            f"No _dmarc.{domain} record. Add minimum: v=DMARC1; p=none; rua=mailto:postmaster@{domain}",
        )
    except Exception as exc:
        report.add("DMARC record", "FAIL", f"DNS lookup failed: {exc}")
    _line(report.results[-1])

    # --- DKIM (M365 default selectors) ---
    for selector in ("selector1", "selector2"):
        host = f"{selector}._domainkey.{domain}"
        try:
            cnames = resolver.resolve(host, "CNAME")
            target = str(list(cnames)[0])
            ok = "onmicrosoft.com" in target or "domainkey" in target
            report.add(
                f"DKIM {selector}",
                "PASS" if ok else "INFO",
                f"{host} -> {target}",
            )
        except dns.resolver.NXDOMAIN:
            report.add(
                f"DKIM {selector}",
                "FAIL",
                f"No CNAME at {host}. DKIM is NOT signed by M365 -> Gmail/Yahoo "
                "will mark as spam or refuse delivery. Enable DKIM in Exchange "
                "Admin Center -> Mail flow -> DKIM.",
            )
        except Exception as exc:
            report.add(f"DKIM {selector}", "FAIL", f"DNS lookup failed: {exc}")
        _line(report.results[-1])


# ----------------------------------------------------------------------
# Check 6 — DB tracking rows
# ----------------------------------------------------------------------


async def check_db_records(report: Report) -> None:
    """Read recent intake.admin_outbound_emails rows."""
    _hr("6. Recent admin email sends (DB)")

    try:
        from db.connection import PostgresConnector

        settings = get_settings()
        pg = PostgresConnector(settings)
        await pg.connect()
    except Exception as exc:
        report.add("PostgreSQL connect", "FAIL", str(exc)[:300])
        _line(report.results[-1])
        return

    try:
        rows = await pg.fetch(
            """
            SELECT outbound_id, actor, status, last_error,
                   to_recipients, subject, sent_at, failed_at, created_at
            FROM intake.admin_outbound_emails
            ORDER BY created_at DESC
            LIMIT 5
            """,
        )
    except Exception as exc:
        report.add("Read admin_outbound_emails", "FAIL", str(exc)[:300])
        _line(report.results[-1])
        await pg.disconnect()
        return

    if not rows:
        report.add(
            "Read admin_outbound_emails",
            "INFO",
            "Table is empty — no admin sends recorded.",
        )
        _line(report.results[-1])
        await pg.disconnect()
        return

    sent_count = sum(1 for r in rows if r["status"] == "SENT")
    failed_count = sum(1 for r in rows if r["status"] == "FAILED")
    lines = []
    for r in rows:
        recips = r["to_recipients"]
        if isinstance(recips, str):
            try:
                recips = json.loads(recips)
            except Exception:
                pass
        recips_s = ", ".join(recips) if isinstance(recips, list) else str(recips)
        line = (
            f"- {r['outbound_id']}  status={r['status']}  "
            f"actor={r['actor']}  to={recips_s}  "
            f"subject={r['subject'][:60]}"
        )
        if r.get("last_error"):
            line += f"\n    last_error: {r['last_error'][:200]}"
        lines.append(line)

    report.add(
        "Read admin_outbound_emails",
        "PASS",
        f"Last {len(rows)} rows ({sent_count} SENT, {failed_count} FAILED):\n"
        + "\n".join(lines)
        + "\n\nNote: Graph returning 200 stamps these as SENT. A subsequent "
        "5.7.708 NDR is delivered async to the sender mailbox and does NOT "
        "flip the row back to FAILED.",
    )
    _line(report.results[-1])
    await pg.disconnect()


# ----------------------------------------------------------------------
# Summary
# ----------------------------------------------------------------------


def summarise(report: Report, mailbox: str) -> None:
    _hr("DIAGNOSIS")

    fails = report.by_status("FAIL")
    skips = report.by_status("SKIP")

    print(f"  PASS: {len(report.by_status('PASS'))}")
    print(f"  FAIL: {len(fails)}")
    print(f"  SKIP: {len(skips)}")
    print(f"  INFO: {len(report.by_status('INFO'))}")

    print()
    print("  Likely root cause(s) of the 5.7.708 bounce, ordered by likelihood:")
    print()

    # Heuristic ordering — if any of these failed, surface them with action.
    causes = []
    fail_names = {f.name for f in fails}

    # The most decisive signal first.
    if "Sender domain is .onmicrosoft.com" in fail_names:
        causes.append(
            (
                "Sender mailbox is on a default .onmicrosoft.com tenant.",
                "Microsoft caps and often blocks external delivery from these "
                "domains. Add a custom domain in Microsoft 365 Admin Center "
                "-> Settings -> Domains, verify it (TXT record), make it the "
                "default, then switch GRAPH_API_MAILBOX in .env to a user on "
                "the new domain. Restart the app. Outbound delivery to Gmail "
                "etc. will start working without further code changes.",
            )
        )

    # NDR error code clues
    ndr_codes = ""
    for r in report.results:
        if r.name == "NDR scan" and "ERROR CODES detected" in (r.detail or ""):
            ndr_codes = r.detail
            break
    if "5.2.121" in ndr_codes:
        causes.append(
            (
                "NDR returned 5.2.121 — sender restricted (Microsoft outbound spam policy).",
                "The sender mailbox has been auto-restricted by EOP. Go to "
                "https://security.microsoft.com/restrictedusers and unblock.",
            )
        )

    if "DKIM selector1" in fail_names or "DKIM selector2" in fail_names:
        causes.append(
            (
                "DKIM is not enabled on the sender domain.",
                "Exchange Admin Center -> Mail flow -> DKIM -> select your "
                f"domain ({mailbox.split('@', 1)[1]}) -> Enable. Then publish "
                "the two CNAME records DKIM page shows you. Without DKIM, "
                "Gmail/Yahoo silently reject mail from M365 tenants and "
                "Microsoft routes the next attempt through HRDP, which is "
                "what 5.7.708 reports.",
            )
        )

    if "DMARC record" in fail_names:
        causes.append(
            (
                "No DMARC record published on sender domain.",
                f"Add a TXT record at _dmarc.{mailbox.split('@', 1)[1]}:\n"
                f"             v=DMARC1; p=none; rua=mailto:postmaster@{mailbox.split('@', 1)[1]}",
            )
        )

    if "SPF record" in fail_names:
        causes.append(
            (
                "SPF record missing or doesn't authorise M365.",
                f"Add/replace the TXT record on {mailbox.split('@', 1)[1]}:\n"
                "             v=spf1 include:spf.protection.outlook.com -all",
            )
        )

    if "Mailbox exists and is readable" in fail_names:
        causes.append(
            (
                "Sender mailbox does not exist (404).",
                f"Confirm GRAPH_API_MAILBOX={mailbox} matches a real licensed "
                "user in your M365 tenant.",
            )
        )

    # If everything DNS-related passed, the issue is tenant-side (HRDP / restricted user).
    if not causes:
        causes.append(
            (
                "Code + DNS look fine — the 5.7.708 is tenant-side.",
                "Two admin actions to take, in order:\n"
                "  a) Microsoft Defender -> https://security.microsoft.com/restrictedusers\n"
                "     -> check whether your sender mailbox is listed -> Unblock.\n"
                "  b) Exchange Admin Center -> Mail flow -> Message trace\n"
                "     -> filter by sender = your mailbox, recipient = the gmail address\n"
                "     -> open the failed delivery -> read the full diagnostic.\n"
                "     The trace tells you exactly which Exchange component\n"
                "     refused the relay and why.",
            )
        )

    for i, (cause, fix) in enumerate(causes, 1):
        print(f"  {i}. {cause}")
        for line in fix.split("\n"):
            print(f"           {line}")
        print()


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--to",
        default=None,
        help="(Reserved — recipient context for future delivery probe)",
    )
    args = parser.parse_args()

    settings = get_settings()
    mailbox = settings.graph_api_mailbox

    print("VQMS Admin Email Delivery Diagnostic")
    print(f"  sender mailbox: {mailbox}")
    if args.to:
        print(f"  recipient hint: {args.to}")

    report = Report()

    token = await check_token_and_scopes(settings, report)
    if token:
        await check_mailbox(token, mailbox, report)
        await check_sent_items(token, mailbox, report)
        await check_inbox_ndrs(token, mailbox, report)
    else:
        print("\n  (Skipping Graph-dependent checks — no token.)")

    check_dns(mailbox, report)

    await check_db_records(report)

    summarise(report, mailbox)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
