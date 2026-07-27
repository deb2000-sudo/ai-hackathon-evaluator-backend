"""
Admin routes for managing users.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.middleware.auth_middleware import get_admin_user
from app.models.user_model import CurrentUser, UserResponse, UserUpdate
from app.services.user_service import UserService


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])

user_service = UserService()


@router.get("/users", status_code=200)
async def get_users(
    admin: CurrentUser = Depends(get_admin_user),
) -> list[UserResponse]:
    """
    Get all non-admin users.
    """
    try:
        users = user_service.get_non_admin_users()
        return [user_service.to_user_response(user["id"], user) for user in users]

    except Exception as e:
        logger.error(f"Error getting users: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving users",
        )


@router.get("/evaluators/pending", status_code=200)
async def get_pending_evaluators(
    admin: CurrentUser = Depends(get_admin_user),
) -> list[UserResponse]:
    """
    List evaluator registrations awaiting admin approval.
    """
    try:
        evaluators = user_service.get_evaluators(approval_status="pending")
        return [user_service.to_user_response(user["id"], user) for user in evaluators]
    except Exception as e:
        logger.error("Error getting pending evaluators: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving pending evaluators",
        )


@router.get("/evaluators", status_code=200)
async def get_evaluators(
    approval_status: Optional[str] = Query(
        None,
        description="Filter by approval_status: pending | approved | rejected",
    ),
    admin: CurrentUser = Depends(get_admin_user),
) -> list[UserResponse]:
    """
    List evaluator accounts.

    Use ``?approval_status=approved`` for the Submissions "Assign evaluator" dropdown
    (active evaluators only).
    """
    try:
        status_filter = approval_status.strip().lower() if approval_status else None
        if status_filter and status_filter not in ("pending", "approved", "rejected"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="approval_status must be pending, approved, or rejected",
            )
        evaluators = user_service.get_evaluators(approval_status=status_filter)
        return [user_service.to_user_response(user["id"], user) for user in evaluators]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error getting evaluators: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving evaluators",
        )


@router.post("/evaluators/{user_id}/approve", response_model=UserResponse, status_code=200)
async def approve_evaluator(
    user_id: str,
    admin: CurrentUser = Depends(get_admin_user),
) -> UserResponse:
    """
    Approve a pending evaluator registration.
    """
    try:
        updated_user = user_service.approve_evaluator(user_id)
        return user_service.to_user_response(user_id, updated_user)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.error("Error approving evaluator %s: %s", user_id, str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error approving evaluator",
        )


@router.get("/user/{user_id}", status_code=200)
async def get_user(
    user_id: str,
    admin: CurrentUser = Depends(get_admin_user),
) -> UserResponse:
    """
    Get specific user details.
    """
    try:
        user_data = user_service.get_user(user_id)

        if not user_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        return user_service.to_user_response(user_id, user_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving user",
        )


@router.patch("/user/{user_id}", status_code=200)
async def update_user(
    user_id: str,
    data: UserUpdate,
    admin: CurrentUser = Depends(get_admin_user),
) -> UserResponse:
    """
    Update user profile.
    """
    try:
        user_data = user_service.get_user(user_id)

        if not user_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        update_data = {}
        if data.name is not None:
            update_data["name"] = data.name

        if update_data:
            user_service.update_user(user_id, update_data)

        updated_user = user_service.get_user(user_id)
        if not updated_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        return user_service.to_user_response(user_id, updated_user)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating user: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error updating user",
        )
