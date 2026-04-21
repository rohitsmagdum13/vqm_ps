"""Tests for the Phase 6 EpisodicMemoryWriter.

Covers:
- save_closure writes a row with vendor_id, intent, resolution_path, outcome
- save_closure returns None when no case_execution row exists
- save_closure returns None on DB write failure (non-critical)
- _build_summary produces the right path label for A / B / C / unknown
- _safe_dict unwraps dict / str / bytes / None inputs defensively
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from config.settings import Settings
from services.episodic_memory import EpisodicMemoryWriter


@pytest.fixture
def phase6_settings() -> Settings:
    """Minimal Settings for episodic memory tests."""
    return Settings(
        app_env="test",
        aws_region="us-east-1",
        graph_api_tenant_id="t",
        graph_api_client_id="c",
        graph_api_client_secret="s",
        graph_api_mailbox="m@co.com",
        salesforce_instance_url="https://sf.test",
        salesforce_username="u",
        salesforce_password="p",
        salesforce_security_token="tk",
        servicenow_instance_url="https://snow.test",
        servicenow_username="u",
        servicenow_password="p",
        postgres_host="localhost",
        postgres_port=5432,
        postgres_db="vqms_test",
        postgres_user="u",
        postgres_password="p",
    )


@pytest.fixture
def writer(
    mock_postgres: AsyncMock, phase6_settings: Settings
) -> EpisodicMemoryWriter:
    return EpisodicMemoryWriter(
        postgres=mock_postgres, settings=phase6_settings
    )


# ---------------------------------------------------------------------------
# save_closure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_closure_writes_row_with_expected_fields(
    writer: EpisodicMemoryWriter, mock_postgres: AsyncMock
) -> None:
    """A closed Path A case produces an INSERT with the right columns."""
    mock_postgres.fetchrow.return_value = {
        "query_id": "VQ-2026-0001",
        "vendor_id": "V-001",
        "processing_path": "A",
        "analysis_result": {"intent_classification": "invoice_discrepancy"},
        "created_at": None,
    }

    memory_id = await writer.save_closure(
        query_id="VQ-2026-0001",
        correlation_id="corr-1",
        reason="VENDOR_CONFIRMED",
    )

    assert memory_id is not None
    assert memory_id.startswith("MEM-")

    mock_postgres.execute.assert_awaited_once()
    sql, *args = mock_postgres.execute.await_args.args
    assert "INSERT INTO memory.episodic_memory" in sql
    # Positional mapping: memory_id, vendor_id, query_id, intent,
    # resolution_path, outcome, resolved_at, summary, created_at
    assert args[0] == memory_id
    assert args[1] == "V-001"
    assert args[2] == "VQ-2026-0001"
    assert args[3] == "invoice_discrepancy"
    assert args[4] == "A"
    assert args[5] == "VENDOR_CONFIRMED"
    assert "AI-resolved" in args[7]
    assert "invoice_discrepancy" in args[7]


@pytest.mark.asyncio
async def test_save_closure_returns_none_when_no_case_row(
    writer: EpisodicMemoryWriter, mock_postgres: AsyncMock
) -> None:
    """Missing case_execution row → return None, don't INSERT."""
    mock_postgres.fetchrow.return_value = None

    memory_id = await writer.save_closure(
        query_id="VQ-MISSING", correlation_id="corr-1"
    )

    assert memory_id is None
    mock_postgres.execute.assert_not_called()


@pytest.mark.asyncio
async def test_save_closure_returns_none_when_case_fetch_fails(
    writer: EpisodicMemoryWriter, mock_postgres: AsyncMock
) -> None:
    """DB fetch raises → return None, don't INSERT."""
    mock_postgres.fetchrow.side_effect = RuntimeError("db down")

    memory_id = await writer.save_closure(
        query_id="VQ-2026-0001", correlation_id="corr-1"
    )

    assert memory_id is None
    mock_postgres.execute.assert_not_called()


@pytest.mark.asyncio
async def test_save_closure_returns_none_when_insert_fails(
    writer: EpisodicMemoryWriter, mock_postgres: AsyncMock
) -> None:
    """DB INSERT raises → return None (non-critical, closure still succeeded)."""
    mock_postgres.fetchrow.return_value = {
        "query_id": "VQ-2026-0001",
        "vendor_id": "V-001",
        "processing_path": "A",
        "analysis_result": None,
        "created_at": None,
    }
    mock_postgres.execute.side_effect = RuntimeError("insert failed")

    memory_id = await writer.save_closure(
        query_id="VQ-2026-0001", correlation_id="corr-1"
    )

    assert memory_id is None


@pytest.mark.asyncio
async def test_save_closure_uses_unknown_defaults_when_fields_missing(
    writer: EpisodicMemoryWriter, mock_postgres: AsyncMock
) -> None:
    """Missing vendor_id / intent / path fall back to safe defaults."""
    mock_postgres.fetchrow.return_value = {
        "query_id": "VQ-2026-0099",
        "vendor_id": None,
        "processing_path": None,
        "analysis_result": None,
        "created_at": None,
    }

    await writer.save_closure(
        query_id="VQ-2026-0099", correlation_id="corr-1"
    )

    args = mock_postgres.execute.await_args.args
    # vendor_id defaults to "UNKNOWN"
    assert args[2] == "UNKNOWN"
    # intent defaults to "general_inquiry"
    assert args[4] == "general_inquiry"
    # path defaults to "A"
    assert args[5] == "A"


# ---------------------------------------------------------------------------
# _build_summary — path label lookup
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "processing_path, expected_label",
    [
        ("A", "AI-resolved"),
        ("B", "team-resolved"),
        ("C", "human-reviewed"),
        ("Z", "resolved"),  # Unknown path falls back to "resolved"
    ],
)
def test_build_summary_path_label(
    processing_path: str, expected_label: str
) -> None:
    """The path label in the summary string matches the processing path."""
    summary = EpisodicMemoryWriter._build_summary(
        vendor_id="V-001",
        intent="invoice_discrepancy",
        processing_path=processing_path,
        reason="VENDOR_CONFIRMED",
    )
    assert expected_label in summary
    assert "V-001" in summary
    assert "invoice_discrepancy" in summary
    assert "VENDOR_CONFIRMED" in summary


# ---------------------------------------------------------------------------
# _safe_dict — defensive JSON handling
# ---------------------------------------------------------------------------


def test_safe_dict_none_returns_empty() -> None:
    assert EpisodicMemoryWriter._safe_dict(None) == {}


def test_safe_dict_dict_passes_through() -> None:
    assert EpisodicMemoryWriter._safe_dict({"k": "v"}) == {"k": "v"}


def test_safe_dict_json_string_parses() -> None:
    assert EpisodicMemoryWriter._safe_dict('{"k": "v"}') == {"k": "v"}


def test_safe_dict_json_bytes_parses() -> None:
    assert EpisodicMemoryWriter._safe_dict(b'{"k": "v"}') == {"k": "v"}


def test_safe_dict_invalid_string_returns_empty() -> None:
    assert EpisodicMemoryWriter._safe_dict("not-json") == {}


def test_safe_dict_unexpected_type_returns_empty() -> None:
    assert EpisodicMemoryWriter._safe_dict(42) == {}
