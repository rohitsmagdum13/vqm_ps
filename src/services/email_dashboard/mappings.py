"""Module: services/email_dashboard/mappings.py

Status, priority, and formatting mappings for the email dashboard.

Pure functions and constants — no side effects, no database access.
Maps internal DB values to user-facing dashboard display values.
"""

from __future__ import annotations

from datetime import datetime

# --- Status Mapping ---
# DB stores UPPERCASE workflow statuses. Dashboard shows 3 categories.

STATUS_MAP: dict[str, str] = {
    "RECEIVED": "New",
    "ANALYZING": "New",
    "ROUTING": "New",
    "DRAFTING": "New",
    "VALIDATING": "New",
    "SENDING": "New",
    "AWAITING_HUMAN_REVIEW": "New",
    "AWAITING_TEAM_RESOLUTION": "New",
    "FAILED": "New",
    "DRAFT_REJECTED": "New",
    "REOPENED": "Reopened",
    "RESOLVED": "Resolved",
    "CLOSED": "Resolved",
}

# Reverse map: dashboard status → list of DB statuses for SQL IN clauses
STATUS_FILTER_MAP: dict[str, list[str]] = {
    "New": [
        "RECEIVED", "ANALYZING", "ROUTING", "DRAFTING", "VALIDATING",
        "SENDING", "AWAITING_HUMAN_REVIEW", "AWAITING_TEAM_RESOLUTION",
        "FAILED", "DRAFT_REJECTED",
    ],
    "Reopened": ["REOPENED"],
    "Resolved": ["RESOLVED", "CLOSED"],
}

# All "New" statuses as a SQL-safe tuple string for the stats query
NEW_STATUSES_SQL = (
    "'RECEIVED','ANALYZING','ROUTING','DRAFTING','VALIDATING',"
    "'SENDING','AWAITING_HUMAN_REVIEW','AWAITING_TEAM_RESOLUTION',"
    "'FAILED','DRAFT_REJECTED'"
)

# --- Priority Mapping ---
# routing_decision.priority → dashboard display string

PRIORITY_MAP: dict[str, str] = {
    "critical": "Critical",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
}


class DashboardMapper:
    """Maps internal DB values to dashboard display values.

    Stateless — all methods are static. Grouped as a class for
    namespacing and to follow the project's class-based convention.
    """

    @staticmethod
    def map_status(db_status: str | None) -> str:
        """Map a DB workflow status to a dashboard display status.

        Unmapped or NULL → 'New' (safe default for unknown states).
        """
        if not db_status:
            return "New"
        return STATUS_MAP.get(db_status, "New")

    @staticmethod
    def map_priority(db_priority: str | None) -> str:
        """Map a DB routing priority to a dashboard display priority.

        Unmapped or NULL → 'Medium' (safe default when routing hasn't run).
        """
        if not db_priority:
            return "Medium"
        return PRIORITY_MAP.get(db_priority.lower(), "Medium")

    @staticmethod
    def file_format(filename: str) -> str:
        """Extract the uppercase file extension from a filename.

        'invoice.pdf' → 'PDF', 'report.xlsx' → 'XLSX'.
        No extension → 'UNKNOWN'.
        """
        if "." not in filename:
            return "UNKNOWN"
        ext = filename.rsplit(".", 1)[-1]
        return ext.upper() if ext else "UNKNOWN"

    @staticmethod
    def format_timestamp(dt: datetime | None) -> str:
        """Format a datetime as ISO 8601 string.

        DB stores naive datetimes in IST (per CLAUDE.md convention).
        Returns empty string for None values.
        """
        if dt is None:
            return ""
        return dt.isoformat()
