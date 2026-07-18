"""
AI video analysis schemas (stored in the ``analysis`` Firestore collection).
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


AnalysisStatus = Literal["processing", "completed", "failed"]


class AnalysisResponse(BaseModel):
    """Analysis document linked to a submission."""

    id: str
    submission_id: str
    student_id: str
    status: AnalysisStatus
    evaluation_criteria: Optional[str] = None
    checklist: Optional[str] = None
    report: Optional[str] = None
    analyzed_at: Optional[datetime] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class AnalysisSummary(BaseModel):
    """Embedded summary returned on a submission when analysis is complete."""

    id: str
    checklist: str
    report: str
    analyzed_at: datetime


class AnalysisReportResponse(BaseModel):
    """Markdown analysis report for a completed submission."""

    analysis_id: str
    submission_id: str
    status: AnalysisStatus
    checklist: str
    report: str
    analyzed_at: datetime
