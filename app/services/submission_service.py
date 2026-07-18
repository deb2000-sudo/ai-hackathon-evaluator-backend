"""
Student submission service — video upload, storage, and AI analysis.
"""

import logging
import os
import uuid
from datetime import datetime
from typing import Any

from google import genai
from google.cloud import storage
from google.genai import types
from google.oauth2 import service_account

from app.models.user_model import CurrentUser, ThemeChosen
from app.services.firebase import FirebaseService
from app.services.user_service import UserService
from app.utils.gcs_video import (
    build_video_streaming_response,
    generate_signed_video_url,
    parse_gs_uri,
)
from app.utils.video_upload import resolve_video_content_type


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
            or "nxt-create-deb"
        )
        self.location = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
        self.bucket_name = os.getenv("EVALUATION_BUCKET_NAME") or os.getenv("VIDEO_BUCKET_NAME")
        self.model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
        self.use_enterprise = os.getenv("GEMINI_ENTERPRISE", "true").lower() in ("1", "true", "yes")
        self.storage_client: storage.Client | None = None
        self.firebase = FirebaseService()
        self.user_service = UserService()

    def create_submission(
        self,
        student: CurrentUser,
        video: tuple[str, bytes, str],
        problem_statement: str,
        solution_description: str,
    ) -> dict[str, Any]:
        """Upload a student video and create a submission document."""
        self._validate_configuration()

        team_name, theme_chosen = self._resolve_student_team_profile(student.user_id)

        filename, video_bytes, content_type = video
        resolved_type, extension = resolve_video_content_type(
            content_type,
            filename,
            video_bytes,
        )

        submission_id = uuid.uuid4().hex
        now = datetime.utcnow().isoformat()
        object_name = (
            f"submissions/{student.user_id}/{submission_id}/video{extension}"
        )
        video_path = f"gs://{self.bucket_name}/{object_name}"

        self._upload_bytes(object_name, video_bytes, resolved_type)

        submission = {
            "student_id": student.user_id,
            "team_name": team_name,
            "theme_chosen": theme_chosen,
            "problem_statement": problem_statement.strip(),
            "solution_description": solution_description.strip(),
            "evaluation_criteria": None,
            "status": "uploaded",
            "video_path": video_path,
            "content_type": resolved_type,
            "source_filename": filename,
            "analysis_id": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
        }

        self.firebase.set_document(self.collection, submission_id, submission)
        return {"id": submission_id, **submission}

    def mark_queued_for_evaluation(
        self,
        submission_id: str,
        evaluation_criteria: str | None = None,
    ) -> str:
        """Create an analysis document and link it to the submission."""
        submission = self.firebase.get_document(self.collection, submission_id)
        if not submission:
            raise ValueError("Submission not found")

        analysis_id = uuid.uuid4().hex
        now = datetime.utcnow().isoformat()
        criteria = evaluation_criteria.strip() if evaluation_criteria else None

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
        self.firebase.set_document(self.analysis_collection, analysis_id, analysis_doc)

        submission_update: dict[str, Any] = {
            "analysis_id": analysis_id,
            "status": "processing",
            "error": None,
        }
        if evaluation_criteria is not None:
            submission_update["evaluation_criteria"] = criteria

        self._update_submission(submission_id, submission_update)
        return analysis_id

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
            self._update_analysis(
                analysis_id,
                {
                    "status": "completed",
                    "checklist": checklist,
                    "report": report,
                    "analyzed_at": analyzed_at,
                    "error": None,
                },
            )
            self._update_submission(
                submission_id,
                {
                    "status": "completed",
                    "error": None,
                },
            )
            logger.info("Analysis %s completed for submission %s", analysis_id, submission_id)

        except Exception as e:
            logger.error("Analysis failed for submission %s: %s", submission_id, str(e))
            if analysis_id:
                self._update_analysis(
                    analysis_id,
                    {"status": "failed", "error": str(e)},
                )
            self._update_submission(
                submission_id,
                {"status": "failed", "error": str(e)},
            )

    def get_submission(
        self,
        submission_id: str,
        current_user: CurrentUser,
    ) -> dict[str, Any] | None:
        """Fetch a submission for the owner, an evaluator, or an admin."""
        submission = self.firebase.get_document(self.collection, submission_id)
        if not submission:
            return None

        if submission.get("student_id") != current_user.user_id and current_user.role not in (
            "admin",
            "evaluator",
        ):
            return None

        return {"id": submission_id, **submission}

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

    def enrich_submission_for_response(self, submission: dict[str, Any]) -> dict[str, Any]:
        """Attach a browser-playable HTTPS URL alongside the internal gs:// path."""
        enriched = dict(submission)

        if not enriched.get("team_name"):
            enriched["team_name"] = enriched.get("title")
        if not enriched.get("team_name") or not enriched.get("theme_chosen"):
            profile = self.user_service.get_user(enriched.get("student_id", ""))
            if profile:
                if not enriched.get("team_name"):
                    enriched["team_name"] = profile.get("team_name")
                if not enriched.get("theme_chosen"):
                    enriched["theme_chosen"] = profile.get("theme_chosen")

        video_path = enriched.get("video_path")
        if video_path:
            enriched["video_url"] = generate_signed_video_url(
                self._storage_client(),
                video_path,
            )
        else:
            enriched["video_url"] = None

        analysis_id = enriched.get("analysis_id")
        if analysis_id:
            analysis_doc = self.firebase.get_document(self.analysis_collection, analysis_id)
            if analysis_doc and analysis_doc.get("status") == "completed":
                enriched["analysis"] = {
                    "id": analysis_id,
                    "checklist": analysis_doc["checklist"],
                    "report": analysis_doc["report"],
                    "analyzed_at": analysis_doc["analyzed_at"],
                }
        elif enriched.get("analysis") and isinstance(enriched["analysis"], dict):
            legacy = enriched["analysis"]
            if "id" not in legacy:
                enriched["analysis"] = {**legacy, "id": enriched.get("analysis_id") or enriched["id"]}

        return enriched

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

    def _update_submission(self, submission_id: str, data: dict[str, Any]) -> None:
        data["updated_at"] = datetime.utcnow().isoformat()
        self.firebase.update_document(self.collection, submission_id, data)

    def _update_analysis(self, analysis_id: str, data: dict[str, Any]) -> None:
        data["updated_at"] = datetime.utcnow().isoformat()
        self.firebase.update_document(self.analysis_collection, analysis_id, data)

    def _resolve_student_team_profile(self, student_id: str) -> tuple[str, ThemeChosen]:
        """Load team_name and theme_chosen from the student's Firestore profile."""
        profile = self.user_service.get_user(student_id)
        if not profile:
            raise ValueError("Student profile not found")
        if profile.get("role") != "student":
            raise ValueError("Only students can create submissions")

        team_name = (profile.get("team_name") or "").strip()
        theme_chosen = profile.get("theme_chosen")

        if not team_name:
            raise ValueError(
                "Team name is missing on your profile. Complete team registration first."
            )
        if not theme_chosen:
            raise ValueError(
                "Theme is missing on your profile. Complete team registration first."
            )

        return team_name, theme_chosen

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
