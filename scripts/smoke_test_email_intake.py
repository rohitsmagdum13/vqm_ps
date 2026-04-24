"""Script: smoke_test_email_intake.py

Offline smoke test for the Email Ingestion Service.

Exercises the full 10-step pipeline using AsyncMock connectors.
Requires ZERO external services — no SSH tunnel, no AWS credentials,
no MS Graph access, no Salesforce login.

Runs in seconds and is safe to re-run without side effects.

Usage:
    uv run python scripts/smoke_test_email_intake.py

Scenarios covered:
    1. Happy path         — new email, vendor resolved, SQS enqueued
    2. Duplicate email    — idempotency returns False, pipeline short-circuits
    3. Vendor unresolved  — Salesforce returns None; domain allowlist lets it pass
    4. Salesforce failure — non-critical; email still processes
    5. Relevance reject   — unknown sender + no allowlist → dropped, no SQS

For the REAL end-to-end test that hits live services (Graph API,
PostgreSQL, S3, SQS, EventBridge, Salesforce), use:
    uv run python scripts/test_email_ingestion.py
"""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

# Make src/ importable when running as a script
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from config.settings import Settings, get_settings  # noqa: E402
from models.vendor import VendorMatch  # noqa: E402
from services.email_intake import EmailIntakeService  # noqa: E402


# ----------------------------------------------------------------------
# Test fixtures — synthetic Graph API payload, sample vendor match
# ----------------------------------------------------------------------

SAMPLE_MESSAGE_ID = "AAMkAGI2TG93-smoke-test"


def build_graph_email(
    *,
    sender_email: str = "rajesh.kumar@technova.com",
    sender_name: str = "Rajesh Kumar",
    subject: str = "Invoice discrepancy for PO-2026-1234",
    body_text: str = (
        "Hi team, the invoice amount on INV-5678 does not match the "
        "purchase order PO-2026-1234. Please review and advise."
    ),
) -> dict[str, Any]:
    """Build a Graph API message response that looks like a real email."""
    return {
        "id": SAMPLE_MESSAGE_ID,
        "from": {
            "emailAddress": {"name": sender_name, "address": sender_email},
        },
        "toRecipients": [
            {"emailAddress": {"address": "vendor-support@company.com"}}
        ],
        "subject": subject,
        "body": {"contentType": "text", "content": body_text},
        "bodyPreview": body_text[:100],
        "conversationId": "conv-AAMkAGI2",
        "internetMessageHeaders": [
            {"name": "Message-ID", "value": f"<{SAMPLE_MESSAGE_ID}@exchange.local>"},
        ],
        "hasAttachments": False,
        "attachments": [],
    }


def build_vendor_match() -> VendorMatch:
    """Return a deterministic VendorMatch for TechNova."""
    return VendorMatch(
        vendor_id="V-001",
        vendor_name="TechNova",
        match_method="exact_email",
        confidence=0.98,
        matched_contact_email="rajesh.kumar@technova.com",
    )


# ----------------------------------------------------------------------
# Connector mocks — one function per connector so each scenario can
# tweak the behaviour it cares about without reinventing the rest.
# ----------------------------------------------------------------------


def make_graph_api_mock(raw_email: dict[str, Any]) -> AsyncMock:
    mock = AsyncMock()
    mock.fetch_email.return_value = raw_email
    mock.send_email.return_value = None
    return mock


def make_postgres_mock(*, is_new: bool = True) -> AsyncMock:
    """Postgres connector stub with claim-check + transactional outbox.

    - ``check_idempotency`` controls the claim branch (True = claimed,
      False = duplicate/in-flight).
    - ``transaction()`` yields a mocked asyncpg-like connection so
      ``persist_email_atomically`` can ``async with`` it.
    - ``execute`` / ``fetch`` / ``fetchrow`` return no-op defaults for
      any non-transactional call sites.
    """
    mock = AsyncMock()
    mock.check_idempotency.return_value = is_new
    mock.execute.return_value = None
    mock.fetch.return_value = []
    mock.fetch_unsent_outbox.return_value = []
    mock.fetchrow.return_value = None

    tx_conn = AsyncMock()
    tx_conn.execute.return_value = "INSERT 0 1"

    @asynccontextmanager
    async def _fake_transaction():
        yield tx_conn

    # MagicMock (not AsyncMock) so that calling .transaction() returns
    # the async context manager itself, not a coroutine wrapping it.
    mock.transaction = MagicMock(side_effect=_fake_transaction)
    return mock


def make_s3_mock(query_id: str = "VQ-2026-0001") -> AsyncMock:
    mock = AsyncMock()
    mock.upload_file.return_value = f"inbound-emails/{query_id}/raw_email.json"
    return mock


def make_sqs_mock() -> AsyncMock:
    mock = AsyncMock()
    mock.send_message.return_value = "mock-sqs-message-id"
    return mock


def make_eventbridge_mock() -> AsyncMock:
    mock = AsyncMock()
    mock.publish_event.return_value = "mock-event-id"
    return mock


def make_salesforce_mock(
    *,
    match: VendorMatch | None = None,
    raise_error: bool = False,
) -> AsyncMock:
    """Salesforce stub that drives the 3 vendor resolution branches.

    - match=<VendorMatch>  → vendor resolved, match_method from the object
    - match=None           → vendor unresolved
    - raise_error=True     → non-critical exception, VendorIdentifier swallows
    """
    mock = AsyncMock()
    if raise_error:
        mock.identify_vendor.side_effect = RuntimeError("Salesforce down")
    else:
        mock.identify_vendor.return_value = match
    return mock


def build_test_settings(allowed_domains: list[str] | None = None) -> Settings:
    """Load real settings then override only what the test needs.

    We clone the cached settings instance and bypass validation because
    Settings is a pydantic BaseSettings — the test only flips two fields.
    """
    base = get_settings()
    overrides = base.model_dump()
    overrides["email_filter_allowed_sender_domains"] = allowed_domains or []
    overrides["email_filter_use_llm_classifier"] = False
    return Settings(**overrides)


def build_service(
    *,
    graph_api: AsyncMock,
    postgres: AsyncMock,
    s3: AsyncMock,
    sqs: AsyncMock,
    eventbridge: AsyncMock,
    salesforce: AsyncMock,
    settings: Settings,
) -> EmailIntakeService:
    return EmailIntakeService(
        graph_api=graph_api,
        postgres=postgres,
        s3=s3,
        sqs=sqs,
        eventbridge=eventbridge,
        salesforce=salesforce,
        settings=settings,
    )


# ----------------------------------------------------------------------
# Pretty-printing helpers
# ----------------------------------------------------------------------


def header(text: str) -> None:
    bar = "=" * 64
    print(f"\n{bar}\n  {text}\n{bar}")


def check(label: str, condition: bool, detail: str = "") -> bool:
    marker = "[ OK ]" if condition else "[FAIL]"
    suffix = f" — {detail}" if detail else ""
    print(f"  {marker}  {label}{suffix}")
    return condition


# ----------------------------------------------------------------------
# Scenarios
# ----------------------------------------------------------------------


async def scenario_happy_path() -> bool:
    """New email from a known vendor flows through all 10 steps."""
    header("Scenario 1: Happy path (new email, vendor resolved)")

    raw_email = build_graph_email()
    graph_api = make_graph_api_mock(raw_email)
    postgres = make_postgres_mock(is_new=True)
    s3 = make_s3_mock()
    sqs = make_sqs_mock()
    eventbridge = make_eventbridge_mock()
    salesforce = make_salesforce_mock(match=build_vendor_match())
    settings = build_test_settings()

    service = build_service(
        graph_api=graph_api,
        postgres=postgres,
        s3=s3,
        sqs=sqs,
        eventbridge=eventbridge,
        salesforce=salesforce,
        settings=settings,
    )

    result = await service.process_email(
        SAMPLE_MESSAGE_ID, correlation_id="smoke-happy-path"
    )

    all_passed = all(
        [
            check("Service returned a ParsedEmailPayload", result is not None),
            check(
                "query_id generated (VQ-YYYY-NNNN)",
                result is not None and result.query_id.startswith("VQ-"),
                detail=(result.query_id if result else ""),
            ),
            check(
                "Sender parsed from Graph payload",
                result is not None and result.sender_email == "rajesh.kumar@technova.com",
            ),
            check(
                "Vendor resolved to V-001",
                result is not None and result.vendor_id == "V-001",
            ),
            check(
                "vendor_match_method = exact_email",
                result is not None and result.vendor_match_method == "exact_email",
            ),
            check(
                "S3 raw email uploaded",
                s3.upload_file.await_count >= 1,
                detail=f"upload_file calls: {s3.upload_file.await_count}",
            ),
            check(
                "SQS message enqueued",
                sqs.send_message.await_count == 1,
            ),
            check(
                "EventBridge event published",
                eventbridge.publish_event.await_count == 1,
            ),
            check(
                "Idempotency claim acquired",
                postgres.check_idempotency.await_count == 1,
            ),
            check(
                "Happy path finalized claim (mark_complete called)",
                postgres.mark_idempotency_complete.await_count == 1,
            ),
            check(
                "Release NOT called (no failure)",
                postgres.release_idempotency_claim.await_count == 0,
            ),
            check(
                "Atomic DB writes via transaction()",
                postgres.transaction.call_count == 1,
            ),
            check(
                "Outbox row enqueued inside the transaction",
                postgres.enqueue_outbox.await_count == 1,
            ),
            check(
                "Outbox row marked sent after successful SQS publish",
                postgres.mark_outbox_sent.await_count == 1,
            ),
        ]
    )
    return all_passed


async def scenario_duplicate() -> bool:
    """Second call with same message_id returns None without side effects."""
    header("Scenario 2: Duplicate email (idempotency short-circuit)")

    raw_email = build_graph_email()
    graph_api = make_graph_api_mock(raw_email)
    postgres = make_postgres_mock(is_new=False)  # duplicate
    s3 = make_s3_mock()
    sqs = make_sqs_mock()
    eventbridge = make_eventbridge_mock()
    salesforce = make_salesforce_mock(match=build_vendor_match())
    settings = build_test_settings()

    service = build_service(
        graph_api=graph_api,
        postgres=postgres,
        s3=s3,
        sqs=sqs,
        eventbridge=eventbridge,
        salesforce=salesforce,
        settings=settings,
    )

    result = await service.process_email(
        SAMPLE_MESSAGE_ID, correlation_id="smoke-duplicate"
    )

    return all(
        [
            check("Returned None for duplicate", result is None),
            check(
                "Graph API was NOT called (short-circuited)",
                graph_api.fetch_email.await_count == 0,
            ),
            check("S3 was NOT called", s3.upload_file.await_count == 0),
            check("SQS was NOT called", sqs.send_message.await_count == 0),
            check(
                "EventBridge was NOT called",
                eventbridge.publish_event.await_count == 0,
            ),
        ]
    )


async def scenario_vendor_unresolved_but_domain_allowed() -> bool:
    """Unknown vendor but sender domain is allowlisted → email still processes."""
    header("Scenario 3: Vendor unresolved + domain allowlisted")

    raw_email = build_graph_email(sender_email="new.vendor@newvendor.io")
    graph_api = make_graph_api_mock(raw_email)
    postgres = make_postgres_mock(is_new=True)
    s3 = make_s3_mock()
    sqs = make_sqs_mock()
    eventbridge = make_eventbridge_mock()
    salesforce = make_salesforce_mock(match=None)
    settings = build_test_settings(allowed_domains=["newvendor.io"])

    service = build_service(
        graph_api=graph_api,
        postgres=postgres,
        s3=s3,
        sqs=sqs,
        eventbridge=eventbridge,
        salesforce=salesforce,
        settings=settings,
    )

    result = await service.process_email(
        SAMPLE_MESSAGE_ID, correlation_id="smoke-unresolved-allowlisted"
    )

    return all(
        [
            check("Service returned a payload", result is not None),
            check(
                "vendor_id is None (unresolved)",
                result is not None and result.vendor_id is None,
            ),
            check(
                "vendor_match_method = unresolved",
                result is not None and result.vendor_match_method == "unresolved",
            ),
            check(
                "SQS still enqueued (allowlist let it through)",
                sqs.send_message.await_count == 1,
            ),
        ]
    )


async def scenario_salesforce_raises() -> bool:
    """Salesforce exception is non-critical — pipeline continues."""
    header("Scenario 4: Salesforce raises an exception (non-critical)")

    raw_email = build_graph_email(sender_email="someone@newvendor.io")
    graph_api = make_graph_api_mock(raw_email)
    postgres = make_postgres_mock(is_new=True)
    s3 = make_s3_mock()
    sqs = make_sqs_mock()
    eventbridge = make_eventbridge_mock()
    salesforce = make_salesforce_mock(raise_error=True)
    # Allowlist the domain so the relevance filter still accepts the mail
    settings = build_test_settings(allowed_domains=["newvendor.io"])

    service = build_service(
        graph_api=graph_api,
        postgres=postgres,
        s3=s3,
        sqs=sqs,
        eventbridge=eventbridge,
        salesforce=salesforce,
        settings=settings,
    )

    result = await service.process_email(
        SAMPLE_MESSAGE_ID, correlation_id="smoke-sf-down"
    )

    return all(
        [
            check(
                "Service still returned a payload",
                result is not None,
            ),
            check(
                "vendor_id is None (Salesforce failure tolerated)",
                result is not None and result.vendor_id is None,
            ),
            check(
                "SQS still enqueued",
                sqs.send_message.await_count == 1,
            ),
        ]
    )


async def scenario_relevance_filter_rejects() -> bool:
    """Unknown sender + no allowlist match → filter rejects before SQS."""
    header("Scenario 5: Relevance filter rejects unknown sender")

    raw_email = build_graph_email(
        sender_email="stranger@randomdomain.xyz",
        subject="Hello",
        body_text="Hi",
    )
    graph_api = make_graph_api_mock(raw_email)
    postgres = make_postgres_mock(is_new=True)
    s3 = make_s3_mock()
    sqs = make_sqs_mock()
    eventbridge = make_eventbridge_mock()
    salesforce = make_salesforce_mock(match=None)
    # No allowlist so the sender gets rejected
    settings = build_test_settings(allowed_domains=[])

    service = build_service(
        graph_api=graph_api,
        postgres=postgres,
        s3=s3,
        sqs=sqs,
        eventbridge=eventbridge,
        salesforce=salesforce,
        settings=settings,
    )

    result = await service.process_email(
        SAMPLE_MESSAGE_ID, correlation_id="smoke-rejected"
    )

    return all(
        [
            check("Service returned None (rejected)", result is None),
            check("SQS was NOT called", sqs.send_message.await_count == 0),
            check(
                "EventBridge was NOT called",
                eventbridge.publish_event.await_count == 0,
            ),
            check(
                "S3 raw upload was NOT called (rejected before storage)",
                s3.upload_file.await_count == 0,
            ),
            check(
                "Auto-reply attempted via Graph /sendMail",
                graph_api.send_email.await_count == 1,
            ),
        ]
    )


async def scenario_fetch_failure_releases_claim() -> bool:
    """Graph API failure after claim → claim released so retry works."""
    header("Scenario 6: Fetch failure releases the idempotency claim")

    graph_api = AsyncMock()
    graph_api.fetch_email.side_effect = RuntimeError("Graph 503")
    postgres = make_postgres_mock(is_new=True)
    s3 = make_s3_mock()
    sqs = make_sqs_mock()
    eventbridge = make_eventbridge_mock()
    salesforce = make_salesforce_mock(match=build_vendor_match())
    settings = build_test_settings()

    service = build_service(
        graph_api=graph_api,
        postgres=postgres,
        s3=s3,
        sqs=sqs,
        eventbridge=eventbridge,
        salesforce=salesforce,
        settings=settings,
    )

    raised = False
    try:
        await service.process_email(
            SAMPLE_MESSAGE_ID, correlation_id="smoke-fetch-fail"
        )
    except RuntimeError:
        raised = True

    return all(
        [
            check("Pipeline raised the Graph error", raised),
            check(
                "Claim was released for retry",
                postgres.release_idempotency_claim.await_count == 1,
            ),
            check(
                "mark_idempotency_complete NOT called",
                postgres.mark_idempotency_complete.await_count == 0,
            ),
            check(
                "SQS was NOT called",
                sqs.send_message.await_count == 0,
            ),
        ]
    )


async def scenario_sqs_failure_keeps_outbox() -> bool:
    """SQS failure after DB commit → claim still completed, outbox has the row."""
    header("Scenario 7: SQS failure is recoverable via outbox")

    raw_email = build_graph_email()
    graph_api = make_graph_api_mock(raw_email)
    postgres = make_postgres_mock(is_new=True)
    s3 = make_s3_mock()
    sqs = make_sqs_mock()
    sqs.send_message.side_effect = RuntimeError("SQS throttled")
    eventbridge = make_eventbridge_mock()
    salesforce = make_salesforce_mock(match=build_vendor_match())
    settings = build_test_settings()

    service = build_service(
        graph_api=graph_api,
        postgres=postgres,
        s3=s3,
        sqs=sqs,
        eventbridge=eventbridge,
        salesforce=salesforce,
        settings=settings,
    )

    result = await service.process_email(
        SAMPLE_MESSAGE_ID, correlation_id="smoke-sqs-fail"
    )

    return all(
        [
            check("Pipeline still returned a payload", result is not None),
            check(
                "Outbox enqueue happened (durable via DB txn)",
                postgres.enqueue_outbox.await_count == 1,
            ),
            check(
                "SQS failure recorded on outbox row",
                postgres.record_outbox_failure.await_count == 1,
            ),
            check(
                "Outbox row NOT marked sent (drainer will retry)",
                postgres.mark_outbox_sent.await_count == 0,
            ),
            check(
                "Claim still finalized COMPLETED",
                postgres.mark_idempotency_complete.await_count == 1,
            ),
            check(
                "Release NOT called (data is durable)",
                postgres.release_idempotency_claim.await_count == 0,
            ),
        ]
    )


# ----------------------------------------------------------------------
# Runner
# ----------------------------------------------------------------------


async def main() -> int:
    scenarios: list[tuple[str, Any]] = [
        ("Happy path", scenario_happy_path),
        ("Duplicate", scenario_duplicate),
        ("Vendor unresolved + allowlist", scenario_vendor_unresolved_but_domain_allowed),
        ("Salesforce raises", scenario_salesforce_raises),
        ("Relevance filter rejects", scenario_relevance_filter_rejects),
        ("Fetch failure releases claim", scenario_fetch_failure_releases_claim),
        ("SQS failure recoverable via outbox", scenario_sqs_failure_keeps_outbox),
    ]

    header("EMAIL INTAKE SERVICE — OFFLINE SMOKE TEST")
    print(f"  Running {len(scenarios)} scenarios with mocked connectors.\n")
    print("  No external services are contacted.")

    results: list[tuple[str, bool]] = []
    for name, fn in scenarios:
        try:
            passed = await fn()
        except Exception as exc:
            print(f"  [FAIL]  Scenario '{name}' raised: {type(exc).__name__}: {exc}")
            passed = False
        results.append((name, passed))

    header("SUMMARY")
    total = len(results)
    passed_count = sum(1 for _, p in results if p)
    width = max(len(name) for name, _ in results)
    for name, passed in results:
        marker = "PASS" if passed else "FAIL"
        print(f"  {marker}  {name.ljust(width)}")
    print(f"\n  {passed_count} / {total} scenarios passed\n")

    return 0 if passed_count == total else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
