"""
Student hackathon submission schemas.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.models.analysis_model import AnalysisSummary
from app.models.user_model import ThemeChosen


SubmissionStatus = Literal["uploaded", "processing", "completed", "failed"]


class SubmissionResponse(BaseModel):
    """Full submission document returned to clients."""

    id: str
    student_id: str
    team_name: str
    theme_chosen: ThemeChosen
    problem_statement: str
    solution_description: str
    evaluation_criteria: Optional[str] = Field(
        None,
        description="Optional extra focus supplied when starting AI analysis.",
    )
    status: SubmissionStatus
    analysis_id: Optional[str] = Field(
        None,
        description="Firestore document id in the analysis collection.",
    )
    video_path: str
    video_url: Optional[str] = Field(
        None,
        description="Time-limited HTTPS URL for browser playback (not gs://).",
    )
    content_type: str
    source_filename: str
    analysis: Optional[AnalysisSummary] = Field(
        None,
        description="Joined analysis summary when status is completed.",
    )
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class EvaluateSubmissionRequest(BaseModel):
    """Optional body when starting AI analysis on an existing submission."""

    evaluation_criteria: Optional[str] = Field(
        None,
        max_length=2000,
        description="Optional extra focus areas appended to the analysis context (not required).",
    )
