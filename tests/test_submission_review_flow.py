"""Phase 0: characterize review workflow state transitions."""

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
        svc.bucket_name = "test-bucket"
        return svc


def _doc_without_id(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k != "id"}


def test_submit_for_review_sets_pending_and_score(service: SubmissionService):
    base = make_submission_doc(status="completed", review_status="none")
    analysis = {"status": "completed", "report": "# ok", "checklist": "c"}

    def get_document(collection: str, doc_id: str):
        if collection == "analysis":
            return analysis
        return _doc_without_id(base)

    service.firebase.get_document.side_effect = get_document
    service._update_submission = MagicMock()

    # After update, return pending state
    updated = {**_doc_without_id(base), "review_status": "pending_review", "final_score": 82.0}
    service.firebase.get_document.side_effect = lambda c, i: (
        analysis if c == "analysis" else updated
    )

    # Re-setup: first calls need original, last get needs updated
    calls: list[tuple[str, str]] = []

    def get_doc(collection: str, doc_id: str):
        calls.append((collection, doc_id))
        if collection == service.analysis_collection:
            return analysis
        # After _update_submission was called, return updated
        if service._update_submission.called:
            return updated
        return _doc_without_id(base)

    service.firebase.get_document.side_effect = get_doc

    result = service.submit_for_review(
        submission_id="sub-1",
        evaluator_user_id="evaluator-1",
        final_score=82,
        evaluator_notes="Looks good",
    )

    service._update_submission.assert_called_once()
    payload = service._update_submission.call_args[0][1]
    assert payload["review_status"] == "pending_review"
    assert payload["final_score"] == 82.0
    assert payload["report_published"] is False
    assert payload["submitted_for_review_by"] == "evaluator-1"
    assert result["review_status"] == "pending_review"


def test_submit_for_review_rejects_non_assignee(service: SubmissionService):
    base = make_submission_doc(assigned_evaluator_id="evaluator-1")
    service.firebase.get_document.return_value = _doc_without_id(base)
    with pytest.raises(ValueError, match="assigned evaluator"):
        service.submit_for_review("sub-1", "other-eval", 50)


def test_submit_for_review_requires_completed_analysis(service: SubmissionService):
    base = make_submission_doc(status="uploaded")
    service.firebase.get_document.return_value = _doc_without_id(base)
    with pytest.raises(ValueError, match="completed"):
        service.submit_for_review("sub-1", "evaluator-1", 50)


def test_approve_evaluation_publishes_and_sets_approved(service: SubmissionService):
    base = make_submission_doc(
        status="completed",
        review_status="pending_review",
        final_score=80,
    )
    analysis = {"status": "completed"}
    service._update_submission = MagicMock()

    def get_doc(collection: str, doc_id: str):
        if collection == service.analysis_collection:
            return analysis
        if service._update_submission.called:
            return {
                **_doc_without_id(base),
                "review_status": "approved",
                "report_published": True,
                "final_score": 85.0,
            }
        return _doc_without_id(base)

    service.firebase.get_document.side_effect = get_doc

    result = service.approve_evaluation(
        submission_id="sub-1",
        admin_user_id="admin-1",
        final_score=85,
        review_notes="Approved",
    )

    payload = service._update_submission.call_args[0][1]
    assert payload["review_status"] == "approved"
    assert payload["report_published"] is True
    assert payload["final_score"] == 85.0
    assert payload["published_by"] == "admin-1"
    assert result["report_published"] is True


def test_approve_requires_pending_or_approved(service: SubmissionService):
    base = make_submission_doc(status="completed", review_status="none")
    analysis = {"status": "completed"}

    def get_doc(collection: str, doc_id: str):
        if collection == service.analysis_collection:
            return analysis
        return _doc_without_id(base)

    service.firebase.get_document.side_effect = get_doc
    with pytest.raises(ValueError, match="submitted for review"):
        service.approve_evaluation("sub-1", "admin-1", final_score=70)


def test_request_changes_unpublishes(service: SubmissionService):
    base = make_submission_doc(
        review_status="pending_review",
        report_published=False,
        final_score=70,
    )
    service.firebase.get_document.side_effect = lambda c, i: (
        {**_doc_without_id(base), "review_status": "changes_requested"}
        if service._update_submission.called
        else _doc_without_id(base)
    )
    service._update_submission = MagicMock()

    # Fix side_effect after mock assignment
    def get_doc(collection: str, doc_id: str):
        if service._update_submission.called:
            return {**_doc_without_id(base), "review_status": "changes_requested"}
        return _doc_without_id(base)

    service.firebase.get_document.side_effect = get_doc

    service.request_evaluation_changes("sub-1", "admin-1", review_notes="Fix scoring")
    payload = service._update_submission.call_args[0][1]
    assert payload["review_status"] == "changes_requested"
    assert payload["report_published"] is False
