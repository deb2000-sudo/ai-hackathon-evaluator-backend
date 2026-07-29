"""
Reusable evaluation-requirement routes.

    POST   /evaluation-requirements        -> admin creates a reusable requirement
    GET    /evaluation-requirements        -> list requirements (for the round dropdown)
    GET    /evaluation-requirements/{id}   -> get a single requirement
    PATCH  /evaluation-requirements/{id}   -> admin updates a requirement
    DELETE /evaluation-requirements/{id}   -> admin deletes a requirement
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.middleware.auth_middleware import get_admin_user, get_current_user
from app.models.evaluation_requirement_model import (
    EvaluationRequirementCreateRequest,
    EvaluationRequirementResponse,
    EvaluationRequirementUpdateRequest,
)
from app.models.user_model import CurrentUser
from app.services.evaluation_requirement_service import EvaluationRequirementService
from app.utils.async_io import run_sync


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/evaluation-requirements", tags=["evaluation-requirements"])


@router.post("", response_model=EvaluationRequirementResponse, status_code=201)
async def create_evaluation_requirement(
    request: EvaluationRequirementCreateRequest,
    admin: CurrentUser = Depends(get_admin_user),
) -> EvaluationRequirementResponse:
    """
    Create a reusable evaluation requirement. Admin only.

    Define the fields a student must submit (e.g. Problem Statement, Solution
    Description, GitHub link, MVP link). The returned ``id`` is what you link to
    a hackathon round.
    """
    service = EvaluationRequirementService()
    requirement = await run_sync(
        service.create_requirement, request=request, created_by=admin.user_id
    )
    return EvaluationRequirementResponse(**requirement)


@router.get("", response_model=list[EvaluationRequirementResponse])
async def list_evaluation_requirements(
    current_user: CurrentUser = Depends(get_current_user),
) -> list[EvaluationRequirementResponse]:
    """List all evaluation requirements (used to populate the round dropdown)."""
    service = EvaluationRequirementService()
    requirements = await run_sync(service.list_requirements)
    return [EvaluationRequirementResponse(**item) for item in requirements]


@router.get("/{requirement_id}", response_model=EvaluationRequirementResponse)
async def get_evaluation_requirement(
    requirement_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> EvaluationRequirementResponse:
    """Get a single evaluation requirement by id."""
    service = EvaluationRequirementService()
    requirement = await run_sync(service.get_requirement, requirement_id)
    if not requirement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation requirement not found",
        )
    return EvaluationRequirementResponse(**requirement)


@router.patch("/{requirement_id}", response_model=EvaluationRequirementResponse)
async def update_evaluation_requirement(
    requirement_id: str,
    request: EvaluationRequirementUpdateRequest,
    admin: CurrentUser = Depends(get_admin_user),
) -> EvaluationRequirementResponse:
    """Update an evaluation requirement. Admin only."""
    service = EvaluationRequirementService()
    requirement = await run_sync(service.update_requirement, requirement_id, request)
    if not requirement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation requirement not found",
        )
    return EvaluationRequirementResponse(**requirement)


@router.delete("/{requirement_id}", status_code=200)
async def delete_evaluation_requirement(
    requirement_id: str,
    admin: CurrentUser = Depends(get_admin_user),
) -> dict:
    """Delete an evaluation requirement. Admin only."""
    service = EvaluationRequirementService()
    deleted = await run_sync(service.delete_requirement, requirement_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evaluation requirement not found",
        )
    return {"message": "Evaluation requirement deleted successfully"}
