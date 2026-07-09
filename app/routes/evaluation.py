"""
Authenticated hackathon video evaluation routes.

    POST /upload-video          -> upload a submission video
    POST /analyze-video         -> run AI evaluation on an uploaded video
    GET  /evaluations/{id}       -> poll status / fetch the result
"""

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status

from app.middleware.auth_middleware import get_active_user
from app.models.evaluation_model import (
    AnalyzeVideoRequest,
    EvaluationSessionResponse,
    UploadVideoResponse,
)
from app.models.user_model import CurrentUser
from app.services.evaluation_service import ALLOWED_VIDEO_TYPES, EvaluationService


router = APIRouter(tags=["evaluation"])


@router.post("/upload-video", response_model=UploadVideoResponse, status_code=201)
async def upload_video(
    video: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_active_user),
) -> UploadVideoResponse:
    """
    Upload a hackathon submission video. Stores it and creates an evaluation
    session with status "uploaded". Call POST /analyze-video next.
    """
    if video.content_type not in ALLOWED_VIDEO_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Unsupported video type. Allowed: "
                + ", ".join(sorted(ALLOWED_VIDEO_TYPES))
            ),
        )

    video_payload = (
        video.filename or "submission",
        await video.read(),
        video.content_type,
    )

    try:
        service = EvaluationService()
        session = service.upload_video(current_user, video_payload)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e

    return UploadVideoResponse(**session)


@router.post("/analyze-video", response_model=EvaluationSessionResponse, status_code=202)
async def analyze_video(
    request: AnalyzeVideoRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(get_active_user),
) -> EvaluationSessionResponse:
    """
    Kick off AI evaluation for an already-uploaded submission video.
    Runs in the background; poll GET /evaluations/{session_id} for the result.
    """
    service = EvaluationService()
    session = service.get_user_session(request.session_id, current_user)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation session not found",
        )

    if session.get("status") == "processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This video is already being analyzed",
        )

    service.mark_queued_for_analysis(
        request.session_id,
        request.problem_statement,
        request.solution_description,
        request.criteria,
    )
    background_tasks.add_task(
        service.analyze_video_for_session,
        request.session_id,
        problem_statement=request.problem_statement,
        solution_description=request.solution_description,
        criteria=request.criteria,
    )

    refreshed = service.get_user_session(request.session_id, current_user)
    return EvaluationSessionResponse(**refreshed)


@router.get("/evaluations/{session_id}", response_model=EvaluationSessionResponse)
async def get_evaluation(
    session_id: str,
    current_user: CurrentUser = Depends(get_active_user),
) -> EvaluationSessionResponse:
    """
    Get evaluation status and, once complete, the AI evaluation result.
    Only the owner, an evaluator, or an admin may read a session.
    """
    service = EvaluationService()
    session = service.get_user_session(session_id, current_user)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation session not found",
        )

    return EvaluationSessionResponse(**session)
