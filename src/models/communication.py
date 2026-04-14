"""Module: models/communication.py

Pydantic models for AI-generated email drafts and quality gate results.

The Resolution Agent (Path A) and Acknowledgment Agent (Path B)
produce DraftResponse objects. The Quality Gate validates every
draft before it is sent to the vendor.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DraftResponse(BaseModel):
    """AI-generated email draft for vendor communication.

    Path A: draft_type='RESOLUTION' — full answer with KB facts
    Path B: draft_type='ACKNOWLEDGMENT' — ticket confirmation only
    """

    model_config = ConfigDict(frozen=True)

    draft_type: Literal["RESOLUTION", "ACKNOWLEDGMENT"] = Field(
        description="RESOLUTION (Path A full answer) or ACKNOWLEDGMENT (Path B confirmation only)",
    )
    subject: str = Field(description="Email subject line for the response")
    body: str = Field(description="Full email body text")
    confidence: float = Field(ge=0.0, le=1.0, description="AI confidence in the draft quality")
    sources: list[str] = Field(default_factory=list, description="KB article IDs used as sources (Path A only)")
    model_id: str = Field(description="Model used to generate the draft")
    tokens_in: int = Field(description="Input token count for the draft generation")
    tokens_out: int = Field(description="Output token count for the draft generation")
    draft_duration_ms: int = Field(description="Time taken to generate the draft in milliseconds")


class QualityGateResult(BaseModel):
    """Result of the 7-check Quality Gate validation (Step 11).

    Every outbound email must pass the Quality Gate before
    being sent. If checks fail, the draft is regenerated
    (up to max_redrafts times) before routing to human review.
    """

    model_config = ConfigDict(frozen=True)

    passed: bool = Field(description="True if all required checks passed")
    checks_run: int = Field(description="Total number of checks executed")
    checks_passed: int = Field(description="Number of checks that passed")
    failed_checks: list[str] = Field(default_factory=list, description="Names of checks that failed")
    redraft_count: int = Field(default=0, description="How many times the draft was regenerated")
    max_redrafts: int = Field(default=2, description="Maximum allowed regeneration attempts")
