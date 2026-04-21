"""Module: models/sla.py

Pydantic models for Phase 6 SLA monitoring.

SlaCheckpoint mirrors the workflow.sla_checkpoints table row and
is used by the SlaMonitor to track live SLA state per query.

SlaThresholdCrossed enumerates which threshold (if any) was crossed
on a single monitor tick. The monitor uses this to decide which
EventBridge event to publish and which idempotency flag to flip.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class SlaThresholdCrossed(str, Enum):
    """Which SLA threshold was crossed on this check.

    The monitor publishes one event per threshold crossing.
    NONE means the row was checked but no new threshold was crossed
    (either the deadline is still far, or the threshold was already fired).
    """

    NONE = "NONE"
    WARNING = "WARNING"
    L1 = "L1"
    L2 = "L2"


class SlaCheckpoint(BaseModel):
    """Live SLA state for a single query.

    Mirrors workflow.sla_checkpoints. The _fired booleans are idempotency
    guards: once flipped to True the monitor never republishes that event.
    """

    model_config = ConfigDict(frozen=True)

    query_id: str = Field(description="Query identifier (VQ-YYYY-NNNN)")
    correlation_id: str = Field(description="Correlation ID for tracing")
    sla_started_at: datetime = Field(description="When the SLA clock started (IST)")
    sla_deadline: datetime = Field(description="When the SLA expires (IST)")
    sla_target_hours: int = Field(ge=1, description="Target resolution window in hours")
    warning_fired: bool = Field(default=False, description="True once SLAWarning70 was published")
    l1_fired: bool = Field(default=False, description="True once SLAEscalation85 was published")
    l2_fired: bool = Field(default=False, description="True once SLAEscalation95 was published")
    last_checked_at: datetime | None = Field(
        default=None, description="When the monitor last scanned this row"
    )
    last_status: str = Field(
        default="ACTIVE",
        description="ACTIVE | RESOLVED | CLOSED — monitor skips anything not ACTIVE",
    )
