"""
Hackathon video evaluation service using Vertex AI Gemini and Google Cloud Storage.

Flow:
1. `upload_video`  -> store the submission video in GCS + create an
   `evaluation_sessions/{id}` Firestore doc with status "uploaded".
2. `analyze_video_for_session` (run as a FastAPI BackgroundTask) -> drive the
   session through "processing" -> "completed"/"failed". When a problem
   statement + solution description are supplied it first generates a "Product
   & Feature Validation Checklist" (as in the VideoAnalyzer prototype), then
   asks Gemini to watch the video and score it against that checklist.
3. The frontend polls `GET /evaluations/{id}` for status + result.
"""

import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any

from google import genai
from google.cloud import storage
from google.genai import types
from google.oauth2 import service_account

from app.models.user_model import CurrentUser
from app.services.firebase import FirebaseService


logger = logging.getLogger(__name__)


# Video MIME types we accept for a hackathon submission.
ALLOWED_VIDEO_TYPES = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
    "video/x-matroska": ".mkv",
    "video/mpeg": ".mpeg",
}


DEFAULT_RUBRIC = (
    "You are an expert judge for a software hackathon. Watch the submission "
    "video and evaluate the project fairly and constructively. Consider the "
    "problem being solved, the working demo, technical depth, clarity of the "
    "pitch, and potential real-world impact."
)


# Prompt used to turn a problem + solution into a validation checklist, adapted
# from the VideoAnalyzer prototype's generate_context step.
CHECKLIST_PROMPT = """You are a product analyst. Based on the PROBLEM STATEMENT and SOLUTION
DESCRIPTION below, produce a "Product & Feature Validation Checklist" that will
later be used to evaluate whether a demo video properly showcases this product.

Structure the output as a numbered checklist with clear sections, for example:

1. PROBLEM ESTABLISHMENT (The Pain Points)
- ...specific things the video should mention about the problem...

2. CORE SOLUTION / FEATURE DEMONSTRATION
- ...specific capabilities the video should visually demonstrate...

3. WORKFLOW / INTEGRATION
- ...how the solution should be shown working end-to-end...

4. VALUE PROPOSITION & BENCHMARKS
- ...explicit benefits/claims the video should confirm...

Adapt the section names and bullets to fit the product described below (do not
copy the template verbatim). Extract concrete, checkable criteria a reviewer can
verify against the video. Output plain text only (no markdown headers).

--- PROBLEM STATEMENT ---
{problem_statement}
--- END PROBLEM STATEMENT ---

--- SOLUTION DESCRIPTION ---
{solution_description}
--- END SOLUTION DESCRIPTION ---
"""


# The exact JSON contract we want Gemini to return for the evaluation.
RESPONSE_INSTRUCTIONS = (
    "Return ONLY a JSON object (no markdown fences, no commentary) with this exact shape:\n"
    "{\n"
    '  "overall_score": <number 0-100>,\n'
    '  "criteria": {\n'
    '    "problem_coverage": <number 0-10>,\n'
    '    "solution_demonstration": <number 0-10>,\n'
    '    "technical_execution": <number 0-10>,\n'
    '    "presentation": <number 0-10>,\n'
    '    "impact": <number 0-10>\n'
    "  },\n"
    '  "summary": "<2-4 sentence overall assessment>",\n'
    '  "strengths": ["<point>", "..."],\n'
    '  "improvements": ["<point>", "..."],\n'
    '  "recommendation": "<one short verdict, e.g. Strong contender / Promising / Needs work>",\n'
    '  "report": "<a detailed markdown analysis of the video, going through each '
    'checklist section and noting what was demonstrated vs. missing>"\n'
    "}"
)


class EvaluationService:
    """
    Creates and tracks user-owned hackathon video evaluation sessions.
    """

    collection = "evaluation_sessions"

    def __init__(self):
        self.project = (
            os.getenv("GOOGLE_CLOUD_PROJECT")
            or os.getenv("FIREBASE_PROJECT_ID")
            or "nxt-create-deb"
        )
        self.location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        self.bucket_name = os.getenv("EVALUATION_BUCKET_NAME") or os.getenv("VIDEO_BUCKET_NAME")
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.storage_client: storage.Client | None = None
        self.firebase = FirebaseService()

    # ==================== Upload ====================

    def upload_video(
        self,
        current_user: CurrentUser,
        video: tuple[str, bytes, str],
    ) -> dict[str, Any]:
        """
        Upload the submission video to GCS and create the session document.

        Args:
            current_user: Authenticated owner of the submission.
            video: Tuple of (filename, raw_bytes, content_type).

        Returns:
            The created session (including its generated `id`).
        """
        self._validate_configuration()

        filename, video_bytes, content_type = video
        extension = ALLOWED_VIDEO_TYPES.get(content_type, ".mp4")

        session_id = uuid.uuid4().hex
        now = datetime.utcnow().isoformat()
        object_name = f"evaluations/{current_user.user_id}/{session_id}/submission{extension}"
        video_path = f"gs://{self.bucket_name}/{object_name}"

        self._upload_bytes(object_name, video_bytes, content_type)

        session = {
            "user_id": current_user.user_id,
            "status": "uploaded",
            "video_path": video_path,
            "content_type": content_type,
            "source_filename": filename,
            "problem_statement": None,
            "solution_description": None,
            "criteria": None,
            "result": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
        }

        self.firebase.set_document(self.collection, session_id, session)
        return {"id": session_id, **session}

    # ==================== Analysis ====================

    def mark_queued_for_analysis(
        self,
        session_id: str,
        problem_statement: str | None,
        solution_description: str | None,
        criteria: str | None,
    ) -> None:
        """
        Flip the session to "processing" and persist the analysis inputs before
        the background task runs, so the client's next poll reflects the state.
        """
        self._update_session(
            session_id,
            {
                "status": "processing",
                "problem_statement": problem_statement,
                "solution_description": solution_description,
                "criteria": criteria,
                "error": None,
            },
        )

    def analyze_video_for_session(
        self,
        session_id: str,
        problem_statement: str | None = None,
        solution_description: str | None = None,
        criteria: str | None = None,
    ) -> None:
        """
        Ask Gemini to evaluate the uploaded submission video and persist the
        result. Intended to run inside a FastAPI BackgroundTask.
        """
        try:
            session = self.firebase.get_document(self.collection, session_id)
            if not session:
                logger.error("Evaluation session not found: %s", session_id)
                return

            self._update_session(session_id, {"status": "processing", "error": None})

            client = genai.Client(
                vertexai=True,
                project=self.project,
                location=self.location,
            )

            problem = problem_statement or session.get("problem_statement")
            solution = solution_description or session.get("solution_description")
            extra_criteria = criteria or session.get("criteria")

            # Step 1 (optional): build a validation checklist from problem + solution.
            checklist = None
            if problem and solution:
                checklist = self._generate_checklist(client, problem, solution)

            # Step 2: evaluate the video against the checklist / rubric.
            result = self._run_gemini_evaluation(
                client=client,
                video_uri=session["video_path"],
                content_type=session.get("content_type", "video/mp4"),
                checklist=checklist,
                criteria=extra_criteria,
            )
            result["checklist"] = checklist

            self._update_session(
                session_id,
                {
                    "status": "completed",
                    "result": result,
                    "error": None,
                },
            )

        except Exception as e:
            logger.error("Evaluation failed for session %s: %s", session_id, str(e))
            self._update_session(
                session_id,
                {
                    "status": "failed",
                    "error": str(e),
                },
            )

    def _generate_checklist(
        self,
        client: "genai.Client",
        problem_statement: str,
        solution_description: str,
    ) -> str:
        """
        Generate a Product & Feature Validation Checklist from the problem +
        solution (VideoAnalyzer.generate_context step).
        """
        prompt = CHECKLIST_PROMPT.format(
            problem_statement=problem_statement.strip(),
            solution_description=solution_description.strip(),
        )
        response = client.models.generate_content(
            model=self.model,
            contents=[types.Part.from_text(text=prompt)],
            config=types.GenerateContentConfig(temperature=0.3),
        )
        return (response.text or "").strip()

    def _run_gemini_evaluation(
        self,
        client: "genai.Client",
        video_uri: str,
        content_type: str,
        checklist: str | None,
        criteria: str | None,
    ) -> dict[str, Any]:
        """
        Send the GCS-hosted video to Gemini and parse a structured evaluation.
        """
        rubric_parts = [DEFAULT_RUBRIC]
        if checklist:
            rubric_parts.append(
                "Evaluate the video against this Product & Feature Validation "
                "Checklist, section by section:\n\n" + checklist
            )
        if criteria and criteria.strip():
            rubric_parts.append("Additional focus for this evaluation:\n" + criteria.strip())

        prompt = "\n\n".join(rubric_parts) + "\n\n" + RESPONSE_INSTRUCTIONS

        contents = [
            types.Part.from_uri(file_uri=video_uri, mime_type=content_type),
            types.Part.from_text(text=prompt),
        ]

        response = client.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )

        return self._parse_evaluation(response.text)

    @staticmethod
    def _parse_evaluation(raw_text: str | None) -> dict[str, Any]:
        """
        Parse the model's JSON output, tolerating an accidental ```json fence.
        """
        if not raw_text:
            raise ValueError("The evaluator returned an empty response")

        text = raw_text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"Could not parse evaluation response: {str(e)}") from e

        criteria = data.get("criteria", {}) or {}
        return {
            "overall_score": data.get("overall_score", 0),
            "criteria": {
                "problem_coverage": criteria.get("problem_coverage", 0),
                "solution_demonstration": criteria.get("solution_demonstration", 0),
                "technical_execution": criteria.get("technical_execution", 0),
                "presentation": criteria.get("presentation", 0),
                "impact": criteria.get("impact", 0),
            },
            "summary": data.get("summary", ""),
            "strengths": data.get("strengths", []) or [],
            "improvements": data.get("improvements", []) or [],
            "recommendation": data.get("recommendation", ""),
            "report": data.get("report"),
        }

    # ==================== Reads ====================

    def get_user_session(self, session_id: str, current_user: CurrentUser) -> dict[str, Any] | None:
        """
        Fetch a session if it belongs to the current user or the user is an admin.
        """
        session = self.firebase.get_document(self.collection, session_id)
        if not session:
            return None

        if session.get("user_id") != current_user.user_id and current_user.role != "admin":
            return None

        return {"id": session_id, **session}

    # ==================== GCS helpers ====================

    def _upload_bytes(self, object_name: str, payload: bytes, content_type: str) -> None:
        blob = self._storage_client().bucket(self.bucket_name).blob(object_name)
        blob.upload_from_string(payload, content_type=content_type)

    def _update_session(self, session_id: str, data: dict[str, Any]) -> None:
        data["updated_at"] = datetime.utcnow().isoformat()
        self.firebase.update_document(self.collection, session_id, data)

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
