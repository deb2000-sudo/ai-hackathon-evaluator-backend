"""
Hackathon routes.

    POST   /hackathons            -> admin creates a hackathon (multipart, banner optional)
    GET    /hackathons            -> list hackathons (any authenticated user)
    GET    /hackathons/{id}       -> get a single hackathon
    PATCH  /hackathons/{id}       -> admin updates a hackathon (multipart, banner optional)
    DELETE /hackathons/{id}       -> admin deletes a hackathon
"""

import json
import logging

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from pydantic import ValidationError

from app.middleware.auth_middleware import get_admin_user, get_current_user
from app.models.hackathon_model import (
    HackathonCreateRequest,
    HackathonPrizes,
    HackathonResponse,
    HackathonUpdateRequest,
    TimelineRound,
)
from app.models.theme_model import ThemeResponse
from app.models.user_model import CurrentUser
from app.services.hackathon_service import HackathonService


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/hackathons", tags=["hackathons"])


def _to_response(service: HackathonService, hackathon: dict) -> HackathonResponse:
    return HackathonResponse(**service.enrich_hackathon_for_response(hackathon))


def _parse_json_field(raw: str | None, field_name: str, default):
    if raw is None or raw.strip() == "":
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} must be valid JSON: {str(e)}",
        ) from e


async def _read_banner(banner: UploadFile | None) -> tuple[str, bytes, str] | None:
    if banner is None:
        return None
    payload = await banner.read()
    if not payload:
        return None
    return (banner.filename or "banner", payload, banner.content_type or "")


@router.post("", response_model=HackathonResponse, status_code=201)
async def create_hackathon(
    name: str = Form(..., min_length=1, max_length=200),
    description: str = Form(..., min_length=1, max_length=10000),
    start_date: str = Form(..., description="ISO date YYYY-MM-DD"),
    end_date: str = Form(..., description="ISO date YYYY-MM-DD"),
    guidelines: str = Form(..., min_length=1, max_length=10000),
    prizes: str = Form(
        ...,
        description='JSON: {"winner": "...", "first_runner_up": "...", "second_runner_up": "..."}',
    ),
    theme_ids: str = Form(
        ...,
        description='JSON array of theme ids, e.g. ["id1","id2"]',
    ),
    timeline: str | None = Form(
        None,
        description='JSON array: [{"title": "Round 1", "description": "...", '
        '"start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}]',
    ),
    banner: UploadFile | None = File(
        None, description="Optional hackathon banner image (jpeg/png/webp/gif)"
    ),
    admin: CurrentUser = Depends(get_admin_user),
) -> HackathonResponse:
    """
    Create a hackathon. Admin only.

    ``prizes``, ``theme_ids``, and ``timeline`` are sent as JSON strings within
    the multipart form; the banner image is an optional file part.
    """
    prizes_data = _parse_json_field(prizes, "prizes", {})
    theme_ids_data = _parse_json_field(theme_ids, "theme_ids", [])
    timeline_data = _parse_json_field(timeline, "timeline", [])

    try:
        payload = HackathonCreateRequest(
            name=name,
            description=description,
            start_date=start_date,
            end_date=end_date,
            guidelines=guidelines,
            theme_ids=theme_ids_data,
            prizes=HackathonPrizes(**prizes_data),
            timeline=[TimelineRound(**item) for item in timeline_data],
        )
    except (ValidationError, ValueError, TypeError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    banner_payload = await _read_banner(banner)

    try:
        service = HackathonService()
        hackathon = service.create_hackathon(
            request=payload,
            created_by=admin.user_id,
            banner=banner_payload,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.error("Hackathon creation failed: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create hackathon",
        ) from e

    return _to_response(service, hackathon)


@router.get("", response_model=list[HackathonResponse])
async def list_hackathons(
    current_user: CurrentUser = Depends(get_current_user),
) -> list[HackathonResponse]:
    """List all hackathons. Available to any authenticated user."""
    service = HackathonService()
    hackathons = service.list_hackathons()
    return [_to_response(service, item) for item in hackathons]


@router.get("/{hackathon_id}/themes", response_model=list[ThemeResponse])
async def list_hackathon_themes(
    hackathon_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> list[ThemeResponse]:
    """
    Themes released for this hackathon.

    Students use this list on the submission form to pick a theme.
    """
    service = HackathonService()
    themes = service.get_hackathon_themes(hackathon_id)
    if themes is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hackathon not found",
        )
    return [ThemeResponse(**item) for item in themes]


@router.get("/{hackathon_id}", response_model=HackathonResponse)
async def get_hackathon(
    hackathon_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> HackathonResponse:
    """Get a single hackathon by id (includes resolved ``themes``)."""
    service = HackathonService()
    hackathon = service.get_hackathon(hackathon_id)
    if not hackathon:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hackathon not found",
        )
    return _to_response(service, hackathon)


@router.patch("/{hackathon_id}", response_model=HackathonResponse)
async def update_hackathon(
    hackathon_id: str,
    name: str | None = Form(None, max_length=200),
    description: str | None = Form(None, max_length=10000),
    start_date: str | None = Form(None),
    end_date: str | None = Form(None),
    guidelines: str | None = Form(None, max_length=10000),
    prizes: str | None = Form(None),
    theme_ids: str | None = Form(None, description='JSON array of theme ids'),
    timeline: str | None = Form(None),
    banner: UploadFile | None = File(None),
    admin: CurrentUser = Depends(get_admin_user),
) -> HackathonResponse:
    """Update a hackathon (partial). Admin only."""
    prizes_data = _parse_json_field(prizes, "prizes", None)
    theme_ids_data = _parse_json_field(theme_ids, "theme_ids", None)
    timeline_data = _parse_json_field(timeline, "timeline", None)

    try:
        payload = HackathonUpdateRequest(
            name=name,
            description=description,
            start_date=start_date,
            end_date=end_date,
            guidelines=guidelines,
            theme_ids=theme_ids_data,
            prizes=HackathonPrizes(**prizes_data) if prizes_data is not None else None,
            timeline=(
                [TimelineRound(**item) for item in timeline_data]
                if timeline_data is not None
                else None
            ),
        )
    except (ValidationError, ValueError, TypeError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    banner_payload = await _read_banner(banner)

    try:
        service = HackathonService()
        hackathon = service.update_hackathon(
            hackathon_id=hackathon_id,
            request=payload,
            banner=banner_payload,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    if not hackathon:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hackathon not found",
        )

    return _to_response(service, hackathon)


@router.delete("/{hackathon_id}", status_code=200)
async def delete_hackathon(
    hackathon_id: str,
    admin: CurrentUser = Depends(get_admin_user),
) -> dict:
    """Delete a hackathon. Admin only."""
    service = HackathonService()
    deleted = service.delete_hackathon(hackathon_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hackathon not found",
        )
    return {"message": "Hackathon deleted successfully"}
