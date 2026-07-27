"""
Student hackathon submission schemas.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.models.analysis_model import AnalysisSummary


SubmissionStatus = Literal["uploaded", "processing", "completed", "failed"]


class HackathonSubmissionSummary(BaseModel):
    """One hackathon row for the admin Submissions tab."""

    hackathon_id: str
    name: str
    start_date: str
    end_date: str
    submission_count: int
    banner_url: Optional[str] = None


class SubmissionResponse(BaseModel):
    """Full submission document returned to clients."""

    id: str
    student_id: str
    hackathon_id: str
    hackathon_name: str
    team_name: str
    theme_id: str
    theme_name: str
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
    report_published: bool = Field(
        False,
        description="When true, students may view the AI analysis report.",
    )
    published_at: Optional[datetime] = None
    published_by: Optional[str] = None
    assigned_evaluator_id: Optional[str] = Field(
        None,
        description="Approved evaluator assigned to review this submission.",
    )
    assigned_evaluator_name: Optional[str] = None
    assigned_at: Optional[datetime] = None
    assigned_by: Optional[str] = None
    video_path: str
    video_url: Optional[str] = Field(
        None,
        description="Time-limited HTTPS URL for browser playback (not gs://).",
    )
    content_type: str
    source_filename: str
    analysis: Optional[AnalysisSummary] = Field(
        None,
        description=(
            "Joined analysis summary when completed. For students, only present "
            "after an admin publishes the report."
        ),
    )
    error: Optional[str] = None
    message: Optional[str] = Field(
        None,
        description="Optional user-facing message (e.g. after successful submit).",
    )
    created_at: datetime
    updated_at: datetime


class EvaluateSubmissionRequest(BaseModel):
    """Optional body when an admin starts AI analysis on a submission."""

    evaluation_criteria: Optional[str] = Field(
        None,
        max_length=2000,
        description="Optional extra focus areas appended to the analysis context (not required).",
    )


class PublishReportRequest(BaseModel):
    """Toggle whether students can see the analysis report."""

    publish: bool = Field(
        True,
        description="True to publish the report to the student; false to unpublish.",
    )


class AssignEvaluatorRequest(BaseModel):
    """Assign (or clear) a single submission's evaluator."""

    evaluator_id: Optional[str] = Field(
        None,
        description="Approved evaluator user id. Null to unassign.",
    )


class DivideEquallyRequest(BaseModel):
    """Divide selected submissions equally among approved evaluators (random)."""

    submission_ids: list[str] = Field(
        ...,
        min_length=1,
        description="Submission ids to assign (usually the selected table rows).",
    )
    evaluator_ids: Optional[list[str]] = Field(
        None,
        description=(
            "Optional subset of approved evaluator ids. "
            "If omitted, all approved (active) evaluators are used."
        ),
    )


class DivideEquallyResponse(BaseModel):
    """Result of a bulk equal-division assignment."""

    assigned_count: int
    evaluator_count: int
    submissions: list[SubmissionResponse]

