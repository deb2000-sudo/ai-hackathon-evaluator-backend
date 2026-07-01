"""
Hackathon video evaluation schemas.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


EvaluationStatus = Literal["uploaded", "processing", "completed", "failed"]


class CriteriaScores(BaseModel):
    """Per-criterion scores (each out of 10)."""

    problem_coverage: float
    solution_demonstration: float
    technical_execution: float
    presentation: float
    impact: float


class EvaluationResult(BaseModel):
    """AI-generated evaluation of a hackathon submission video."""

    overall_score: float  # 0-100
    criteria: CriteriaScores
    summary: str
    strengths: list[str]
    improvements: list[str]
    recommendation: str
    # The "Product & Feature Validation Checklist" generated from the problem +
    # solution (null when those inputs were not supplied).
    checklist: Optional[str] = None
    # A longer, human-readable markdown analysis of the video vs. the checklist.
    report: Optional[str] = None


class UploadVideoResponse(BaseModel):
    """Response returned after a submission video is uploaded."""

    id: str
    user_id: str
    status: EvaluationStatus
    video_path: str
    source_filename: str
    created_at: datetime
    updated_at: datetime


class AnalyzeVideoRequest(BaseModel):
    """Request body to kick off analysis of a previously uploaded video."""

    session_id: str = Field(..., min_length=1)
    # What the project is meant to solve. When both problem_statement and
    # solution_description are given, a validation checklist is generated and
    # the video is judged against it (mirrors the VideoAnalyzer prototype).
    problem_statement: Optional[str] = Field(None, max_length=5000)
    solution_description: Optional[str] = Field(None, max_length=5000)
    # Optional freeform rubric / focus areas, used when problem+solution are
    # not provided (or in addition to them).
    criteria: Optional[str] = Field(None, max_length=2000)


class EvaluationSessionResponse(BaseModel):
    """Full evaluation session, used for polling and results."""

    id: str
    user_id: str
    status: EvaluationStatus
    video_path: str
    source_filename: Optional[str] = None
    problem_statement: Optional[str] = None
    solution_description: Optional[str] = None
    criteria: Optional[str] = None
    result: Optional[EvaluationResult] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
