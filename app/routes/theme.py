"""
Theme routes.

    POST   /themes        -> admin creates a theme
    GET    /themes        -> list themes (any authenticated user)
    GET    /themes/{id}   -> get one theme
    PATCH  /themes/{id}   -> admin updates a theme
    DELETE /themes/{id}   -> admin deletes a theme
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.middleware.auth_middleware import get_admin_user, get_current_user
from app.models.theme_model import ThemeCreateRequest, ThemeResponse, ThemeUpdateRequest
from app.models.user_model import CurrentUser
from app.services.theme_service import ThemeService


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/themes", tags=["themes"])


@router.post("", response_model=ThemeResponse, status_code=201)
async def create_theme(
    request: ThemeCreateRequest,
    admin: CurrentUser = Depends(get_admin_user),
) -> ThemeResponse:
    """Create a reusable theme (name + description). Admin only."""
    service = ThemeService()
    theme = service.create_theme(request=request, created_by=admin.user_id)
    return ThemeResponse(**theme)


@router.get("", response_model=list[ThemeResponse])
async def list_themes(
    current_user: CurrentUser = Depends(get_current_user),
) -> list[ThemeResponse]:
    """List all themes. Used for the multi-select when creating a hackathon."""
    service = ThemeService()
    themes = service.list_themes()
    return [ThemeResponse(**item) for item in themes]


@router.get("/{theme_id}", response_model=ThemeResponse)
async def get_theme(
    theme_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> ThemeResponse:
    """Get a single theme by id."""
    service = ThemeService()
    theme = service.get_theme(theme_id)
    if not theme:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Theme not found",
        )
    return ThemeResponse(**theme)


@router.patch("/{theme_id}", response_model=ThemeResponse)
async def update_theme(
    theme_id: str,
    request: ThemeUpdateRequest,
    admin: CurrentUser = Depends(get_admin_user),
) -> ThemeResponse:
    """Update a theme. Admin only."""
    service = ThemeService()
    theme = service.update_theme(theme_id, request)
    if not theme:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Theme not found",
        )
    return ThemeResponse(**theme)


@router.delete("/{theme_id}", status_code=200)
async def delete_theme(
    theme_id: str,
    admin: CurrentUser = Depends(get_admin_user),
) -> dict:
    """Delete a theme. Admin only."""
    service = ThemeService()
    deleted = service.delete_theme(theme_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Theme not found",
        )
    return {"message": "Theme deleted successfully"}
