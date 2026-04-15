"""Module: utils/helpers.py

Utility helpers for VQMS.

Provides IST timezone handling, unique ID generation, and
other shared utility functions used across the codebase.

Usage:
    from utils.helpers import TimeHelper, IdGenerator

    now = TimeHelper.ist_now()
    query_id = IdGenerator.generate_query_id()
    correlation_id = IdGenerator.generate_correlation_id()
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

# IST is UTC+5:30 — using timedelta instead of ZoneInfo
# because Windows may not have the tzdata package installed
_IST_OFFSET = timedelta(hours=5, minutes=30)
_IST = timezone(_IST_OFFSET)


class TimeHelper:
    """IST timezone utilities.

    All timestamps in VQMS use IST (Indian Standard Time, UTC+5:30).
    PostgreSQL TIMESTAMP columns store naive datetimes in IST.
    """

    @staticmethod
    def ist_now() -> datetime:
        """Return the current time in IST as a naive datetime.

        Returns a naive datetime (no tzinfo) because PostgreSQL
        TIMESTAMP columns store naive datetimes. The convention
        is that all naive datetimes in the system are in IST.
        """
        return datetime.now(_IST).replace(tzinfo=None)

    @staticmethod
    def ist_now_offset(*, hours: int = 0) -> datetime:
        """Return IST now plus the given number of hours.

        Used for calculating SLA deadlines based on priority.
        """
        return TimeHelper.ist_now() + timedelta(hours=hours)


class IdGenerator:
    """Unique ID generation for VQMS entities.

    Query IDs follow the format VQ-{year}-{4-digit-sequence}.
    Correlation IDs and execution IDs are UUID v4 strings.
    """

    @staticmethod
    def generate_query_id(prefix: str = "VQ") -> str:
        """Generate a unique query ID in the format VQ-2026-XXXX.

        Uses the last 4 digits of a UUID to create the sequence number.
        This is a simple approach for development. In production, this
        will use a PostgreSQL sequence for guaranteed uniqueness.

        TODO: Replace UUID-based sequence with DB-backed counter in Phase 2
        """
        year = TimeHelper.ist_now().year
        # Use last 4 hex digits of UUID, converted to a 4-digit number
        sequence = int(uuid.uuid4().hex[-4:], 16) % 10000
        return f"{prefix}-{year}-{sequence:04d}"

    @staticmethod
    def generate_correlation_id() -> str:
        """Generate a UUID v4 correlation ID for request tracing.

        This ID follows the request through every service call,
        database write, and external API request in the pipeline.
        """
        return str(uuid.uuid4())

    @staticmethod
    def generate_execution_id() -> str:
        """Generate a UUID v4 execution ID for a pipeline run.

        Each time the LangGraph pipeline processes a query,
        it gets a unique execution ID for tracking that specific run.
        """
        return str(uuid.uuid4())
