"""
Super Admin Application Settings.

    GET  /super-admin/settings                         -> settings flags (sidebar page)
    POST /super-admin/settings/change-profile-password -> change Profile Password
    POST /super-admin/settings/reset-database          -> wipe app Firestore data

Admin and custom roles receive 403. The page and Reset Database stay the same
for Super Admin.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_app_settings_service
from app.exceptions import AppError
from app.middleware.auth_middleware import get_super_admin_user
from app.models.settings_model import (
    AppSettingsResponse,
    ChangeProfilePasswordRequest,
    ResetDatabaseRequest,
    ResetDatabaseResponse,
)
from app.models.user_model import CurrentUser
from app.services.app_settings_service import AppSettingsService
from app.utils.async_io import run_sync


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/super-admin/settings", tags=["super-admin-settings"])


@router.get("", response_model=AppSettingsResponse)
async def get_application_settings(
    super_admin: CurrentUser = Depends(get_super_admin_user),
    service: AppSettingsService = Depends(get_app_settings_service),
) -> AppSettingsResponse:
    """
    Application Settings page payload for Super Admin.

    Never returns the Profile Password itself — only configuration flags.
    """
    _ = super_admin
    payload = await run_sync(service.get_settings_public)
    return AppSettingsResponse(**payload)


@router.post("/change-profile-password", status_code=200)
async def change_profile_password(
    request: ChangeProfilePasswordRequest,
    super_admin: CurrentUser = Depends(get_super_admin_user),
    service: AppSettingsService = Depends(get_app_settings_service),
) -> dict:
    """
    Change the admin Profile Password (same UX pattern as ``/auth/change-password``).

    Requires the current Profile Password, then new + confirm. This password is
    separate from the Firebase login password and is used for destructive
    actions such as Reset Database.
    """
    try:
        await run_sync(
            service.change_profile_password,
            request.current_profile_password,
            request.new_profile_password,
            super_admin.user_id,
        )
    except ValueError as e:
        # 400, not 401. A wrong Profile Password is not an expired login, and
        # the SPA treats every 401 as "signed out".
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except AppError:
        raise
    except Exception as e:
        logger.exception("Change profile password failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to change profile password",
        ) from e

    return {"message": "Profile password changed successfully"}


@router.post("/reset-database", response_model=ResetDatabaseResponse)
async def reset_database(
    request: ResetDatabaseRequest,
    super_admin: CurrentUser = Depends(get_super_admin_user),
    service: AppSettingsService = Depends(get_app_settings_service),
) -> ResetDatabaseResponse:
    """
    Delete application documents from Firestore (hackathons, submissions, …).

    Requires a valid Profile Password and ``confirm_phrase: "RESET"``.
    Admin user accounts and the Profile Password setting are preserved.
    """
    try:
        result = await run_sync(
            service.reset_database,
            request.profile_password,
            preserve_user_id=super_admin.user_id,
            confirm_phrase=request.confirm_phrase,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except AppError:
        raise
    except Exception as e:
        logger.exception("Database reset failed for super admin %s", super_admin.user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reset database",
        ) from e

    return ResetDatabaseResponse(**result)
