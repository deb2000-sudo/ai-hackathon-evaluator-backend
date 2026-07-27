"""
Student submission routes.

    POST   /submissions                 -> student uploads (no analysis triggered)
    GET    /submissions                 -> student lists their own submissions
    GET    /submissions/admin/hackathons              -> admin: hackathons + submission counts
    GET    /submissions/admin/hackathons/{hackathon_id} -> admin: submissions for one hackathon
    POST   /submissions/admin/hackathons/{hackathon_id}/assign-equally
           -> admin: randomly divide selected submissions among active evaluators
    GET    /submissions/admin/all       -> admin lists all submissions
    GET    /submissions/evaluator/hackathons
           -> evaluator: hackathons with assigned submission counts
    GET    /submissions/evaluator/hackathons/{hackathon_id}
           -> evaluator: assigned submissions for one hackathon
    GET    /submissions/assigned-to-me  -> evaluator: flat list of assigned submissions
    GET    /submissions/{id}            -> get submission (report hidden until published)
    GET    /submissions/{id}/video      -> stream/download the submission video
    GET    /submissions/{id}/analysis   -> analysis (students only if published)
    GET    /submissions/{id}/report     -> report (students only if published)
    POST   /submissions/{id}/evaluate   -> admin or assigned evaluator starts AI analysis
    POST   /submissions/{id}/submit-for-review -> evaluator submits evaluation to admin
    POST   /submissions/{id}/approve-evaluation -> admin approves → final score to student
    POST   /submissions/{id}/request-changes -> admin sends evaluation back to evaluator
    POST   /submissions/{id}/publish    -> admin publishes / unpublishes the report
    POST   /submissions/{id}/assign     -> admin assigns one evaluator (dropdown)
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

from app.middleware.auth_middleware import (
    get_active_user,
    get_admin_user,
    get_evaluator_user,
    get_student_user,
)
from app.models.analysis_model import AnalysisReportResponse, AnalysisResponse
from app.models.submission_model import (
    ApproveEvaluationRequest,
    AssignEvaluatorRequest,
    DivideEquallyRequest,
    DivideEquallyResponse,
    EvaluateSubmissionRequest,
    HackathonSubmissionSummary,
    PublishReportRequest,
    RequestChangesRequest,
    SubmissionResponse,
    SubmitForReviewRequest,
)
from app.models.user_model import CurrentUser
from app.services.submission_service import SubmissionService
from app.utils.video_upload import resolve_video_content_type


router = APIRouter(prefix="/submissions", tags=["submissions"])


def _to_submission_response(
    service: SubmissionService,
    submission: dict,
    current_user: CurrentUser | None = None,
) -> SubmissionResponse:
    return SubmissionResponse(
        **service.enrich_submission_for_response(submission, current_user=current_user)
    )


def _ensure_student_can_view_report(
    service: SubmissionService,
    submission: dict,
    current_user: CurrentUser,
) -> None:
    """Staff always; students only after publish/approval."""
    if current_user.role in ("admin", "evaluator"):
        return
    if not service.student_can_view_report(submission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "The evaluation report is not available yet. "
                "It will be visible once the admin approves the final score."
            ),
        )


def _http_from_value_error(e: ValueError) -> HTTPException:
    detail = str(e)
    lower = detail.lower()
    if "not found" in lower:
        code = status.HTTP_404_NOT_FOUND
    elif "already" in lower or "conflict" in lower:
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=detail)


@router.post("", response_model=SubmissionResponse, status_code=201)
async def create_submission(
    video: UploadFile = File(..., description="Hackathon demo / screen recording"),
    hackathon_id: str = Form(..., min_length=1, description="Hackathon this submission belongs to"),
    theme_id: str = Form(
        ...,
        min_length=1,
        description="Theme selected from themes released for this hackathon",
    ),
    problem_statement: str = Form(..., min_length=1, max_length=5000),
    solution_description: str = Form(..., min_length=1, max_length=5000),
    student: CurrentUser = Depends(get_student_user),
) -> SubmissionResponse:
    """
    Create a student submission: upload the video and store project details.

    Does **not** start AI analysis. Students are told the submission is recorded
    and results will appear after the hackathon ends / admin publishes the report.
    Requires ``hackathon_id`` and a ``theme_id`` from that hackathon's themes.
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
            hackathon_id=hackathon_id,
            theme_id=theme_id,
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

    return _to_submission_response(service, submission, current_user=student)


@router.get("", response_model=list[SubmissionResponse])
async def list_my_submissions(
    student: CurrentUser = Depends(get_student_user),
) -> list[SubmissionResponse]:
    """List all submissions for the authenticated student."""
    service = SubmissionService()
    submissions = service.list_student_submissions(student.user_id)
    return [
        _to_submission_response(service, item, current_user=student)
        for item in submissions
    ]


@router.get("/admin/hackathons", response_model=list[HackathonSubmissionSummary])
async def list_hackathons_for_admin_submissions(
    admin: CurrentUser = Depends(get_admin_user),
) -> list[HackathonSubmissionSummary]:
    """
    Admin Submissions tab: list hackathons with submission counts.

    Each row is a hackathon the admin can open to view that hackathon's
    submissions via ``GET /submissions/admin/hackathons/{hackathon_id}``.
    """
    service = SubmissionService()
    summaries = service.list_hackathons_with_submission_counts()
    return [HackathonSubmissionSummary(**item) for item in summaries]


@router.get(
    "/admin/hackathons/{hackathon_id}",
    response_model=list[SubmissionResponse],
)
async def list_submissions_for_hackathon_admin(
    hackathon_id: str,
    admin: CurrentUser = Depends(get_admin_user),
) -> list[SubmissionResponse]:
    """Admin: list all submissions belonging to a specific hackathon."""
    service = SubmissionService()
    hackathon = service.hackathon_service.get_hackathon(hackathon_id)
    if not hackathon:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hackathon not found",
        )

    submissions = service.list_submissions_for_hackathon(hackathon_id)
    return [
        _to_submission_response(service, item, current_user=admin)
        for item in submissions
    ]


@router.post(
    "/admin/hackathons/{hackathon_id}/assign-equally",
    response_model=DivideEquallyResponse,
)
async def divide_submissions_equally(
    hackathon_id: str,
    request: DivideEquallyRequest,
    admin: CurrentUser = Depends(get_admin_user),
) -> DivideEquallyResponse:
    """
    Randomly divide selected submissions among active (approved) evaluators.

    Used by the bulk action on the admin Submissions table after multi-select.
    """
    service = SubmissionService()
    try:
        assigned = service.divide_equally_among_evaluators(
            hackathon_id=hackathon_id,
            submission_ids=request.submission_ids,
            assigned_by=admin.user_id,
            evaluator_ids=request.evaluator_ids,
        )
    except ValueError as e:
        detail = str(e)
        code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in detail.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=detail) from e

    evaluator_count = len(
        {
            item.get("assigned_evaluator_id")
            for item in assigned
            if item.get("assigned_evaluator_id")
        }
    )
    return DivideEquallyResponse(
        assigned_count=len(assigned),
        evaluator_count=evaluator_count,
        submissions=[
            _to_submission_response(service, item, current_user=admin)
            for item in assigned
        ],
    )


@router.get("/admin/all", response_model=list[SubmissionResponse])
async def list_all_submissions_for_admin(
    admin: CurrentUser = Depends(get_admin_user),
) -> list[SubmissionResponse]:
    """Admin review queue: list every student submission."""
    service = SubmissionService()
    submissions = service.list_all_submissions()
    return [
        _to_submission_response(service, item, current_user=admin)
        for item in submissions
    ]


@router.get("/evaluator/hackathons", response_model=list[HackathonSubmissionSummary])
async def list_hackathons_for_evaluator(
    evaluator: CurrentUser = Depends(get_evaluator_user),
) -> list[HackathonSubmissionSummary]:
    """
    Evaluator Submissions home: hackathons that have at least one submission
    assigned to this evaluator, with assigned counts.
    """
    service = SubmissionService()
    summaries = service.list_hackathons_with_submission_counts(
        evaluator_id=evaluator.user_id,
    )
    return [HackathonSubmissionSummary(**item) for item in summaries]


@router.get(
    "/evaluator/hackathons/{hackathon_id}",
    response_model=list[SubmissionResponse],
)
async def list_submissions_for_hackathon_evaluator(
    hackathon_id: str,
    evaluator: CurrentUser = Depends(get_evaluator_user),
) -> list[SubmissionResponse]:
    """Evaluator: list only submissions assigned to them for this hackathon."""
    service = SubmissionService()
    hackathon = service.hackathon_service.get_hackathon(hackathon_id)
    if not hackathon:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hackathon not found",
        )

    submissions = service.list_submissions_for_hackathon(
        hackathon_id,
        evaluator_id=evaluator.user_id,
    )
    return [
        _to_submission_response(service, item, current_user=evaluator)
        for item in submissions
    ]


@router.get("/assigned-to-me", response_model=list[SubmissionResponse])
async def list_my_assigned_submissions(
    current_user: CurrentUser = Depends(get_active_user),
) -> list[SubmissionResponse]:
    """
    Flat list of submissions assigned to the current user.

    Prefer ``/evaluator/hackathons`` for the hackathon-first UI.
    """
    if current_user.role not in ("evaluator", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only evaluators can list assigned submissions",
        )

    service = SubmissionService()
    submissions = service.list_submissions_for_evaluator(current_user.user_id)
    return [
        _to_submission_response(service, item, current_user=current_user)
        for item in submissions
    ]


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
    """Fetch the analysis document. Students may only access it after publish."""
    service = SubmissionService()
    submission = service.get_submission(submission_id, current_user)
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    _ensure_student_can_view_report(service, submission, current_user)

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
    Fetch the AI-generated markdown analysis report.

    Admins/evaluators can always read a completed report.
    Students can only read it after ``report_published`` is true.
    """
    service = SubmissionService()
    submission = service.get_submission(submission_id, current_user)
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    _ensure_student_can_view_report(service, submission, current_user)

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

    Students may read their own; assigned evaluators and admins may read theirs.
    Analysis content is omitted for students until the report is approved/published.
    """
    service = SubmissionService()
    submission = service.get_submission(submission_id, current_user)
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    return _to_submission_response(service, submission, current_user=current_user)


@router.post("/{submission_id}/evaluate", response_model=SubmissionResponse, status_code=202)
async def evaluate_submission(
    submission_id: str,
    request: EvaluateSubmissionRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(get_active_user),
) -> SubmissionResponse:
    """
    Start AI video analysis for a submission.

    Allowed for **admins** or the **assigned approved evaluator**.
    After analysis completes, the evaluator submits for review; admin approval
    publishes the final score to the student.
    """
    if current_user.role not in ("admin", "evaluator"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins or assigned evaluators can start analysis",
        )

    service = SubmissionService()
    submission = service.get_submission(submission_id, current_user)
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    try:
        service.assert_can_evaluate(submission, current_user)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from e

    if submission.get("status") == "processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This submission is already being analyzed",
        )

    try:
        service.mark_queued_for_evaluation(
            submission_id,
            evaluation_criteria=request.evaluation_criteria,
            analyzed_by=current_user.user_id,
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

    refreshed = service.get_submission(submission_id, current_user)
    if not refreshed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    return _to_submission_response(service, refreshed, current_user=current_user)


@router.post("/{submission_id}/submit-for-review", response_model=SubmissionResponse)
async def submit_evaluation_for_review(
    submission_id: str,
    request: SubmitForReviewRequest,
    evaluator: CurrentUser = Depends(get_evaluator_user),
) -> SubmissionResponse:
    """
    Assigned evaluator submits a completed evaluation to admin for approval.

    Requires AI analysis ``status=completed``. Sets ``review_status=pending_review``.
    """
    service = SubmissionService()
    try:
        submission = service.submit_for_review(
            submission_id=submission_id,
            evaluator_user_id=evaluator.user_id,
            final_score=request.final_score,
            evaluator_notes=request.evaluator_notes,
        )
    except ValueError as e:
        raise _http_from_value_error(e) from e

    return _to_submission_response(service, submission, current_user=evaluator)


@router.post("/{submission_id}/approve-evaluation", response_model=SubmissionResponse)
async def approve_evaluation(
    submission_id: str,
    request: ApproveEvaluationRequest,
    admin: CurrentUser = Depends(get_admin_user),
) -> SubmissionResponse:
    """
    Admin approves a pending evaluation.

    Sets ``review_status=approved``, locks ``final_score``, and publishes the
    report so the student can see the result.
    """
    service = SubmissionService()
    try:
        submission = service.approve_evaluation(
            submission_id=submission_id,
            admin_user_id=admin.user_id,
            final_score=request.final_score,
            review_notes=request.review_notes,
        )
    except ValueError as e:
        raise _http_from_value_error(e) from e

    return _to_submission_response(service, submission, current_user=admin)


@router.post("/{submission_id}/request-changes", response_model=SubmissionResponse)
async def request_evaluation_changes(
    submission_id: str,
    request: RequestChangesRequest,
    admin: CurrentUser = Depends(get_admin_user),
) -> SubmissionResponse:
    """
    Admin sends a pending/approved evaluation back to the assigned evaluator.

    Unpublishes the student report and sets ``review_status=changes_requested``.
    """
    service = SubmissionService()
    try:
        submission = service.request_evaluation_changes(
            submission_id=submission_id,
            admin_user_id=admin.user_id,
            review_notes=request.review_notes,
        )
    except ValueError as e:
        raise _http_from_value_error(e) from e

    return _to_submission_response(service, submission, current_user=admin)


@router.post("/{submission_id}/publish", response_model=SubmissionResponse)
async def publish_submission_report(
    submission_id: str,
    request: PublishReportRequest,
    admin: CurrentUser = Depends(get_admin_user),
) -> SubmissionResponse:
    """
    Publish or unpublish the analysis report for the student. **Admin only.**

    Prefer ``approve-evaluation`` for the evaluator review workflow. This remains
    available for direct admin publish without the review gate.
    """
    service = SubmissionService()
    try:
        submission = service.publish_report(
            submission_id=submission_id,
            publish=request.publish,
            admin_user_id=admin.user_id,
        )
    except ValueError as e:
        raise _http_from_value_error(e) from e

    return _to_submission_response(service, submission, current_user=admin)


@router.post("/{submission_id}/assign", response_model=SubmissionResponse)
async def assign_submission_evaluator(
    submission_id: str,
    request: AssignEvaluatorRequest,
    admin: CurrentUser = Depends(get_admin_user),
) -> SubmissionResponse:
    """
    Assign one approved (active) evaluator to a submission, or clear assignment.

    Used by the per-row Evaluator dropdown on the admin Submissions table.
    Pass ``evaluator_id: null`` to unassign.
    """
    service = SubmissionService()
    try:
        submission = service.assign_evaluator(
            submission_id=submission_id,
            evaluator_id=request.evaluator_id,
            assigned_by=admin.user_id,
        )
    except ValueError as e:
        detail = str(e)
        code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in detail.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=detail) from e

    return _to_submission_response(service, submission, current_user=admin)
