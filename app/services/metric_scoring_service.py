"""
AI evaluation metric-scoring service.

Manages per-field scoring prompts linked to an evaluation requirement.
"""

import logging
import uuid
from datetime import datetime
from typing import Any

from app.models.metric_scoring_model import (
    FieldScoringMetric,
    MetricScoringCreateRequest,
    MetricScoringUpdateRequest,
)
from app.services.evaluation_requirement_service import EvaluationRequirementService
from app.services.firebase import FirebaseService


logger = logging.getLogger(__name__)


class MetricScoringService:
    """Creates and manages metric-scoring configs in ai_evaluation_metric_scoring."""

    collection = "ai_evaluation_metric_scoring"

    def __init__(
        self,
        firebase: FirebaseService | None = None,
        requirements: EvaluationRequirementService | None = None,
    ):
        self.firebase = firebase or FirebaseService()
        self.requirements = requirements or EvaluationRequirementService(
            firebase=self.firebase
        )

    def create_scoring(
        self,
        request: MetricScoringCreateRequest,
        created_by: str,
    ) -> dict[str, Any]:
        """Create a metric-scoring config linked to an evaluation requirement."""
        metrics = self._resolve_and_validate_metrics(
            request.evaluation_requirement_id,
            request.metrics,
        )

        if self._find_by_requirement(request.evaluation_requirement_id):
            raise ValueError(
                "A metric-scoring config already exists for this evaluation "
                "requirement. Use update instead."
            )

        scoring_id = uuid.uuid4().hex
        now = datetime.utcnow().isoformat()
        document = {
            "evaluation_requirement_id": request.evaluation_requirement_id,
            "name": (request.name or "").strip() or None,
            "metrics": metrics,
            "created_by": created_by,
            "created_at": now,
            "updated_at": now,
        }

        self.firebase.set_document(self.collection, scoring_id, document)
        return {"id": scoring_id, **document}

    def list_scoring(
        self, evaluation_requirement_id: str | None = None
    ) -> list[dict[str, Any]]:
        """List metric-scoring configs, optionally filtered by requirement."""
        if evaluation_requirement_id:
            documents = self.firebase.query_collection(
                self.collection,
                "evaluation_requirement_id",
                "==",
                evaluation_requirement_id,
            )
        else:
            documents = self.firebase.get_collection(self.collection)
        documents.sort(key=lambda d: d.get("created_at", ""), reverse=True)
        return documents

    def get_scoring(self, scoring_id: str) -> dict[str, Any] | None:
        """Fetch a single metric-scoring config by id."""
        document = self.firebase.get_document(self.collection, scoring_id)
        if not document:
            return None
        return {"id": scoring_id, **document}

    def update_scoring(
        self,
        scoring_id: str,
        request: MetricScoringUpdateRequest,
    ) -> dict[str, Any] | None:
        """Apply a partial update to a metric-scoring config."""
        existing = self.firebase.get_document(self.collection, scoring_id)
        if not existing:
            return None

        update: dict[str, Any] = {}
        if request.name is not None:
            update["name"] = request.name.strip() or None
        if request.metrics is not None:
            update["metrics"] = self._resolve_and_validate_metrics(
                existing["evaluation_requirement_id"],
                request.metrics,
            )

        if update:
            update["updated_at"] = datetime.utcnow().isoformat()
            self.firebase.update_document(self.collection, scoring_id, update)

        return self.get_scoring(scoring_id)

    def delete_scoring(self, scoring_id: str) -> bool:
        """Delete a metric-scoring config. Returns False if it does not exist."""
        if not self.firebase.get_document(self.collection, scoring_id):
            return False
        self.firebase.delete_document(self.collection, scoring_id)
        return True

    def _find_by_requirement(self, evaluation_requirement_id: str) -> dict[str, Any] | None:
        matches = self.firebase.query_collection(
            self.collection,
            "evaluation_requirement_id",
            "==",
            evaluation_requirement_id,
        )
        return matches[0] if matches else None

    def _resolve_and_validate_metrics(
        self,
        evaluation_requirement_id: str,
        metrics: list[FieldScoringMetric],
    ) -> list[dict[str, Any]]:
        """Validate metric field_keys against the requirement and snapshot labels."""
        requirement = self.requirements.get_requirement(evaluation_requirement_id)
        if not requirement:
            raise ValueError("Evaluation requirement not found")

        fields = requirement.get("fields") or []
        label_by_key = {f["key"]: f.get("label") for f in fields}
        valid_keys = set(label_by_key.keys())

        resolved: list[dict[str, Any]] = []
        for metric in metrics:
            if metric.field_key not in valid_keys:
                raise ValueError(
                    f"field_key '{metric.field_key}' is not a field of the linked "
                    f"evaluation requirement. Valid keys: {', '.join(sorted(valid_keys))}"
                )
            data = metric.model_dump()
            data["field_label"] = label_by_key.get(metric.field_key)
            resolved.append(data)

        return resolved
