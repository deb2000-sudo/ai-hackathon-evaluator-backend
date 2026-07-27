"""
AI evaluation metric-scoring routes.

    POST   /ai-evaluation-metric-scoring        -> admin creates scoring for a requirement
    GET    /ai-evaluation-metric-scoring        -> list (optional ?evaluation_requirement_id=)
    GET    /ai-evaluation-metric-scoring/{id}   -> get one
    PATCH  /ai-evaluation-metric-scoring/{id}   -> admin updates
    DELETE /ai-evaluation-metric-scoring/{id}   -> admin deletes
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.middleware.auth_middleware import get_admin_user, get_current_user
from app.models.metric_scoring_model import (
    MetricScoringCreateRequest,
    MetricScoringResponse,
    MetricScoringUpdateRequest,
)
from app.models.user_model import CurrentUser
from app.services.metric_scoring_service import MetricScoringService


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai-evaluation-metric-scoring", tags=["ai-evaluation-metric-scoring"])


@router.post("", response_model=MetricScoringResponse, status_code=201)
async def create_metric_scoring(
    request: MetricScoringCreateRequest,
    admin: CurrentUser = Depends(get_admin_user),
) -> MetricScoringResponse:
    """
    Create a metric-scoring config for an evaluation requirement. Admin only.

    Each metric's ``field_key`` must match a field of the linked evaluation
    requirement; ``scoring_prompt`` is the natural-language scoring instruction.
    """
    service = MetricScoringService()
    try:
        scoring = service.create_scoring(request=request, created_by=admin.user_id)
    except ValueError as e:
        detail = str(e)
        code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in detail.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=detail) from e

    return MetricScoringResponse(**scoring)


@router.get("", response_model=list[MetricScoringResponse])
async def list_metric_scoring(
    evaluation_requirement_id: str | None = None,
    current_user: CurrentUser = Depends(get_current_user),
) -> list[MetricScoringResponse]:
    """
    List metric-scoring configs. Pass ``?evaluation_requirement_id=`` to fetch the
    config linked to a specific evaluation requirement.
    """
    service = MetricScoringService()
    items = service.list_scoring(evaluation_requirement_id=evaluation_requirement_id)
    return [MetricScoringResponse(**item) for item in items]


@router.get("/{scoring_id}", response_model=MetricScoringResponse)
async def get_metric_scoring(
    scoring_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> MetricScoringResponse:
    """Get a single metric-scoring config by id."""
    service = MetricScoringService()
    scoring = service.get_scoring(scoring_id)
    if not scoring:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Metric-scoring config not found",
        )
    return MetricScoringResponse(**scoring)


@router.patch("/{scoring_id}", response_model=MetricScoringResponse)
async def update_metric_scoring(
    scoring_id: str,
    request: MetricScoringUpdateRequest,
    admin: CurrentUser = Depends(get_admin_user),
) -> MetricScoringResponse:
    """Update a metric-scoring config. Admin only."""
    service = MetricScoringService()
    try:
        scoring = service.update_scoring(scoring_id, request)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    if not scoring:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Metric-scoring config not found",
        )
    return MetricScoringResponse(**scoring)


@router.delete("/{scoring_id}", status_code=200)
async def delete_metric_scoring(
    scoring_id: str,
    admin: CurrentUser = Depends(get_admin_user),
) -> dict:
    """Delete a metric-scoring config. Admin only."""
    service = MetricScoringService()
    deleted = service.delete_scoring(scoring_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Metric-scoring config not found",
        )
    return {"message": "Metric-scoring config deleted successfully"}
