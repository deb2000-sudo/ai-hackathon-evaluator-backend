"""
Theme schemas (stored in the ``themes`` Firestore collection).

Admins create reusable themes (name + description), then attach one or more
theme ids to a hackathon. Students pick a theme from that hackathon's list
when submitting.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ThemeCreateRequest(BaseModel):
    """Payload for creating a theme."""

    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=5000)


class ThemeUpdateRequest(BaseModel):
    """Partial update payload for a theme."""

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, min_length=1, max_length=5000)


class ThemeResponse(BaseModel):
    """A theme returned to clients."""

    id: str
    name: str
    description: str
    created_by: str
    created_at: datetime
    updated_at: datetime


class ThemeSummary(BaseModel):
    """Compact theme info embedded on hackathon / submission responses."""

    id: str
    name: str
    description: str
