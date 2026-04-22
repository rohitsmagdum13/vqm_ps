"""Module: models/ticket.py

Pydantic models for ServiceNow ticket operations, routing decisions, and SLA targets.

Tickets are created in ServiceNow at Step 12 (Delivery).
Path A tickets are for team monitoring; Path B tickets
require active team investigation.

The Routing Node (Step 9A) uses deterministic rules to assign
a team, set SLA targets, and determine priority based on
vendor tier, urgency, and confidence.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ServiceNow returns incident numbers like "INC0010001" (no hyphen,
# 7+ digits). Earlier VQMS fixtures used "INC-XXXXXXX" (hyphenated)
# so the validator accepts both forms for backward compatibility.
_TICKET_ID_PATTERN = re.compile(r"^INC-?\d{7,}$")


class TicketCreateRequest(BaseModel):
    """Request payload for creating a ServiceNow incident ticket.

    Sent to the ServiceNow connector at Step 12.
    """

    model_config = ConfigDict(frozen=True)

    query_id: str = Field(description="VQMS query ID (VQ-2026-XXXX)")
    correlation_id: str = Field(description="UUID v4 tracing ID")
    subject: str = Field(description="Ticket short description")
    description: str = Field(description="Ticket long description with context")
    priority: str = Field(description="ServiceNow priority (1-Critical, 2-High, 3-Medium, 4-Low)")
    assigned_team: str = Field(description="Assignment group in ServiceNow")
    vendor_id: str | None = Field(default=None, description="Vendor ID for context")
    vendor_name: str | None = Field(default=None, description="Vendor name for context")
    category: str = Field(description="Ticket category")
    sla_hours: int = Field(description="SLA target in hours")


class TicketInfo(BaseModel):
    """ServiceNow ticket information returned after creation.

    The ticket_id is the ServiceNow incident number — either the
    real ServiceNow form (INC0010001, no hyphen, 7+ digits) or the
    legacy hyphenated form used by older fixtures (INC-0010001).
    Both are included in outbound emails to the vendor as-is.
    """

    model_config = ConfigDict(frozen=True)

    ticket_id: str = Field(
        description="ServiceNow incident number (e.g. INC0010001 or INC-0010001)",
    )
    query_id: str = Field(description="VQMS query ID this ticket belongs to")
    status: str = Field(description="Ticket status (New, In Progress, Resolved, Closed)")
    created_at: datetime = Field(description="When the ticket was created (IST)")
    assigned_team: str = Field(description="Team assigned to the ticket")
    sla_deadline: datetime = Field(description="When the SLA expires (IST)")

    @field_validator("ticket_id")
    @classmethod
    def validate_ticket_id_format(cls, v: str) -> str:
        """Ticket ID must be INC followed by 7+ digits, optional hyphen.

        ServiceNow-native form: "INC0010001" (no hyphen, 10 chars total).
        Legacy VQMS test-fixture form: "INC-0010001" (hyphen, 11 chars).
        Both accepted — the hyphen is tolerated so older tests still pass
        while real ServiceNow responses also validate.
        """
        if not _TICKET_ID_PATTERN.match(v):
            msg = (
                "Ticket ID must be 'INC' followed by 7+ digits "
                "(e.g. 'INC0010001'); a hyphen after INC is tolerated"
            )
            raise ValueError(msg)
        return v


class SLATarget(BaseModel):
    """SLA timing configuration for a specific query.

    Calculated based on vendor tier + urgency combination.
    Escalation thresholds determine when warnings and
    escalation events fire.
    """

    model_config = ConfigDict(frozen=True)

    total_hours: int = Field(description="Total SLA window in hours")
    warning_at_percent: int = Field(default=70, description="Percentage of SLA when warning fires")
    l1_escalation_at_percent: int = Field(default=85, description="Percentage of SLA for L1 escalation")
    l2_escalation_at_percent: int = Field(default=95, description="Percentage of SLA for L2 escalation")


class RoutingDecision(BaseModel):
    """Output from the Routing Node (Step 9A).

    Deterministic rules engine output that determines which
    team handles the query, the SLA target, and whether
    human investigation is required.
    """

    model_config = ConfigDict(frozen=True)

    assigned_team: str = Field(description="Team assigned to handle this query")
    sla_target: SLATarget = Field(description="SLA timing for this query")
    category: str = Field(description="Query category for routing")
    priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = Field(description="Final priority after rules evaluation")
    routing_reason: str = Field(description="Human-readable explanation of routing decision")
    requires_human_investigation: bool = Field(
        default=False,
        description="True for Path B — team must investigate, not just monitor",
    )
