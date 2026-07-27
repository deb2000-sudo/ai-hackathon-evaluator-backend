"""
AI evaluation metric-scoring schemas.

A metric-scoring document is linked to a single evaluation requirement and
defines, per field of that requirement (e.g. Problem Statement, Solution
Description, GitHub link, MVP link), a natural-language scoring prompt the AI
uses to score a student's answer. Stored in the ``ai_evaluation_metric_scoring``
Firestore collection.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class FieldScoringMetric(BaseModel):
    """Scoring definition for one field of the linked evaluation requirement."""

    field_key: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Must match a field key in the linked evaluation requirement.",
    )
    field_label: Optional[str] = Field(
        None,
        description="Snapshot of the field label (auto-filled from the requirement).",
    )
    scoring_prompt: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Natural-language instructions telling the AI how to score this field.",
    )
    max_score: float = Field(10, gt=0, le=100)
    weight: Optional[float] = Field(None, ge=0)


class MetricScoringCreateRequest(BaseModel):
    """Payload for creating a metric-scoring config for an evaluation requirement."""

    evaluation_requirement_id: str = Field(..., min_length=1)
    name: Optional[str] = Field(None, max_length=200)
    metrics: list[FieldScoringMetric] = Field(..., min_length=1)

    @field_validator("metrics")
    @classmethod
    def unique_field_keys(cls, value: list[FieldScoringMetric]) -> list[FieldScoringMetric]:
        keys = [m.field_key for m in value]
        if len(keys) != len(set(keys)):
            raise ValueError("Each field_key may only appear once in metrics")
        return value


class MetricScoringUpdateRequest(BaseModel):
    """Partial update payload for a metric-scoring config."""

    name: Optional[str] = Field(None, max_length=200)
    metrics: Optional[list[FieldScoringMetric]] = Field(None, min_length=1)

    @field_validator("metrics")
    @classmethod
    def unique_field_keys(
        cls, value: Optional[list[FieldScoringMetric]]
    ) -> Optional[list[FieldScoringMetric]]:
        if value is None:
            return None
        keys = [m.field_key for m in value]
        if len(keys) != len(set(keys)):
            raise ValueError("Each field_key may only appear once in metrics")
        return value


class MetricScoringResponse(BaseModel):
    """A metric-scoring config returned to clients."""

    id: str
    evaluation_requirement_id: str
    name: Optional[str] = None
    metrics: list[FieldScoringMetric]
    created_by: str
    created_at: datetime
    updated_at: datetime
