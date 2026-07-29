"""
Hackathon service — admin-created hackathons with banner storage in GCS.
"""

import logging
import os
import uuid
from datetime import datetime
from typing import Any

from google.cloud import storage

from app.models.hackathon_model import HackathonCreateRequest, HackathonUpdateRequest
from app.services.evaluation_requirement_service import EvaluationRequirementService
from app.services.firebase import FirebaseService
from app.services.theme_service import ThemeService
from app.utils.gcs_video import build_storage_client, generate_signed_url
from app.utils.image_upload import resolve_image_content_type


logger = logging.getLogger(__name__)


class HackathonService:
    """Creates and manages hackathons stored in the ``hackathons`` collection."""

    collection = "hackathons"

    def __init__(self):
        self.project = (
            os.getenv("GOOGLE_CLOUD_PROJECT")
            or os.getenv("FIREBASE_PROJECT_ID")
        )
        self.bucket_name = os.getenv("EVALUATION_BUCKET_NAME") or os.getenv("VIDEO_BUCKET_NAME")
        self.storage_client: storage.Client | None = None
        self.firebase = FirebaseService()
        self.evaluation_requirements = EvaluationRequirementService()
        self.theme_service = ThemeService()

    def create_hackathon(
        self,
        request: HackathonCreateRequest,
        created_by: str,
        banner: tuple[str, bytes, str] | None = None,
    ) -> dict[str, Any]:
        """Create a hackathon document, optionally uploading a banner image."""
        self._validate_round_requirement_links(request.timeline)
        theme_ids = self.theme_service.validate_theme_ids(request.theme_ids)

        hackathon_id = uuid.uuid4().hex
        now = datetime.utcnow().isoformat()

        banner_path = None
        if banner is not None:
            banner_path = self._upload_banner(hackathon_id, banner)

        hackathon = {
            "name": request.name.strip(),
            "description": request.description.strip(),
            "start_date": request.start_date,
            "end_date": request.end_date,
            "guidelines": request.guidelines.strip(),
            "theme_ids": theme_ids,
            "hackathon_url": request.hackathon_url,
            "timeline": [round_.model_dump() for round_ in request.timeline],
            "prizes": request.prizes.model_dump(),
            "banner_path": banner_path,
            "created_by": created_by,
            "created_at": now,
            "updated_at": now,
        }

        self.firebase.set_document(self.collection, hackathon_id, hackathon)
        return {"id": hackathon_id, **hackathon}

    def list_hackathons(self) -> list[dict[str, Any]]:
        """List all hackathons (most recent first)."""
        hackathons = self.firebase.get_collection(self.collection)
        hackathons.sort(key=lambda h: h.get("created_at", ""), reverse=True)
        return hackathons

    def get_hackathon(self, hackathon_id: str) -> dict[str, Any] | None:
        """Fetch a single hackathon by id."""
        hackathon = self.firebase.get_document(self.collection, hackathon_id)
        if not hackathon:
            return None
        return {"id": hackathon_id, **hackathon}

    def update_hackathon(
        self,
        hackathon_id: str,
        request: HackathonUpdateRequest,
        banner: tuple[str, bytes, str] | None = None,
    ) -> dict[str, Any] | None:
        """Apply a partial update to a hackathon, optionally replacing the banner."""
        existing = self.firebase.get_document(self.collection, hackathon_id)
        if not existing:
            return None

        update: dict[str, Any] = {}
        if request.name is not None:
            update["name"] = request.name.strip()
        if request.description is not None:
            update["description"] = request.description.strip()
        if request.start_date is not None:
            update["start_date"] = request.start_date
        if request.end_date is not None:
            update["end_date"] = request.end_date
        if request.guidelines is not None:
            update["guidelines"] = request.guidelines.strip()
        if request.theme_ids is not None:
            update["theme_ids"] = self.theme_service.validate_theme_ids(request.theme_ids)
        if "hackathon_url" in request.model_fields_set:
            # Explicitly sent (including cleared/empty → None) updates the URL.
            update["hackathon_url"] = request.hackathon_url
        if request.timeline is not None:
            self._validate_round_requirement_links(request.timeline)
            update["timeline"] = [round_.model_dump() for round_ in request.timeline]
        if request.prizes is not None:
            update["prizes"] = request.prizes.model_dump()
        if banner is not None:
            update["banner_path"] = self._upload_banner(hackathon_id, banner)

        # Validate the resulting date range if either date changed.
        start = update.get("start_date", existing.get("start_date"))
        end = update.get("end_date", existing.get("end_date"))
        if start and end and end < start:
            raise ValueError("end_date cannot be earlier than start_date")

        if update:
            update["updated_at"] = datetime.utcnow().isoformat()
            self.firebase.update_document(self.collection, hackathon_id, update)

        return self.get_hackathon(hackathon_id)

    def delete_hackathon(self, hackathon_id: str) -> bool:
        """Delete a hackathon document. Returns False if it does not exist."""
        existing = self.firebase.get_document(self.collection, hackathon_id)
        if not existing:
            return False
        self.firebase.delete_document(self.collection, hackathon_id)
        return True

    def enrich_hackathon_for_response(self, hackathon: dict[str, Any]) -> dict[str, Any]:
        """Attach signed banner URL and resolved theme objects."""
        enriched = dict(hackathon)
        enriched.setdefault("theme_ids", [])
        enriched.setdefault("hackathon_url", None)

        banner_path = enriched.get("banner_path")
        if banner_path:
            enriched["banner_url"] = generate_signed_url(
                self._get_storage_client(),
                banner_path,
            )
        else:
            enriched["banner_url"] = None

        theme_ids = enriched.get("theme_ids") or []
        themes = self.theme_service.get_themes_by_ids(theme_ids)
        enriched["themes"] = [
            {
                "id": theme["id"],
                "name": theme["name"],
                "description": theme["description"],
            }
            for theme in themes
        ]
        return enriched

    def enrich_hackathon_for_submission_summary(
        self, hackathon: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Lightweight enrich for Submissions-tab hackathon rows (Phase 7).

        Same fields the summary API needs (name/dates/banner_url) without
        resolving the full themes list.
        """
        enriched = dict(hackathon)
        banner_path = enriched.get("banner_path")
        if banner_path:
            enriched["banner_url"] = generate_signed_url(
                self._get_storage_client(),
                banner_path,
            )
        else:
            enriched["banner_url"] = None
        return enriched

    def get_hackathon_themes(self, hackathon_id: str) -> list[dict[str, Any]] | None:
        """Return themes released for a hackathon, or None if hackathon missing."""
        hackathon = self.get_hackathon(hackathon_id)
        if not hackathon:
            return None
        theme_ids = hackathon.get("theme_ids") or []
        return self.theme_service.get_themes_by_ids(theme_ids)

    def _upload_banner(self, hackathon_id: str, banner: tuple[str, bytes, str]) -> str:
        self._validate_configuration()
        filename, payload, content_type = banner
        resolved_type, extension = resolve_image_content_type(
            content_type,
            filename,
            payload,
        )
        object_name = f"hackathons/{hackathon_id}/banner{extension}"
        blob = self._get_storage_client().bucket(self.bucket_name).blob(object_name)
        blob.upload_from_string(payload, content_type=resolved_type)
        return f"gs://{self.bucket_name}/{object_name}"

    def _validate_round_requirement_links(self, timeline) -> None:
        """Ensure any evaluation_requirement_id linked to a round actually exists."""
        for index, round_ in enumerate(timeline or [], start=1):
            requirement_id = getattr(round_, "evaluation_requirement_id", None)
            if requirement_id and not self.evaluation_requirements.exists(requirement_id):
                raise ValueError(
                    f"Round {index} references an unknown evaluation requirement "
                    f"({requirement_id})"
                )

    def _validate_configuration(self) -> None:
        if not self.bucket_name:
            raise ValueError(
                "Banner storage is not configured (EVALUATION_BUCKET_NAME or VIDEO_BUCKET_NAME)"
            )

    def _get_storage_client(self) -> storage.Client:
        if self.storage_client is None:
            self.storage_client = build_storage_client(self.project)
        return self.storage_client
