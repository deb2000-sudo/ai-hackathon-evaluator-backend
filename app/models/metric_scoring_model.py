"""
Metric-scoring schemas for AI + manual scorecards.

Stored in ``ai_evaluation_metric_scoring``. Each metric can be scored by AI
(``scoring_mode=ai``) or by the evaluator (``scoring_mode=manual``), with
optional nested segments (e.g. MVP feature checklist, GitHub visibility).
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.string_utils import strip_optional, strip_required


ScoringMode = Literal["ai", "manual"]
SegmentKind = Literal["score", "boolean", "enum"]

# Metrics that need not exist as student form fields (video is analyzed from GCS).
SYNTHETIC_METRIC_KEYS: frozenset[str] = frozenset(
    {
        "video_explanation",
        "video",
    }
)

DEFAULT_METRIC_COLORS: dict[str, str] = {
    "problem_statement": "#2563EB",
    "solution_description": "#7C3AED",
    "video_explanation": "#DB2777",
    "video": "#DB2777",
    "github_link": "#059669",
    "project_github_link": "#059669",
    "mvp_link": "#D97706",
}


class MetricSegment(BaseModel):
    """Nested rubric item under a metric (manual checklists / enums)."""

    key: str = Field(..., min_length=1, max_length=100)
    label: str = Field(..., min_length=1, max_length=200)
    kind: SegmentKind = "score"
    max_score: float = Field(
        0,
        ge=0,
        le=100,
        description="For boolean: marks when true. For score: max. For enum: usually 0.",
    )
    options: Optional[list[str]] = Field(
        None,
        description='For kind=enum, e.g. ["public", "private"].',
    )
    description: Optional[str] = Field(
        None,
        max_length=2000,
        description="UI guidance for the evaluator (e.g. fullstack = 20 marks).",
    )
    scoring_prompt: Optional[str] = Field(
        None,
        max_length=5000,
        description="Optional AI sub-rubric (rarely used for manual segments).",
    )

    @field_validator("key", "label", mode="before")
    @classmethod
    def normalize_required(cls, value: str) -> str:
        return strip_required(value)

    @field_validator("description", "scoring_prompt", mode="before")
    @classmethod
    def normalize_optional(cls, value: Optional[str]) -> Optional[str]:
        return strip_optional(value)

    @model_validator(mode="after")
    def validate_kind_shape(self) -> "MetricSegment":
        if self.kind == "enum":
            if not self.options or len(self.options) < 2:
                raise ValueError("enum segments require at least two options")
        if self.kind == "boolean" and self.max_score <= 0:
            raise ValueError("boolean segments need max_score > 0 (marks when present)")
        return self


class FieldScoringMetric(BaseModel):
    """One scorecard metric (AI or manual) for the linked evaluation requirement."""

    field_key: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description=(
            "Requirement field key, or a synthetic key such as "
            "video_explanation for demo-video scoring."
        ),
    )
    field_label: Optional[str] = Field(
        None,
        description="Display label (auto-filled from requirement when applicable).",
    )
    scoring_mode: ScoringMode = Field(
        "ai",
        description="ai = Gemini scores this metric; manual = evaluator fills it.",
    )
    scoring_prompt: Optional[str] = Field(
        None,
        max_length=20000,
        description="Required for AI metrics — full rubric text for Gemini.",
    )
    max_score: float = Field(10, gt=0, le=100)
    weight: Optional[float] = Field(
        None,
        ge=0,
        le=100,
        description="Percentage weight toward the 0–100 total (e.g. 15 for 15%).",
    )
    color: Optional[str] = Field(
        None,
        max_length=32,
        description="Hex color for scorecard segments, e.g. #2563EB.",
    )
    segments: Optional[list[MetricSegment]] = Field(
        None,
        description="Nested manual/AI sub-fields (GitHub visibility, MVP checklist, …).",
    )

    @field_validator("field_key", mode="before")
    @classmethod
    def normalize_field_key(cls, value: str) -> str:
        return strip_required(value)

    @field_validator("field_label", "scoring_prompt", "color", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: Optional[str]) -> Optional[str]:
        return strip_optional(value)

    @model_validator(mode="after")
    def validate_mode_and_segments(self) -> "FieldScoringMetric":
        if self.scoring_mode == "ai":
            if not (self.scoring_prompt or "").strip():
                raise ValueError(
                    f"scoring_prompt is required for AI metric '{self.field_key}'"
                )
        if self.segments:
            keys = [s.key for s in self.segments]
            if len(keys) != len(set(keys)):
                raise ValueError(
                    f"Duplicate segment keys under metric '{self.field_key}'"
                )
        if not self.color:
            self.color = DEFAULT_METRIC_COLORS.get(self.field_key)
        return self


class MetricScoringCreateRequest(BaseModel):
    """Payload for creating a metric-scoring / scorecard config."""

    evaluation_requirement_id: str = Field(..., min_length=1)
    name: Optional[str] = Field(None, max_length=200)
    metrics: list[FieldScoringMetric] = Field(..., min_length=1)

    @field_validator("evaluation_requirement_id", mode="before")
    @classmethod
    def normalize_requirement_id(cls, value: str) -> str:
        return strip_required(value)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: Optional[str]) -> Optional[str]:
        return strip_optional(value)

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

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: Optional[str]) -> Optional[str]:
        return strip_optional(value)

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
