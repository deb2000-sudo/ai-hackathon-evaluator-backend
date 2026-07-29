"""Evaluator submit-for-review and admin approve / request-changes."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any


logger = logging.getLogger(__name__)


class ReviewMixin:
    def submit_for_review(
        self,
        submission_id: str,
        evaluator_user_id: str,
        final_score: float,
        evaluator_notes: str | None = None,
    ) -> dict[str, Any]:
        """Assigned evaluator submits completed evaluation to admin."""
        notes = evaluator_notes.strip() if evaluator_notes else None
        now = datetime.utcnow().isoformat()

        def _txn(transaction):
            submission = self.firebase.txn_get(
                transaction, self.collection, submission_id
            )
            if not submission:
                raise ValueError("Submission not found")
            if submission.get("assigned_evaluator_id") != evaluator_user_id:
                raise ValueError("Only the assigned evaluator can submit this evaluation")
            if submission.get("status") != "completed":
                raise ValueError(
                    "AI analysis must be completed before submitting for review"
                )

            analysis_id = submission.get("analysis_id")
            if not analysis_id:
                raise ValueError("No analysis linked to this submission")
            analysis = self.firebase.txn_get(
                transaction, self.analysis_collection, analysis_id
            )
            if not analysis or analysis.get("status") != "completed":
                raise ValueError("Analysis report is not ready to submit")

            review_status = submission.get("review_status") or "none"
            if review_status == "pending_review":
                raise ValueError("Evaluation is already pending admin review")
            if review_status == "approved":
                raise ValueError(
                    "Evaluation is already approved; unpublish/request changes first"
                )

            update = {
                "review_status": "pending_review",
                "final_score": float(final_score),
                "evaluator_notes": notes,
                "submitted_for_review_at": now,
                "submitted_for_review_by": evaluator_user_id,
                # Keep unpublished until admin approves.
                "report_published": False,
                "published_at": None,
                "published_by": None,
                "reviewed_at": None,
                "reviewed_by": None,
                "review_notes": None,
                "updated_at": now,
            }
            self.firebase.txn_update(
                transaction, self.collection, submission_id, update
            )
            return {"id": submission_id, **submission, **update}

        return self.firebase.run_transaction(_txn)

    def approve_evaluation(
        self,
        submission_id: str,
        admin_user_id: str,
        final_score: float | None = None,
        review_notes: str | None = None,
    ) -> dict[str, Any]:
        """Admin approves evaluation → final score + report become visible to student."""
        notes = review_notes.strip() if review_notes else None
        now = datetime.utcnow().isoformat()

        def _txn(transaction):
            submission = self.firebase.txn_get(
                transaction, self.collection, submission_id
            )
            if not submission:
                raise ValueError("Submission not found")
            if submission.get("status") != "completed":
                raise ValueError("Can only approve a completed evaluation")

            review_status = submission.get("review_status") or "none"
            if review_status not in ("pending_review", "approved"):
                raise ValueError(
                    "Evaluation must be submitted for review before admin approval"
                )

            analysis_id = submission.get("analysis_id")
            if not analysis_id:
                raise ValueError("No analysis linked to this submission")
            analysis = self.firebase.txn_get(
                transaction, self.analysis_collection, analysis_id
            )
            if not analysis or analysis.get("status") != "completed":
                raise ValueError("Analysis report is not ready to approve")

            score = (
                final_score if final_score is not None else submission.get("final_score")
            )
            if score is None:
                raise ValueError(
                    "final_score is required to approve (evaluator did not propose one)"
                )

            update = {
                "review_status": "approved",
                "final_score": float(score),
                "review_notes": notes,
                "reviewed_at": now,
                "reviewed_by": admin_user_id,
                "report_published": True,
                "published_at": now,
                "published_by": admin_user_id,
                "updated_at": now,
            }
            self.firebase.txn_update(
                transaction, self.collection, submission_id, update
            )
            return {"id": submission_id, **submission, **update}

        return self.firebase.run_transaction(_txn)

    def request_evaluation_changes(
        self,
        submission_id: str,
        admin_user_id: str,
        review_notes: str | None = None,
    ) -> dict[str, Any]:
        """Admin sends evaluation back to the assigned evaluator."""
        notes = review_notes.strip() if review_notes else None
        now = datetime.utcnow().isoformat()

        def _txn(transaction):
            submission = self.firebase.txn_get(
                transaction, self.collection, submission_id
            )
            if not submission:
                raise ValueError("Submission not found")

            review_status = submission.get("review_status") or "none"
            if review_status not in ("pending_review", "approved"):
                raise ValueError("Only pending or approved evaluations can be sent back")

            update = {
                "review_status": "changes_requested",
                "review_notes": notes,
                "reviewed_at": now,
                "reviewed_by": admin_user_id,
                "report_published": False,
                "published_at": None,
                "published_by": None,
                "updated_at": now,
            }
            self.firebase.txn_update(
                transaction, self.collection, submission_id, update
            )
            return {"id": submission_id, **submission, **update}

        return self.firebase.run_transaction(_txn)

