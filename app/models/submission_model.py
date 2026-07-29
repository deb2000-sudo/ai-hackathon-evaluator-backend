"""
Student hackathon submission schemas.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.models.analysis_model import AnalysisSummary
from app.models.string_utils import strip_optional, strip_required


SubmissionStatus = Literal["uploaded", "processing", "completed", "failed"]
ReviewStatus = Literal["none", "pending_review", "approved", "changes_requested"]
VideoSource = Literal["recorded", "uploaded"]


class HackathonSubmissionSummary(BaseModel):
    """One hackathon row for the admin/evaluator Submissions tab."""

    hackathon_id: str
    name: str
    start_date: str
    end_date: str
    submission_count: int
    banner_url: Optional[str] = None


class AcceptedVideoTypesResponse(BaseModel):
    """Constraints for Record demo vs Upload from disk pickers."""

    allowed_mime_types: list[str]
    allowed_extensions: list[str]
    file_input_accept: str
    max_upload_bytes: int = Field(
        ...,
        description="Max size for signed GCS uploads (upload-url → from-upload).",
    )
    max_multipart_upload_bytes: int = Field(
        ...,
        description=(
            "Max video size for legacy multipart POST /submissions. "
            "Larger files must use the signed-URL flow."
        ),
    )
    sources: list[VideoSource]
    note: str


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
        description=(
            "When true, students may view the evaluation report and final score. "
            "Set automatically when an admin approves the evaluation."
        ),
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
    analyzed_by: Optional[str] = Field(
        None,
        description="User id of the admin/evaluator who started AI analysis.",
    )
    review_status: ReviewStatus = Field(
        "none",
        description=(
            "Evaluation review workflow: none → pending_review (evaluator submitted) "
            "→ approved (admin) or changes_requested."
        ),
    )
    final_score: Optional[float] = Field(
        None,
        description="Final score shown to students after admin approval (0-100).",
    )
    evaluator_notes: Optional[str] = Field(
        None,
        description="Optional notes from the evaluator when submitting for review.",
    )
    submitted_for_review_at: Optional[datetime] = None
    submitted_for_review_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None
    review_notes: Optional[str] = Field(
        None,
        description="Optional admin notes when approving or requesting changes.",
    )
    video_path: str
    video_url: Optional[str] = Field(
        None,
        description="Time-limited HTTPS URL for browser playback (not gs://).",
    )
    content_type: str
    source_filename: str
    video_source: Optional[VideoSource] = Field(
        None,
        description=(
            "How the demo was provided: 'recorded' (in-browser) or "
            "'uploaded' (local file). Same GCS storage either way."
        ),
    )
    analysis: Optional[AnalysisSummary] = Field(
        None,
        description=(
            "Joined analysis summary when completed. For students, only present "
            "after an admin approves/publishes the report."
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
    """Optional body when starting AI analysis on a submission."""

    evaluation_criteria: Optional[str] = Field(
        None,
        max_length=2000,
        description="Optional extra focus areas appended to the analysis context (not required).",
    )

    @field_validator("evaluation_criteria", mode="before")
    @classmethod
    def normalize_criteria(cls, value: Optional[str]) -> Optional[str]:
        return strip_optional(value)


class SubmitForReviewRequest(BaseModel):
    """Evaluator submits a completed evaluation to admin for approval."""

    final_score: float = Field(
        ...,
        ge=0,
        le=100,
        description="Proposed final score (0-100) for admin approval.",
    )
    evaluator_notes: Optional[str] = Field(
        None,
        max_length=5000,
        description="Optional notes for the admin reviewing this evaluation.",
    )

    @field_validator("evaluator_notes", mode="before")
    @classmethod
    def normalize_notes(cls, value: Optional[str]) -> Optional[str]:
        return strip_optional(value)


class ApproveEvaluationRequest(BaseModel):
    """Admin approves an evaluator's submitted evaluation (publishes to student)."""

    final_score: Optional[float] = Field(
        None,
        ge=0,
        le=100,
        description="Optional override of the evaluator's proposed score. Defaults to theirs.",
    )
    review_notes: Optional[str] = Field(
        None,
        max_length=5000,
        description="Optional admin notes.",
    )

    @field_validator("review_notes", mode="before")
    @classmethod
    def normalize_notes(cls, value: Optional[str]) -> Optional[str]:
        return strip_optional(value)


class RequestChangesRequest(BaseModel):
    """Admin sends the evaluation back to the assigned evaluator."""

    review_notes: Optional[str] = Field(
        None,
        max_length=5000,
        description="What the evaluator should change before resubmitting.",
    )

    @field_validator("review_notes", mode="before")
    @classmethod
    def normalize_notes(cls, value: Optional[str]) -> Optional[str]:
        return strip_optional(value)


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


class PrepareUploadRequest(BaseModel):
    """Request a direct-to-GCS signed upload URL for a submission video."""

    filename: str = Field(..., min_length=1, max_length=500)
    content_type: Optional[str] = Field(
        None,
        max_length=200,
        description=(
            "Video MIME type (e.g. video/webm, video/mp4). "
            "Optional for local file picks that omit type — resolved from filename."
        ),
    )
    video_source: Optional[VideoSource] = Field(
        None,
        description="'recorded' for MediaRecorder blob, 'uploaded' for local file.",
    )

    @field_validator("filename", mode="before")
    @classmethod
    def normalize_filename(cls, value: str) -> str:
        return strip_required(value)

    @field_validator("content_type", mode="before")
    @classmethod
    def normalize_content_type(cls, value: Optional[str]) -> Optional[str]:
        return strip_optional(value)


class PrepareUploadResponse(BaseModel):
    """Signed PUT URL so the browser can upload video directly to GCS."""

    upload_url: str = Field(
        ...,
        description="PUT the video bytes here. Must send the same Content-Type.",
    )
    video_path: str = Field(..., description="gs:// URI to pass when finalizing.")
    object_name: str
    content_type: str
    source_filename: str
    video_source: Optional[VideoSource] = None
    expires_in_seconds: int
    max_upload_bytes: int = Field(
        ...,
        description="Suggested client-side max size before rejecting the file.",
    )


class CreateSubmissionFromUploadRequest(BaseModel):
    """Finalize a submission after the video was uploaded via signed URL."""

    video_path: str = Field(..., min_length=1, description="gs:// URI from prepare-upload.")
    content_type: str = Field(..., min_length=1)
    source_filename: str = Field(..., min_length=1, max_length=500)
    hackathon_id: str = Field(..., min_length=1)
    theme_id: str = Field(..., min_length=1)
    problem_statement: str = Field(..., min_length=1, max_length=5000)
    solution_description: str = Field(..., min_length=1, max_length=5000)
    video_source: Optional[VideoSource] = Field(
        None,
        description="'recorded' or 'uploaded' — same GCS path either way.",
    )

    @field_validator(
        "video_path",
        "content_type",
        "source_filename",
        "hackathon_id",
        "theme_id",
        "problem_statement",
        "solution_description",
        mode="before",
    )
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        return strip_required(value)

