"""Upload / create submission paths (multipart + signed URL)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Any, BinaryIO

from app.models.user_model import CurrentUser
from app.utils.gcs_video import generate_signed_upload_url, parse_gs_uri
from app.utils.video_upload import (
    MAX_MULTIPART_VIDEO_BYTES,
    MAX_VIDEO_UPLOAD_BYTES,
    assert_video_size,
    peek_file_header,
    resolve_video_content_type,
    resolve_video_content_type_from_metadata,
)


CREATE_SUCCESS_MESSAGE = (
    "Your submission has been recorded successfully. "
    "You will receive the evaluation result once an evaluator finishes "
    "review and the admin approves the final score."
)


def demo_video_required(hackathon: dict[str, Any]) -> bool:
    """Older hackathons without the flag still require a demo video."""
    return bool(hackathon.get("working_demo_video_required", True))


class CreateMixin:
    """Multipart upload, signed-URL prepare, and finalize-from-upload."""

    def create_submission(
        self,
        student: CurrentUser,
        problem_statement: str,
        solution_description: str,
        hackathon_id: str,
        theme_id: str,
        video: tuple[str, bytes | BinaryIO, str] | None = None,
        video_source: str | None = None,
        mvp_link: str | None = None,
        github_link: str | None = None,
        field_answers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create a submission; upload video when provided / required."""
        hackathon, theme, theme_id = self._validate_hackathon_and_theme(
            hackathon_id, theme_id
        )
        video_required = demo_video_required(hackathon)
        if video_required and video is None:
            raise ValueError(
                "A working demo video is required for this hackathon. "
                "Record or upload a video before submitting."
            )

        self._validate_configuration(require_bucket=video is not None or video_required)
        team_name = self._resolve_student_team_name(student.user_id)

        video_path: str | None = None
        resolved_type: str | None = None
        filename = ""
        if video is not None:
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
            object_name = self._video_object_name(student.user_id, submission_id, extension)
            video_path = f"gs://{self.bucket_name}/{object_name}"

            if isinstance(upload_target, (bytes, bytearray)):
                self._upload_bytes(object_name, bytes(upload_target), resolved_type)
            else:
                self._upload_fileobj(object_name, upload_target, resolved_type)
        else:
            submission_id = uuid.uuid4().hex

        submission = self._build_new_submission_document(
            student_id=student.user_id,
            hackathon_id=hackathon_id.strip(),
            hackathon=hackathon,
            theme_id=theme_id,
            theme=theme,
            team_name=team_name,
            problem_statement=problem_statement,
            solution_description=solution_description,
            video_path=video_path,
            content_type=resolved_type,
            source_filename=filename or None,
            video_source=video_source,
            mvp_link=mvp_link,
            github_link=github_link,
            field_answers=field_answers,
        )
        return self._persist_new_submission(submission_id, submission)

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
        object_name = self._video_object_name(student.user_id, submission_id, extension)
        video_path = f"gs://{self.bucket_name}/{object_name}"
        expires_in = int(os.getenv("VIDEO_UPLOAD_URL_EXPIRY_SECONDS", "1800"))

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
            "video_source": self._normalize_video_source(video_source),
            "expires_in_seconds": expires_in,
            "max_upload_bytes": MAX_VIDEO_UPLOAD_BYTES,
        }

    def create_submission_from_upload(
        self,
        student: CurrentUser,
        problem_statement: str,
        solution_description: str,
        hackathon_id: str,
        theme_id: str,
        video_path: str | None = None,
        content_type: str | None = None,
        source_filename: str | None = None,
        video_source: str | None = None,
        mvp_link: str | None = None,
        github_link: str | None = None,
        field_answers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create a submission after optional signed-URL video upload."""
        hackathon, theme, theme_id = self._validate_hackathon_and_theme(
            hackathon_id, theme_id
        )
        video_required = demo_video_required(hackathon)
        has_video = bool(video_path and str(video_path).strip())

        if video_required and not has_video:
            raise ValueError(
                "A working demo video is required for this hackathon. "
                "Upload the video via the signed URL, then finalize."
            )

        self._validate_configuration(require_bucket=has_video or video_required)

        resolved_type: str | None = None
        submission_id = uuid.uuid4().hex

        if has_video:
            assert video_path is not None
            resolved_type, extension = resolve_video_content_type_from_metadata(
                content_type,
                source_filename or "submission.mp4",
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
        submission = self._build_new_submission_document(
            student_id=student.user_id,
            hackathon_id=hackathon_id.strip(),
            hackathon=hackathon,
            theme_id=theme_id,
            theme=theme,
            team_name=team_name,
            problem_statement=problem_statement,
            solution_description=solution_description,
            video_path=video_path.strip() if has_video and video_path else None,
            content_type=resolved_type,
            source_filename=source_filename,
            video_source=video_source if has_video else None,
            mvp_link=mvp_link,
            github_link=github_link,
            field_answers=field_answers,
        )
        return self._persist_new_submission(submission_id, submission)

    # ---- shared create helpers (Phase 10 dedupe) ----

    @staticmethod
    def _normalize_video_source(video_source: str | None) -> str | None:
        return video_source if video_source in ("recorded", "uploaded") else None

    @staticmethod
    def _video_object_name(student_id: str, submission_id: str, extension: str) -> str:
        return f"submissions/{student_id}/{submission_id}/video{extension}"

    def _validate_hackathon_and_theme(
        self,
        hackathon_id: str,
        theme_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any], str]:
        """Shared hackathon + released-theme checks for both create paths."""
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
        return hackathon, theme, theme_id

    def _build_new_submission_document(
        self,
        *,
        student_id: str,
        hackathon_id: str,
        hackathon: dict[str, Any],
        theme_id: str,
        theme: dict[str, Any],
        team_name: str,
        problem_statement: str,
        solution_description: str,
        video_path: str | None,
        content_type: str | None,
        source_filename: str | None,
        video_source: str | None,
        mvp_link: str | None = None,
        github_link: str | None = None,
        field_answers: dict[str, str] | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        """Single document shape for multipart and signed-URL create paths."""
        created_at = now or datetime.utcnow().isoformat()
        answers = dict(field_answers or {})
        # Keep top-level PS/SD as the source of truth; mirror into field_answers.
        answers.setdefault("problem_statement", problem_statement.strip())
        answers.setdefault("solution_description", solution_description.strip())
        if mvp_link:
            answers.setdefault("mvp_link", mvp_link.strip())
        if github_link:
            answers.setdefault("github_link", github_link.strip())
            answers.setdefault("project_github_link", github_link.strip())

        return {
            "student_id": student_id,
            "hackathon_id": hackathon_id,
            "hackathon_name": hackathon["name"],
            "team_name": team_name,
            "theme_id": theme_id,
            "theme_name": theme["name"],
            "problem_statement": problem_statement.strip(),
            "solution_description": solution_description.strip(),
            "mvp_link": (mvp_link or "").strip() or None,
            "github_link": (github_link or "").strip() or None,
            "field_answers": answers,
            "evaluation_criteria": None,
            "status": "uploaded",
            "video_path": video_path,
            "content_type": content_type,
            "source_filename": source_filename,
            "video_source": self._normalize_video_source(video_source) if video_path else None,
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
            "created_at": created_at,
            "updated_at": created_at,
        }

    def _persist_new_submission(
        self,
        submission_id: str,
        submission: dict[str, Any],
    ) -> dict[str, Any]:
        self.firebase.set_document(self.collection, submission_id, submission)
        return {
            "id": submission_id,
            **submission,
            "message": CREATE_SUCCESS_MESSAGE,
        }

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
