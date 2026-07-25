"""
Hackathon schemas (stored in the ``hackathons`` Firestore collection).
"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class TimelineRound(BaseModel):
    """A single stage in the hackathon timeline (e.g. Round 1, Round 2)."""

    title: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=2000)
    start_date: Optional[str] = None
    end_date: Optional[str] = None

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_iso_date(cls, value: Optional[str]) -> Optional[str]:
        if value is None or value == "":
            return None
        try:
            date.fromisoformat(value)
        except ValueError as e:
            raise ValueError("Dates must be ISO format (YYYY-MM-DD)") from e
        return value


class HackathonPrizes(BaseModel):
    """Prize breakdown for the top three positions."""

    winner: str = Field(..., min_length=1, max_length=500)
    first_runner_up: str = Field(..., min_length=1, max_length=500)
    second_runner_up: str = Field(..., min_length=1, max_length=500)


class HackathonCreateRequest(BaseModel):
    """Validated payload for creating a hackathon (banner handled separately)."""

    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=10000)
    start_date: str
    end_date: str
    guidelines: str = Field(..., min_length=1, max_length=10000)
    timeline: list[TimelineRound] = Field(default_factory=list)
    prizes: HackathonPrizes

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_iso_date(cls, value: str) -> str:
        try:
            date.fromisoformat(value)
        except ValueError as e:
            raise ValueError("start_date and end_date must be ISO format (YYYY-MM-DD)") from e
        return value

    @model_validator(mode="after")
    def validate_date_range(self) -> "HackathonCreateRequest":
        if date.fromisoformat(self.end_date) < date.fromisoformat(self.start_date):
            raise ValueError("end_date cannot be earlier than start_date")
        return self


class HackathonUpdateRequest(BaseModel):
    """Partial update payload for a hackathon (all fields optional)."""

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, min_length=1, max_length=10000)
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    guidelines: Optional[str] = Field(None, min_length=1, max_length=10000)
    timeline: Optional[list[TimelineRound]] = None
    prizes: Optional[HackathonPrizes] = None

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_iso_date(cls, value: Optional[str]) -> Optional[str]:
        if value is None or value == "":
            return None
        try:
            date.fromisoformat(value)
        except ValueError as e:
            raise ValueError("Dates must be ISO format (YYYY-MM-DD)") from e
        return value


class HackathonResponse(BaseModel):
    """Full hackathon document returned to clients."""

    id: str
    name: str
    description: str
    start_date: str
    end_date: str
    guidelines: str
    timeline: list[TimelineRound]
    prizes: HackathonPrizes
    banner_path: Optional[str] = Field(
        None,
        description="Internal gs:// path of the banner image (not browser-playable).",
    )
    banner_url: Optional[str] = Field(
        None,
        description="Time-limited HTTPS URL for the banner image.",
    )
    created_by: str
    created_at: datetime
    updated_at: datetime
