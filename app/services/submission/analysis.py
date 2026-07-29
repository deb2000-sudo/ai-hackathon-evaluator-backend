"""AI analysis queueing, Gemini evaluation, and report publish helpers."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from google import genai
from google.genai import types

from app.models.user_model import CurrentUser
from app.services.submission.prompts import ANALYZE_VIDEO_PROMPT, CHECKLIST_PROMPT


logger = logging.getLogger(__name__)


class AnalysisMixin:
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

    def _build_genai_client(self) -> genai.Client:
        if self._genai_client is not None:
            return self._genai_client
        if self.use_enterprise:
            client = genai.Client(
                enterprise=True,
                project=self.project,
                location=self.location,
            )
        else:
            client = genai.Client(
                vertexai=True,
                project=self.project,
                location=self.location,
            )
        # Cache on the process-scoped service instance (one client lifecycle).
        self._genai_client = client
        return client

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

