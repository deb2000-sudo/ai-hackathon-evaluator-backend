"""Phase 0/3: characterize review workflow state transitions (transactional)."""

from unittest.mock import MagicMock, patch

import pytest

from app.services.submission_service import SubmissionService
from tests.conftest import make_submission_doc


@pytest.fixture
def service() -> SubmissionService:
    with patch.object(SubmissionService, "__init__", lambda self: None):
        svc = SubmissionService()
        svc.collection = "submissions"
        svc.analysis_collection = "analysis"
        svc.firebase = MagicMock()
        svc.user_service = MagicMock()
        svc.hackathon_service = MagicMock()
        svc.theme_service = MagicMock()
        svc.metric_scoring_service = MagicMock()
        svc.metric_scoring_service.get_scoring_for_requirement.return_value = None
        svc.bucket_name = "test-bucket"
        # Execute transactional callbacks immediately (no real Firestore).
        svc.firebase.run_transaction.side_effect = lambda cb: cb(MagicMock())
        return svc


def _doc_without_id(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k != "id"}


def _wire_reads(
    service: SubmissionService,
    submission: dict,
    analysis: dict | None = None,
) -> None:
    def txn_get(_txn, collection: str, _doc_id: str):
        if collection == service.analysis_collection:
            return analysis
        return submission

    service.firebase.txn_get.side_effect = txn_get


def test_submit_for_review_sets_pending_and_score(service: SubmissionService):
    base = make_submission_doc(status="completed", review_status="none")
    analysis = {"status": "completed", "report": "# ok", "checklist": "c"}
    _wire_reads(service, _doc_without_id(base), analysis)

    result = service.submit_for_review(
        submission_id="sub-1",
        evaluator_user_id="evaluator-1",
        final_score=82,
        evaluator_notes="Looks good",
    )

    service.firebase.txn_update.assert_called_once()
    payload = service.firebase.txn_update.call_args[0][3]
    assert payload["review_status"] == "pending_review"
    assert payload["final_score"] == 82.0
    assert payload["report_published"] is False
    assert payload["submitted_for_review_by"] == "evaluator-1"
    assert result["review_status"] == "pending_review"


def test_submit_for_review_rejects_non_assignee(service: SubmissionService):
    base = make_submission_doc(assigned_evaluator_id="evaluator-1")
    _wire_reads(service, _doc_without_id(base), {"status": "completed"})
    with pytest.raises(ValueError, match="assigned evaluator"):
        service.submit_for_review("sub-1", "other-eval", 50)


def test_submit_for_review_requires_completed_analysis(service: SubmissionService):
    base = make_submission_doc(status="uploaded")
    _wire_reads(service, _doc_without_id(base), {"status": "completed"})
    with pytest.raises(ValueError, match="completed"):
        service.submit_for_review("sub-1", "evaluator-1", 50)


def test_approve_evaluation_publishes_and_sets_approved(service: SubmissionService):
    base = make_submission_doc(
        status="completed",
        review_status="pending_review",
        final_score=80,
    )
    _wire_reads(service, _doc_without_id(base), {"status": "completed"})

    result = service.approve_evaluation(
        submission_id="sub-1",
        admin_user_id="admin-1",
        final_score=85,
        review_notes="Approved",
    )

    payload = service.firebase.txn_update.call_args[0][3]
    assert payload["review_status"] == "approved"
    assert payload["report_published"] is True
    assert payload["final_score"] == 85.0
    assert payload["published_by"] == "admin-1"
    assert result["report_published"] is True


def test_approve_requires_pending_or_approved(service: SubmissionService):
    base = make_submission_doc(status="completed", review_status="none")
    _wire_reads(service, _doc_without_id(base), {"status": "completed"})
    with pytest.raises(ValueError, match="submitted for review"):
        service.approve_evaluation("sub-1", "admin-1", final_score=70)


def test_request_changes_unpublishes(service: SubmissionService):
    base = make_submission_doc(
        review_status="pending_review",
        report_published=False,
        final_score=70,
    )
    _wire_reads(service, _doc_without_id(base))

    service.request_evaluation_changes("sub-1", "admin-1", review_notes="Fix scoring")
    payload = service.firebase.txn_update.call_args[0][3]
    assert payload["review_status"] == "changes_requested"
    assert payload["report_published"] is False
