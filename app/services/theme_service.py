"""
Theme service — admin-created reusable hackathon themes.
"""

import logging
import uuid
from datetime import datetime
from typing import Any

from app.models.theme_model import ThemeCreateRequest, ThemeUpdateRequest
from app.services.firebase import FirebaseService


logger = logging.getLogger(__name__)


class ThemeService:
    """Manages themes stored in the ``themes`` collection."""

    collection = "themes"

    def __init__(self):
        self.firebase = FirebaseService()

    def create_theme(
        self,
        request: ThemeCreateRequest,
        created_by: str,
    ) -> dict[str, Any]:
        """Create a theme document."""
        theme_id = uuid.uuid4().hex
        now = datetime.utcnow().isoformat()
        document = {
            "name": request.name.strip(),
            "description": request.description.strip(),
            "created_by": created_by,
            "created_at": now,
            "updated_at": now,
        }
        self.firebase.set_document(self.collection, theme_id, document)
        return {"id": theme_id, **document}

    def list_themes(self) -> list[dict[str, Any]]:
        """List all themes (newest first)."""
        themes = self.firebase.get_collection(self.collection)
        themes.sort(key=lambda t: t.get("created_at", ""), reverse=True)
        return themes

    def get_theme(self, theme_id: str) -> dict[str, Any] | None:
        """Fetch a single theme by id."""
        document = self.firebase.get_document(self.collection, theme_id)
        if not document:
            return None
        return {"id": theme_id, **document}

    def get_themes_by_ids(self, theme_ids: list[str]) -> list[dict[str, Any]]:
        """Fetch themes for the given ids (preserves input order; skips missing)."""
        themes: list[dict[str, Any]] = []
        for theme_id in theme_ids:
            theme = self.get_theme(theme_id)
            if theme:
                themes.append(theme)
        return themes

    def exists(self, theme_id: str) -> bool:
        return self.firebase.get_document(self.collection, theme_id) is not None

    def update_theme(
        self,
        theme_id: str,
        request: ThemeUpdateRequest,
    ) -> dict[str, Any] | None:
        """Apply a partial update to a theme."""
        existing = self.firebase.get_document(self.collection, theme_id)
        if not existing:
            return None

        update: dict[str, Any] = {}
        if request.name is not None:
            update["name"] = request.name.strip()
        if request.description is not None:
            update["description"] = request.description.strip()

        if update:
            update["updated_at"] = datetime.utcnow().isoformat()
            self.firebase.update_document(self.collection, theme_id, update)

        return self.get_theme(theme_id)

    def delete_theme(self, theme_id: str) -> bool:
        """Delete a theme. Returns False if it does not exist."""
        if not self.firebase.get_document(self.collection, theme_id):
            return False
        self.firebase.delete_document(self.collection, theme_id)
        return True

    def validate_theme_ids(self, theme_ids: list[str]) -> list[str]:
        """
        Ensure every theme id exists. Returns the cleaned unique list.
        Raises ValueError if any id is unknown.
        """
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in theme_ids:
            theme_id = (raw or "").strip()
            if not theme_id or theme_id in seen:
                continue
            if not self.exists(theme_id):
                raise ValueError(f"Unknown theme id: {theme_id}")
            seen.add(theme_id)
            cleaned.append(theme_id)

        if not cleaned:
            raise ValueError("At least one theme must be selected")
        return cleaned
