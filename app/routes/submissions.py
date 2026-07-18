"""
Student submission routes.

    POST   /submissions              -> student uploads a hackathon video submission
    GET    /submissions              -> student lists their submissions
    GET    /submissions/{id}         -> get submission status / analysis result
    GET    /submissions/{id}/video   -> stream/download the submission video
    GET    /submissions/{id}/report  -> fetch the markdown analysis report
    GET    /submissions/{id}/analysis  -> fetch the linked analysis document
    POST   /submissions/{id}/evaluate -> start AI video analysis (evaluation_criteria optional)
"""

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)

from app.middleware.auth_middleware import get_active_user, get_student_user
from app.models.analysis_model import AnalysisReportResponse, AnalysisResponse
from app.models.submission_model import (
    EvaluateSubmissionRequest,
    SubmissionResponse,
)
from app.models.user_model import CurrentUser
from app.services.submission_service import SubmissionService
from app.utils.video_upload import resolve_video_content_type


router = APIRouter(prefix="/submissions", tags=["submissions"])


def _to_submission_response(
    service: SubmissionService,
    submission: dict,
) -> SubmissionResponse:
    return SubmissionResponse(**service.enrich_submission_for_response(submission))


@router.post("", response_model=SubmissionResponse, status_code=201)
async def create_submission(
    video: UploadFile = File(..., description="Hackathon demo / screen recording"),
    problem_statement: str = Form(..., min_length=1, max_length=5000),
    solution_description: str = Form(..., min_length=1, max_length=5000),
    student: CurrentUser = Depends(get_student_user),
) -> SubmissionResponse:
    """
    Create a student submission: upload the video and store project details.

    Required: video, problem statement, solution description.
    Team name and theme are read automatically from the student's profile.
    """
    video_bytes = await video.read()

    try:
        resolved_type, _extension = resolve_video_content_type(
            video.content_type,
            video.filename,
            video_bytes,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    video_payload = (
        video.filename or "submission",
        video_bytes,
        resolved_type,
    )

    try:
        service = SubmissionService()
        submission = service.create_submission(
            student=student,
            video=video_payload,
            problem_statement=problem_statement,
            solution_description=solution_description,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Submission upload failed",
        ) from e

    return _to_submission_response(service, submission)


@router.get("", response_model=list[SubmissionResponse])
async def list_my_submissions(
    student: CurrentUser = Depends(get_student_user),
) -> list[SubmissionResponse]:
    """List all submissions for the authenticated student."""
    service = SubmissionService()
    submissions = service.list_student_submissions(student.user_id)
    return [_to_submission_response(service, item) for item in submissions]


@router.get("/{submission_id}/video")
async def stream_submission_video(
    submission_id: str,
    request: Request,
    current_user: CurrentUser = Depends(get_active_user),
):
    """
    Stream the submission video over HTTPS.

    Supports HTTP Range requests for in-browser seeking. Requires the same
    authentication as other submission routes (cookie or Bearer token).
    """
    service = SubmissionService()
    submission = service.get_submission(submission_id, current_user)
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    try:
        return service.build_video_stream_response(
            submission,
            request.headers.get("range"),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.get("/{submission_id}/analysis", response_model=AnalysisResponse)
async def get_submission_analysis(
    submission_id: str,
    current_user: CurrentUser = Depends(get_active_user),
) -> AnalysisResponse:
    """Fetch the analysis document linked to a submission."""
    service = SubmissionService()
    analysis = service.get_analysis_for_submission(submission_id, current_user)
    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis not found",
        )
    return AnalysisResponse(**analysis)


@router.get("/{submission_id}/report", response_model=AnalysisReportResponse)
async def get_submission_report(
    submission_id: str,
    current_user: CurrentUser = Depends(get_active_user),
) -> AnalysisReportResponse:
    """
    Fetch the AI-generated markdown analysis report for a submission.

    Available when analysis status is ``completed``. Poll ``GET /submissions/{id}``
    or ``GET /submissions/{id}/analysis`` while status is ``processing``.
    """
    service = SubmissionService()
    analysis = service.get_analysis_for_submission(submission_id, current_user)
    if not analysis or analysis.get("status") != "completed":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis report not available yet",
        )

    return AnalysisReportResponse(
        analysis_id=analysis["id"],
        submission_id=submission_id,
        status=analysis["status"],
        checklist=analysis["checklist"],
        report=analysis["report"],
        analyzed_at=analysis["analyzed_at"],
    )


@router.get("/{submission_id}", response_model=SubmissionResponse)
async def get_submission(
    submission_id: str,
    current_user: CurrentUser = Depends(get_active_user),
) -> SubmissionResponse:
    """
    Get a submission by id.

    Students may read their own; evaluators and admins may read any submission.
    """
    service = SubmissionService()
    submission = service.get_submission(submission_id, current_user)
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    return _to_submission_response(service, submission)


@router.post("/{submission_id}/evaluate", response_model=SubmissionResponse, status_code=202)
async def evaluate_submission(
    submission_id: str,
    request: EvaluateSubmissionRequest,
    background_tasks: BackgroundTasks,
    student: CurrentUser = Depends(get_student_user),
) -> SubmissionResponse:
    """
    Start AI video analysis for a previously uploaded submission.

    Uses the stored problem statement, solution description, and GCS video URI.
    `evaluation_criteria` is optional and appended to the generated checklist.
    """
    service = SubmissionService()
    submission = service.get_submission(submission_id, student)
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    if submission.get("status") == "processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This submission is already being analyzed",
        )

    try:
        service.mark_queued_for_evaluation(
            submission_id,
            evaluation_criteria=request.evaluation_criteria,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e

    background_tasks.add_task(
        service.evaluate_submission,
        submission_id,
        evaluation_criteria=request.evaluation_criteria,
    )

    refreshed = service.get_submission(submission_id, student)
    if not refreshed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    return _to_submission_response(service, refreshed)
