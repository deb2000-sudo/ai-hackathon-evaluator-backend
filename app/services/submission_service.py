"""
Student submission service — video upload, storage, and AI analysis.
"""

import logging
import os
import uuid
from datetime import datetime
from typing import Any, BinaryIO

from google import genai
from google.cloud import storage
from google.genai import types
from google.oauth2 import service_account

from app.models.user_model import CurrentUser
from app.services.firebase import FirebaseService
from app.services.hackathon_service import HackathonService
from app.services.theme_service import ThemeService
from app.services.user_service import UserService
from app.utils.gcs_video import (
    build_video_streaming_response,
    generate_signed_upload_url,
    generate_signed_video_url,
    parse_gs_uri,
)
from app.utils.video_upload import (
    MAX_MULTIPART_VIDEO_BYTES,
    MAX_VIDEO_UPLOAD_BYTES,
    assert_video_size,
    peek_file_header,
    resolve_video_content_type,
    resolve_video_content_type_from_metadata,
)


logger = logging.getLogger(__name__)


CHECKLIST_PROMPT = """You are a product analyst. Based on the PROBLEM STATEMENT and SOLUTION
DESCRIPTION below, produce a "Product & Feature Validation Checklist" that
will later be used to evaluate whether a demo video properly showcases
this product.

Structure your output as a numbered checklist with clear sections, similar
to this style:

1. PROBLEM ESTABLISHMENT (The Pain Points)
- ...specific things the video should mention about the problem...

2. CORE SOLUTION / FEATURE DEMONSTRATION
- ...specific capabilities the video should visually demonstrate...

3. WORKFLOW / INTEGRATION
- ...how the solution should be shown working end-to-end...

4. VALUE PROPOSITION & BENCHMARKS
- ...explicit benefits/claims the video should confirm...

Adapt section names and bullet points to fit the specific product described
below (don't just copy the template above verbatim) — extract concrete,
checkable criteria a reviewer can verify against the video. Output plain
text only (no markdown headers like #, just numbered sections and bullets).

--- PROBLEM STATEMENT ---
{problem_statement}
--- END PROBLEM STATEMENT ---

--- SOLUTION DESCRIPTION ---
{solution_description}
--- END SOLUTION DESCRIPTION ---
"""


ANALYZE_VIDEO_PROMPT = """You are a video analysis agent. You have been given a video and a piece of
reference "context" (requirements, a script, guidelines, or a checklist).

Your job:
1. Watch/analyze the video content carefully (visuals, spoken/on-screen
   text, scenes, pacing, and overall narrative).
2. Compare what is actually present in the video against the CONTEXT below.
3. Produce a structured report in Markdown with these sections:

## Video Summary
A concise summary of what happens in the video.

## Key Content Identified
Bullet list of the key scenes, topics, claims, or elements present in the
video.

## Comparison Against Context
For each relevant point in the CONTEXT, state whether the video:
- Matches / Covers it (✅)
- Partially covers it (⚠️)
- Is missing it (❌)
Explain briefly why for each.

## Discrepancies & Issues
Anything in the video that contradicts, conflicts with, or deviates from
the context.

## Overall Assessment
A short verdict (e.g., compliant / non-compliant / needs revision) plus a
1-5 score with justification.

## Recommendations
Concrete, actionable suggestions to align the video with the context.

--- CONTEXT ---
{context}
--- END CONTEXT ---
"""


class SubmissionService:
    """Creates and tracks student-owned hackathon video submissions."""

    collection = "submissions"
    analysis_collection = "analysis"

    def __init__(self):
        self.project = (
            os.getenv("GOOGLE_CLOUD_PROJECT")
            or os.getenv("FIREBASE_PROJECT_ID")
            or ""
        )
        self.location = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
        self.bucket_name = os.getenv("EVALUATION_BUCKET_NAME") or os.getenv("VIDEO_BUCKET_NAME")
        self.model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
        self.use_enterprise = os.getenv("GEMINI_ENTERPRISE", "true").lower() in ("1", "true", "yes")
        self.storage_client: storage.Client | None = None
        self.firebase = FirebaseService()
        self.user_service = UserService()
        self.hackathon_service = HackathonService()
        self.theme_service = ThemeService()

    def create_submission(
        self,
        student: CurrentUser,
        video: tuple[str, bytes | BinaryIO, str],
        problem_statement: str,
        solution_description: str,
        hackathon_id: str,
        theme_id: str,
        video_source: str | None = None,
    ) -> dict[str, Any]:
        """Upload a student video and create a submission document."""
        self._validate_configuration()

        hackathon = self.hackathon_service.get_hackathon(hackathon_id.strip())
        if not hackathon:
            raise ValueError("Hackathon not found")

        theme_id = theme_id.strip()
        released_theme_ids = hackathon.get("theme_ids") or []
        if theme_id not in released_theme_ids:
            raise ValueError(
                "Selected theme is not released for this hackathon. "
                "Choose a theme from the hackathon's theme list."
            )

        theme = self.theme_service.get_theme(theme_id)
        if not theme:
            raise ValueError("Theme not found")

        team_name = self._resolve_student_team_name(student.user_id)

        filename, video_payload, content_type = video
        if isinstance(video_payload, (bytes, bytearray)):
            video_bytes = bytes(video_payload)
            assert_video_size(
                len(video_bytes),
                max_bytes=MAX_MULTIPART_VIDEO_BYTES,
                via="multipart",
            )
            resolved_type, extension = resolve_video_content_type(
                content_type,
                filename,
                video_bytes,
            )
            upload_target: bytes | BinaryIO = video_bytes
        else:
            fileobj = video_payload
            fileobj.seek(0, 2)
            size = fileobj.tell()
            fileobj.seek(0)
            assert_video_size(
                size,
                max_bytes=MAX_MULTIPART_VIDEO_BYTES,
                via="multipart",
            )
            header = peek_file_header(fileobj)
            resolved_type, extension = resolve_video_content_type(
                content_type,
                filename,
                header,
            )
            upload_target = fileobj

        submission_id = uuid.uuid4().hex
        now = datetime.utcnow().isoformat()
        object_name = (
            f"submissions/{student.user_id}/{submission_id}/video{extension}"
        )
        video_path = f"gs://{self.bucket_name}/{object_name}"

        if isinstance(upload_target, (bytes, bytearray)):
            self._upload_bytes(object_name, bytes(upload_target), resolved_type)
        else:
            self._upload_fileobj(object_name, upload_target, resolved_type)

        source = video_source if video_source in ("recorded", "uploaded") else None

        submission = {
            "student_id": student.user_id,
            "hackathon_id": hackathon_id.strip(),
            "hackathon_name": hackathon["name"],
            "team_name": team_name,
            "theme_id": theme_id,
            "theme_name": theme["name"],
            "problem_statement": problem_statement.strip(),
            "solution_description": solution_description.strip(),
            "evaluation_criteria": None,
            "status": "uploaded",
            "video_path": video_path,
            "content_type": resolved_type,
            "source_filename": filename,
            "video_source": source,
            "analysis_id": None,
            "report_published": False,
            "published_at": None,
            "published_by": None,
            "assigned_evaluator_id": None,
            "assigned_evaluator_name": None,
            "assigned_at": None,
            "assigned_by": None,
            "analyzed_by": None,
            "review_status": "none",
            "final_score": None,
            "evaluator_notes": None,
            "submitted_for_review_at": None,
            "submitted_for_review_by": None,
            "reviewed_at": None,
            "reviewed_by": None,
            "review_notes": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
        }

        self.firebase.set_document(self.collection, submission_id, submission)
        return {
            "id": submission_id,
            **submission,
            "message": (
                "Your submission has been recorded successfully. "
                "You will receive the evaluation result once an evaluator finishes "
                "review and the admin approves the final score."
            ),
        }

    def prepare_direct_upload(
        self,
        student: CurrentUser,
        filename: str,
        content_type: str | None = None,
        video_source: str | None = None,
    ) -> dict[str, Any]:
        """
        Mint a signed PUT URL so the browser uploads the video straight to GCS.

        Works for both in-browser recordings and local file picks. Avoids Cloud
        Run's HTTP/1 32 MiB request-body limit (413 Content Too Large).
        """
        self._validate_configuration()

        resolved_type, extension = resolve_video_content_type_from_metadata(
            content_type,
            filename,
        )
        submission_id = uuid.uuid4().hex
        object_name = (
            f"submissions/{student.user_id}/{submission_id}/video{extension}"
        )
        video_path = f"gs://{self.bucket_name}/{object_name}"
        expires_in = int(os.getenv("VIDEO_UPLOAD_URL_EXPIRY_SECONDS", "1800"))
        source = video_source if video_source in ("recorded", "uploaded") else None

        upload_url = generate_signed_upload_url(
            self._storage_client(),
            self.bucket_name,
            object_name,
            resolved_type,
            expiry_seconds=expires_in,
        )

        return {
            "upload_url": upload_url,
            "video_path": video_path,
            "object_name": object_name,
            "content_type": resolved_type,
            "source_filename": filename,
            "video_source": source,
            "expires_in_seconds": expires_in,
            "max_upload_bytes": MAX_VIDEO_UPLOAD_BYTES,
        }

    def create_submission_from_upload(
        self,
        student: CurrentUser,
        video_path: str,
        content_type: str,
        source_filename: str,
        problem_statement: str,
        solution_description: str,
        hackathon_id: str,
        theme_id: str,
        video_source: str | None = None,
    ) -> dict[str, Any]:
        """Create a submission after the video was uploaded via signed URL."""
        self._validate_configuration()

        hackathon = self.hackathon_service.get_hackathon(hackathon_id.strip())
        if not hackathon:
            raise ValueError("Hackathon not found")

        theme_id = theme_id.strip()
        released_theme_ids = hackathon.get("theme_ids") or []
        if theme_id not in released_theme_ids:
            raise ValueError(
                "Selected theme is not released for this hackathon. "
                "Choose a theme from the hackathon's theme list."
            )

        theme = self.theme_service.get_theme(theme_id)
        if not theme:
            raise ValueError("Theme not found")

        resolved_type, extension = resolve_video_content_type_from_metadata(
            content_type,
            source_filename,
        )

        video_path = video_path.strip()
        try:
            bucket_name, object_name = parse_gs_uri(video_path)
        except ValueError as e:
            raise ValueError("Invalid video_path") from e

        expected_prefix = f"submissions/{student.user_id}/"
        if bucket_name != self.bucket_name:
            raise ValueError("video_path does not belong to the evaluation bucket")
        if not object_name.startswith(expected_prefix):
            raise ValueError("video_path is not owned by the current student")
        if not object_name.endswith(f"/video{extension}"):
            raise ValueError("video_path does not match the expected upload object")

        blob = self._storage_client().bucket(bucket_name).blob(object_name)
        if not blob.exists():
            raise ValueError(
                "Video has not been uploaded yet. "
                "PUT the file to the signed upload_url first."
            )
        blob.reload()
        size = int(blob.size or 0)
        assert_video_size(size, max_bytes=MAX_VIDEO_UPLOAD_BYTES, via="signed")

        # Prefer the path segment as the stable submission id.
        parts = object_name.split("/")
        # submissions/{student_id}/{submission_id}/video.ext
        submission_id = parts[2] if len(parts) >= 4 else uuid.uuid4().hex

        existing = self.firebase.get_document(self.collection, submission_id)
        if existing:
            raise ValueError("A submission already exists for this uploaded video")

        team_name = self._resolve_student_team_name(student.user_id)
        now = datetime.utcnow().isoformat()
        source = video_source if video_source in ("recorded", "uploaded") else None

        submission = {
            "student_id": student.user_id,
            "hackathon_id": hackathon_id.strip(),
            "hackathon_name": hackathon["name"],
            "team_name": team_name,
            "theme_id": theme_id,
            "theme_name": theme["name"],
            "problem_statement": problem_statement.strip(),
            "solution_description": solution_description.strip(),
            "evaluation_criteria": None,
            "status": "uploaded",
            "video_path": video_path,
            "content_type": resolved_type,
            "source_filename": source_filename,
            "video_source": source,
            "analysis_id": None,
            "report_published": False,
            "published_at": None,
            "published_by": None,
            "assigned_evaluator_id": None,
            "assigned_evaluator_name": None,
            "assigned_at": None,
            "assigned_by": None,
            "analyzed_by": None,
            "review_status": "none",
            "final_score": None,
            "evaluator_notes": None,
            "submitted_for_review_at": None,
            "submitted_for_review_by": None,
            "reviewed_at": None,
            "reviewed_by": None,
            "review_notes": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
        }

        self.firebase.set_document(self.collection, submission_id, submission)
        return {
            "id": submission_id,
            **submission,
            "message": (
                "Your submission has been recorded successfully. "
                "You will receive the evaluation result once an evaluator finishes "
                "review and the admin approves the final score."
            ),
        }

    def mark_queued_for_evaluation(
        self,
        submission_id: str,
        evaluation_criteria: str | None = None,
        analyzed_by: str | None = None,
    ) -> str:
        """
        Create an analysis document and link it to the submission.

        Uses a Firestore transaction so two concurrent evaluate calls cannot
        both move the same submission into ``processing`` / overwrite analysis_id.
        """
        analysis_id = uuid.uuid4().hex
        now = datetime.utcnow().isoformat()
        criteria = evaluation_criteria.strip() if evaluation_criteria else None

        def _txn(transaction):
            submission = self.firebase.txn_get(
                transaction, self.collection, submission_id
            )
            if not submission:
                raise ValueError("Submission not found")
            if submission.get("status") == "processing":
                raise ValueError("This submission is already being analyzed")

            analysis_doc = {
                "submission_id": submission_id,
                "student_id": submission["student_id"],
                "status": "processing",
                "evaluation_criteria": criteria,
                "checklist": None,
                "report": None,
                "analyzed_at": None,
                "error": None,
                "created_at": now,
                "updated_at": now,
            }
            self.firebase.txn_set(
                transaction, self.analysis_collection, analysis_id, analysis_doc
            )

            submission_update: dict[str, Any] = {
                "analysis_id": analysis_id,
                "status": "processing",
                "error": None,
                "analyzed_by": analyzed_by,
                "report_published": False,
                "published_at": None,
                "published_by": None,
                "review_status": "none",
                "final_score": None,
                "evaluator_notes": None,
                "submitted_for_review_at": None,
                "submitted_for_review_by": None,
                "reviewed_at": None,
                "reviewed_by": None,
                "review_notes": None,
                "updated_at": now,
            }
            if evaluation_criteria is not None:
                submission_update["evaluation_criteria"] = criteria

            self.firebase.txn_update(
                transaction, self.collection, submission_id, submission_update
            )
            return analysis_id

        return self.firebase.run_transaction(_txn)

    def evaluate_submission(
        self,
        submission_id: str,
        evaluation_criteria: str | None = None,
    ) -> None:
        """Run Gemini video analysis for a submission (background task)."""
        analysis_id: str | None = None
        try:
            submission = self.firebase.get_document(self.collection, submission_id)
            if not submission:
                logger.error("Submission not found: %s", submission_id)
                return

            analysis_id = submission.get("analysis_id")
            if not analysis_id:
                raise ValueError("No analysis document linked to this submission")

            problem = (submission.get("problem_statement") or "").strip()
            solution = (submission.get("solution_description") or "").strip()
            video_uri = submission.get("video_path")
            content_type = submission.get("content_type", "video/mp4")

            if not problem or not solution:
                raise ValueError("Submission is missing problem statement or solution description")
            if not video_uri:
                raise ValueError("Submission is missing video_path (GCS URI)")

            client = self._build_genai_client()

            logger.info("Generating validation checklist for submission %s", submission_id)
            checklist = self._generate_checklist(client, problem, solution)

            extra_criteria = evaluation_criteria or submission.get("evaluation_criteria")
            if extra_criteria and extra_criteria.strip():
                checklist = (
                    checklist
                    + "\n\n--- ADDITIONAL EVALUATION FOCUS ---\n"
                    + extra_criteria.strip()
                )

            logger.info("Analyzing video for submission %s: %s", submission_id, video_uri)
            report = self._analyze_video(
                client=client,
                video_uri=video_uri,
                content_type=content_type,
                context=checklist,
            )

            analyzed_at = datetime.utcnow().isoformat()
            self._commit_analysis_and_submission(
                analysis_id,
                submission_id,
                analysis_data={
                    "status": "completed",
                    "checklist": checklist,
                    "report": report,
                    "analyzed_at": analyzed_at,
                    "error": None,
                },
                submission_data={
                    "status": "completed",
                    "error": None,
                },
            )
            logger.info("Analysis %s completed for submission %s", analysis_id, submission_id)

        except Exception as e:
            logger.error("Analysis failed for submission %s: %s", submission_id, str(e))
            self._commit_analysis_and_submission(
                analysis_id,
                submission_id,
                analysis_data={"status": "failed", "error": str(e)} if analysis_id else None,
                submission_data={"status": "failed", "error": str(e)},
            )

    def get_submission(
        self,
        submission_id: str,
        current_user: CurrentUser,
    ) -> dict[str, Any] | None:
        """
        Fetch a submission for the owner, assigned evaluator, or an admin.

        Evaluators may only access submissions assigned to them.
        """
        submission = self.firebase.get_document(self.collection, submission_id)
        if not submission:
            return None

        if current_user.role == "admin":
            return {"id": submission_id, **submission}

        if submission.get("student_id") == current_user.user_id:
            return {"id": submission_id, **submission}

        if current_user.role == "evaluator":
            if submission.get("assigned_evaluator_id") == current_user.user_id:
                return {"id": submission_id, **submission}
            return None

        return None

    def assert_can_evaluate(
        self,
        submission: dict[str, Any],
        current_user: CurrentUser,
    ) -> None:
        """Admin, or the assigned evaluator, may start AI analysis."""
        if current_user.role == "admin":
            return
        if (
            current_user.role == "evaluator"
            and submission.get("assigned_evaluator_id") == current_user.user_id
        ):
            return
        raise ValueError("Only the assigned evaluator or an admin can evaluate this submission")

    def list_submissions_for_hackathon(
        self,
        hackathon_id: str,
        evaluator_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List submissions for a hackathon. Newest first. Optionally filter by assignee."""
        submissions = self.firebase.query_collection(
            self.collection,
            "hackathon_id",
            "==",
            hackathon_id.strip(),
        )
        if evaluator_id:
            submissions = [
                item
                for item in submissions
                if item.get("assigned_evaluator_id") == evaluator_id
            ]
        submissions.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return submissions

    def list_hackathons_with_submission_counts(
        self,
        evaluator_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Submissions tab: hackathons plus submission counts.

        When ``evaluator_id`` is set, only include hackathons that have at least
        one submission assigned to that evaluator, and count only those.
        """
        hackathons = self.hackathon_service.list_hackathons()

        # Phase 7: scoped query for evaluators; avoid loading themes on summary rows.
        if evaluator_id:
            submissions = self.firebase.query_collection(
                self.collection,
                "assigned_evaluator_id",
                "==",
                evaluator_id,
            )
        else:
            submissions = self.firebase.get_collection(self.collection)

        counts: dict[str, int] = {}
        for submission in submissions:
            hid = submission.get("hackathon_id")
            if not hid:
                continue
            counts[hid] = counts.get(hid, 0) + 1

        summaries: list[dict[str, Any]] = []
        for hackathon in hackathons:
            enriched = self.hackathon_service.enrich_hackathon_for_submission_summary(
                hackathon
            )
            count = counts.get(enriched["id"], 0)
            if evaluator_id and count == 0:
                continue
            summaries.append(
                {
                    "hackathon_id": enriched["id"],
                    "name": enriched["name"],
                    "start_date": enriched["start_date"],
                    "end_date": enriched["end_date"],
                    "submission_count": count,
                    "banner_url": enriched.get("banner_url"),
                }
            )
        return summaries

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

    def get_analysis(
        self,
        analysis_id: str,
        current_user: CurrentUser,
    ) -> dict[str, Any] | None:
        """Fetch an analysis document if the user may access its submission."""
        analysis = self.firebase.get_document(self.analysis_collection, analysis_id)
        if not analysis:
            return None

        submission = self.get_submission(analysis["submission_id"], current_user)
        if not submission:
            return None

        return {"id": analysis_id, **analysis}

    def get_analysis_for_submission(
        self,
        submission_id: str,
        current_user: CurrentUser,
    ) -> dict[str, Any] | None:
        """Fetch the linked analysis document for a submission."""
        submission = self.get_submission(submission_id, current_user)
        if not submission:
            return None

        analysis_id = submission.get("analysis_id")
        if analysis_id:
            analysis = self.firebase.get_document(self.analysis_collection, analysis_id)
            if analysis:
                return {"id": analysis_id, **analysis}

        # Legacy submissions may still have embedded analysis data.
        if submission.get("analysis"):
            legacy = submission["analysis"]
            return {
                "id": analysis_id or submission_id,
                "submission_id": submission_id,
                "student_id": submission["student_id"],
                "status": submission.get("status", "completed"),
                **legacy,
            }

        return None

    def list_student_submissions(self, student_id: str) -> list[dict[str, Any]]:
        """List all submissions for a student."""
        submissions = self.firebase.query_collection(
            self.collection,
            "student_id",
            "==",
            student_id,
        )
        return submissions

    def list_all_submissions(self) -> list[dict[str, Any]]:
        """List every submission (admin review queue). Newest first."""
        submissions = self.firebase.get_collection(self.collection)
        submissions.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return submissions

    def list_submissions_for_evaluator(self, evaluator_id: str) -> list[dict[str, Any]]:
        """List submissions assigned to a given evaluator. Newest first."""
        submissions = self.firebase.query_collection(
            self.collection,
            "assigned_evaluator_id",
            "==",
            evaluator_id,
        )
        submissions.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return submissions

    def assign_evaluator(
        self,
        submission_id: str,
        evaluator_id: str | None,
        assigned_by: str,
    ) -> dict[str, Any]:
        """Assign one approved evaluator to a submission, or clear the assignment."""
        # User lookup stays outside the transaction (different collection / service).
        evaluator: dict[str, Any] | None = None
        if evaluator_id is not None and str(evaluator_id).strip():
            evaluator = self._require_active_evaluator(evaluator_id.strip())

        now = datetime.utcnow().isoformat()

        def _txn(transaction):
            submission = self.firebase.txn_get(
                transaction, self.collection, submission_id
            )
            if not submission:
                raise ValueError("Submission not found")

            if evaluator is None:
                update = {
                    "assigned_evaluator_id": None,
                    "assigned_evaluator_name": None,
                    "assigned_at": None,
                    "assigned_by": None,
                    "review_status": "none",
                    "submitted_for_review_at": None,
                    "submitted_for_review_by": None,
                    "updated_at": now,
                }
            else:
                update = {
                    "assigned_evaluator_id": evaluator["id"],
                    "assigned_evaluator_name": evaluator["name"],
                    "assigned_at": now,
                    "assigned_by": assigned_by,
                    # Reassignment clears in-flight review submission.
                    "review_status": "none",
                    "submitted_for_review_at": None,
                    "submitted_for_review_by": None,
                    "updated_at": now,
                }

            self.firebase.txn_update(
                transaction, self.collection, submission_id, update
            )
            return {"id": submission_id, **submission, **update}

        return self.firebase.run_transaction(_txn)

    def divide_equally_among_evaluators(
        self,
        hackathon_id: str,
        submission_ids: list[str],
        assigned_by: str,
        evaluator_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Shuffle the selected submissions and assign them round-robin to active
        evaluators so the load is roughly equal.
        """
        import random

        hackathon = self.hackathon_service.get_hackathon(hackathon_id)
        if not hackathon:
            raise ValueError("Hackathon not found")

        unique_ids = list(dict.fromkeys(sid.strip() for sid in submission_ids if sid.strip()))
        if not unique_ids:
            raise ValueError("At least one submission id is required")

        submissions: list[dict[str, Any]] = []
        for submission_id in unique_ids:
            submission = self.firebase.get_document(self.collection, submission_id)
            if not submission:
                raise ValueError(f"Submission not found: {submission_id}")
            if submission.get("hackathon_id") != hackathon_id:
                raise ValueError(
                    f"Submission {submission_id} does not belong to this hackathon"
                )
            submissions.append({"id": submission_id, **submission})

        evaluators = self._resolve_active_evaluators(evaluator_ids)
        if not evaluators:
            raise ValueError("No active (approved) evaluators available to assign")

        random.shuffle(submissions)
        random.shuffle(evaluators)

        now = datetime.utcnow().isoformat()
        operations: list[dict[str, Any]] = []
        planned: list[dict[str, Any]] = []
        for index, submission in enumerate(submissions):
            evaluator = evaluators[index % len(evaluators)]
            update = {
                "assigned_evaluator_id": evaluator["id"],
                "assigned_evaluator_name": evaluator["name"],
                "assigned_at": now,
                "assigned_by": assigned_by,
                "updated_at": now,
            }
            operations.append(
                {
                    "type": "update",
                    "collection": self.collection,
                    "document_id": submission["id"],
                    "data": update,
                }
            )
            planned.append({"id": submission["id"], **submission, **update})

        if operations:
            self.firebase.batch_write(operations)

        return planned

    def _require_active_evaluator(self, evaluator_id: str) -> dict[str, Any]:
        user = self.user_service.get_user(evaluator_id)
        if not user or user.get("role") != "evaluator":
            raise ValueError("Evaluator not found")
        if user.get("approval_status") != "approved":
            raise ValueError("Evaluator is not active (must be approved)")
        return {
            "id": evaluator_id,
            "name": user.get("name") or user.get("email") or evaluator_id,
        }

    def _resolve_active_evaluators(
        self, evaluator_ids: list[str] | None
    ) -> list[dict[str, Any]]:
        approved = self.user_service.get_evaluators(approval_status="approved")
        by_id = {item["id"]: item for item in approved if item.get("id")}

        if evaluator_ids is None:
            return [
                {
                    "id": item["id"],
                    "name": item.get("name") or item.get("email") or item["id"],
                }
                for item in approved
                if item.get("id")
            ]

        resolved: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in evaluator_ids:
            eid = (raw or "").strip()
            if not eid or eid in seen:
                continue
            if eid not in by_id:
                raise ValueError(f"Evaluator is not active/approved: {eid}")
            item = by_id[eid]
            resolved.append(
                {
                    "id": eid,
                    "name": item.get("name") or item.get("email") or eid,
                }
            )
            seen.add(eid)
        return resolved

    def publish_report(
        self,
        submission_id: str,
        publish: bool,
        admin_user_id: str,
    ) -> dict[str, Any]:
        """Publish or unpublish the analysis report for student viewing."""
        submission = self.firebase.get_document(self.collection, submission_id)
        if not submission:
            raise ValueError("Submission not found")

        if publish:
            if submission.get("status") != "completed":
                raise ValueError(
                    "Report can only be published after analysis has completed"
                )
            analysis_id = submission.get("analysis_id")
            if not analysis_id:
                raise ValueError("No analysis linked to this submission")
            analysis = self.firebase.get_document(self.analysis_collection, analysis_id)
            if not analysis or analysis.get("status") != "completed":
                raise ValueError("Analysis report is not ready to publish")

            self._update_submission(
                submission_id,
                {
                    "report_published": True,
                    "published_at": datetime.utcnow().isoformat(),
                    "published_by": admin_user_id,
                },
            )
        else:
            self._update_submission(
                submission_id,
                {
                    "report_published": False,
                    "published_at": None,
                    "published_by": None,
                },
            )

        updated = self.firebase.get_document(self.collection, submission_id)
        if not updated:
            raise ValueError("Submission not found")
        return {"id": submission_id, **updated}

    def student_can_view_report(self, submission: dict[str, Any]) -> bool:
        """Students may only see the report after an admin publishes it."""
        return bool(submission.get("report_published"))

    def enrich_submission_for_response(
        self,
        submission: dict[str, Any],
        current_user: CurrentUser | None = None,
        *,
        analysis_by_id: dict[str, dict[str, Any]] | None = None,
        storage_client: Any | None = None,
        check_video_exists: bool = False,
    ) -> dict[str, Any]:
        """Attach a browser-playable HTTPS URL alongside the internal gs:// path."""
        enriched = dict(submission)
        enriched.setdefault("report_published", False)
        enriched.setdefault("assigned_evaluator_id", None)
        enriched.setdefault("assigned_evaluator_name", None)
        enriched.setdefault("assigned_at", None)
        enriched.setdefault("assigned_by", None)
        enriched.setdefault("analyzed_by", None)
        enriched.setdefault("review_status", "none")
        enriched.setdefault("final_score", None)
        enriched.setdefault("evaluator_notes", None)
        enriched.setdefault("submitted_for_review_at", None)
        enriched.setdefault("submitted_for_review_by", None)
        enriched.setdefault("reviewed_at", None)
        enriched.setdefault("reviewed_by", None)
        enriched.setdefault("review_notes", None)
        enriched.setdefault("video_source", None)

        # Backfill hackathon fields for older submissions that predate the link.
        if not enriched.get("hackathon_id"):
            enriched["hackathon_id"] = ""
        if not enriched.get("hackathon_name"):
            enriched["hackathon_name"] = "Unknown hackathon"
            if enriched["hackathon_id"]:
                hackathon = self.hackathon_service.get_hackathon(enriched["hackathon_id"])
                if hackathon:
                    enriched["hackathon_name"] = hackathon.get("name", "Unknown hackathon")

        # Migrate legacy theme_chosen → theme_name for older submissions.
        if not enriched.get("theme_id"):
            enriched["theme_id"] = ""
        if not enriched.get("theme_name"):
            enriched["theme_name"] = enriched.get("theme_chosen") or "Unknown theme"
            if enriched["theme_id"]:
                theme = self.theme_service.get_theme(enriched["theme_id"])
                if theme:
                    enriched["theme_name"] = theme.get("name", "Unknown theme")

        if not enriched.get("team_name"):
            enriched["team_name"] = enriched.get("title")
        if not enriched.get("team_name"):
            profile = self.user_service.get_user(enriched.get("student_id", ""))
            if profile:
                enriched["team_name"] = profile.get("team_name")

        video_path = enriched.get("video_path")
        if video_path:
            client = storage_client or self._storage_client()
            enriched["video_url"] = generate_signed_video_url(
                client,
                video_path,
                check_exists=check_video_exists,
            )
        else:
            enriched["video_url"] = None

        is_staff = bool(
            current_user and current_user.role in ("admin", "evaluator")
        )
        can_see_analysis = is_staff or self.student_can_view_report(enriched)

        analysis_id = enriched.get("analysis_id")
        if can_see_analysis and analysis_id:
            if analysis_by_id is not None:
                analysis_doc = analysis_by_id.get(analysis_id)
            else:
                analysis_doc = self.firebase.get_document(
                    self.analysis_collection, analysis_id
                )
            if analysis_doc and analysis_doc.get("status") == "completed":
                enriched["analysis"] = {
                    "id": analysis_id,
                    "checklist": analysis_doc["checklist"],
                    "report": analysis_doc["report"],
                    "analyzed_at": analysis_doc["analyzed_at"],
                }
        elif can_see_analysis and enriched.get("analysis") and isinstance(
            enriched["analysis"], dict
        ):
            legacy = enriched["analysis"]
            if "id" not in legacy:
                enriched["analysis"] = {
                    **legacy,
                    "id": enriched.get("analysis_id") or enriched["id"],
                }
        else:
            # Hide analysis content from students until the admin publishes.
            enriched["analysis"] = None

        if not can_see_analysis:
            enriched["final_score"] = None
            enriched["evaluator_notes"] = None
            enriched["review_notes"] = None

        return enriched

    def enrich_submissions_for_response(
        self,
        submissions: list[dict[str, Any]],
        current_user: CurrentUser | None = None,
    ) -> list[dict[str, Any]]:
        """
        Batch-enrich a submission list (Phase 7).

        Same JSON as calling ``enrich_submission_for_response`` per item, but
        analysis docs are fetched in one Firestore batch and one GCS client is
        reused for signed URLs.
        """
        if not submissions:
            return []

        is_staff = bool(
            current_user and current_user.role in ("admin", "evaluator")
        )
        analysis_ids: list[str] = []
        for submission in submissions:
            analysis_id = submission.get("analysis_id")
            if not analysis_id:
                continue
            if is_staff or self.student_can_view_report(submission):
                analysis_ids.append(analysis_id)

        analysis_by_id = self.firebase.get_documents(
            self.analysis_collection, analysis_ids
        )
        storage_client = self._storage_client()

        return [
            self.enrich_submission_for_response(
                submission,
                current_user=current_user,
                analysis_by_id=analysis_by_id,
                storage_client=storage_client,
                check_video_exists=False,
            )
            for submission in submissions
        ]

    def build_video_stream_response(
        self,
        submission: dict[str, Any],
        range_header: str | None,
    ):
        """Stream the submission video from GCS with optional Range support."""
        video_path = submission.get("video_path")
        if not video_path:
            raise ValueError("Submission has no stored video")

        bucket_name, object_name = parse_gs_uri(video_path)
        blob = self._storage_client().bucket(bucket_name).blob(object_name)
        if not blob.exists():
            raise ValueError("Video file not found in storage")

        content_type = submission.get("content_type", "video/mp4")
        return build_video_streaming_response(blob, content_type, range_header)

    def _build_genai_client(self) -> genai.Client:
        if self.use_enterprise:
            return genai.Client(
                enterprise=True,
                project=self.project,
                location=self.location,
            )
        return genai.Client(
            vertexai=True,
            project=self.project,
            location=self.location,
        )

    def _generate_checklist(
        self,
        client: genai.Client,
        problem_statement: str,
        solution_description: str,
    ) -> str:
        prompt = CHECKLIST_PROMPT.format(
            problem_statement=problem_statement.strip(),
            solution_description=solution_description.strip(),
        )
        response = client.models.generate_content(
            model=self.model,
            contents=[prompt],
        )
        text = (response.text or "").strip()
        if not text:
            raise ValueError("Failed to generate validation checklist")
        return text

    def _analyze_video(
        self,
        client: genai.Client,
        video_uri: str,
        content_type: str,
        context: str,
    ) -> str:
        video_part = types.Part.from_uri(file_uri=video_uri, mime_type=content_type)
        prompt = ANALYZE_VIDEO_PROMPT.format(context=context)

        response = client.models.generate_content(
            model=self.model,
            contents=[video_part, prompt],
        )
        report = (response.text or "").strip()
        if not report:
            raise ValueError("The analyzer returned an empty report")
        return report

    def _upload_bytes(self, object_name: str, payload: bytes, content_type: str) -> None:
        blob = self._storage_client().bucket(self.bucket_name).blob(object_name)
        blob.upload_from_string(payload, content_type=content_type)

    def _upload_fileobj(
        self,
        object_name: str,
        fileobj: BinaryIO,
        content_type: str,
    ) -> None:
        """Stream a file-like object to GCS (avoids holding a second full copy)."""
        fileobj.seek(0)
        blob = self._storage_client().bucket(self.bucket_name).blob(object_name)
        blob.upload_from_file(fileobj, content_type=content_type, rewind=True)

    def _update_submission(self, submission_id: str, data: dict[str, Any]) -> None:
        data["updated_at"] = datetime.utcnow().isoformat()
        self.firebase.update_document(self.collection, submission_id, data)

    def _update_analysis(self, analysis_id: str, data: dict[str, Any]) -> None:
        data["updated_at"] = datetime.utcnow().isoformat()
        self.firebase.update_document(self.analysis_collection, analysis_id, data)

    def _commit_analysis_and_submission(
        self,
        analysis_id: str | None,
        submission_id: str,
        analysis_data: dict[str, Any] | None,
        submission_data: dict[str, Any],
    ) -> None:
        """Atomically update analysis + submission (or submission alone on early fail)."""
        now = datetime.utcnow().isoformat()
        operations: list[dict[str, Any]] = []
        if analysis_id and analysis_data is not None:
            analysis_payload = {**analysis_data, "updated_at": now}
            operations.append(
                {
                    "type": "update",
                    "collection": self.analysis_collection,
                    "document_id": analysis_id,
                    "data": analysis_payload,
                }
            )
        submission_payload = {**submission_data, "updated_at": now}
        operations.append(
            {
                "type": "update",
                "collection": self.collection,
                "document_id": submission_id,
                "data": submission_payload,
            }
        )
        self.firebase.batch_write(operations)

    def _resolve_student_team_name(self, student_id: str) -> str:
        """Load team_name from the student's Firestore profile."""
        profile = self.user_service.get_user(student_id)
        if not profile:
            raise ValueError("Student profile not found")
        if profile.get("role") != "student":
            raise ValueError("Only students can create submissions")

        team_name = (profile.get("team_name") or "").strip()
        if not team_name:
            raise ValueError(
                "Team name is missing on your profile. Complete team registration first."
            )
        return team_name

    def _validate_configuration(self) -> None:
        missing = []
        if not self.project:
            missing.append("GOOGLE_CLOUD_PROJECT or FIREBASE_PROJECT_ID")
        if not self.bucket_name:
            missing.append("EVALUATION_BUCKET_NAME or VIDEO_BUCKET_NAME")
        if missing:
            raise ValueError(f"Missing evaluation configuration: {', '.join(missing)}")

    def _storage_client(self) -> storage.Client:
        if self.storage_client is None:
            self.storage_client = self._build_storage_client()
        return self.storage_client

    def _build_storage_client(self) -> storage.Client:
        firebase_private_key = os.getenv("FIREBASE_PRIVATE_KEY")
        firebase_client_email = os.getenv("FIREBASE_CLIENT_EMAIL")

        if firebase_private_key and firebase_client_email:
            credentials = service_account.Credentials.from_service_account_info(
                {
                    "type": "service_account",
                    "project_id": self.project,
                    "private_key": firebase_private_key.replace("\\n", "\n"),
                    "client_email": firebase_client_email,
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            )
            return storage.Client(project=self.project, credentials=credentials)

        return storage.Client(project=self.project)
