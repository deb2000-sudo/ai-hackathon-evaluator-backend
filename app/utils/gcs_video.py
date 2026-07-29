"""
Google Cloud Storage helpers for submission video playback.
"""

import logging
import os
import re
from datetime import timedelta
from typing import Iterator

from google.cloud import storage
from google.cloud.storage.blob import Blob
from google.oauth2 import service_account
from starlette.responses import StreamingResponse


logger = logging.getLogger(__name__)

GS_URI_PATTERN = re.compile(r"^gs://([^/]+)/(.+)$")
RANGE_PATTERN = re.compile(r"bytes=(\d+)-(\d*)")


def parse_gs_uri(gs_uri: str) -> tuple[str, str]:
    """Split a gs://bucket/object/path URI into bucket name and object path."""
    match = GS_URI_PATTERN.match(gs_uri)
    if not match:
        raise ValueError(f"Invalid GCS URI: {gs_uri}")
    return match.group(1), match.group(2)


def build_storage_client(project: str | None) -> storage.Client:
    """
    Build a GCS client, reusing the Firebase service-account env vars when
    available (same pattern used across services).
    """
    firebase_private_key = os.getenv("FIREBASE_PRIVATE_KEY")
    firebase_client_email = os.getenv("FIREBASE_CLIENT_EMAIL")

    if firebase_private_key and firebase_client_email:
        credentials = service_account.Credentials.from_service_account_info(
            {
                "type": "service_account",
                "project_id": project,
                "private_key": firebase_private_key.replace("\\n", "\n"),
                "client_email": firebase_client_email,
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        )
        return storage.Client(project=project, credentials=credentials)

    return storage.Client(project=project)


def generate_signed_url(
    client: storage.Client,
    gs_uri: str,
    expiry_seconds: int | None = None,
    *,
    check_exists: bool = False,
) -> str | None:
    """
    Return a time-limited HTTPS URL for any GCS object (generic).

    ``check_exists`` defaults to False (Phase 7) to avoid an extra GCS RPC per
    object on list endpoints. Missing objects still get a URL that fails on GET.
    """
    try:
        bucket_name, object_name = parse_gs_uri(gs_uri)
        blob = client.bucket(bucket_name).blob(object_name)
        if check_exists and not blob.exists():
            logger.warning("GCS object not found: %s", gs_uri)
            return None

        return blob.generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=expiry_seconds or signed_url_expiry_seconds()),
            method="GET",
        )
    except Exception as e:
        logger.error("Failed to generate signed URL for %s: %s", gs_uri, str(e))
        return None


def generate_signed_upload_url(
    client: storage.Client,
    bucket_name: str,
    object_name: str,
    content_type: str,
    expiry_seconds: int = 1800,
) -> str:
    """
    Return a v4 signed URL for a browser PUT directly to GCS.

    The client must send the same ``Content-Type`` header when uploading.
    """
    blob = client.bucket(bucket_name).blob(object_name)
    return blob.generate_signed_url(
        version="v4",
        expiration=timedelta(seconds=max(60, expiry_seconds)),
        method="PUT",
        content_type=content_type,
    )


def signed_url_expiry_seconds() -> int:
    raw = os.getenv("VIDEO_SIGNED_URL_EXPIRY_SECONDS", "3600")
    try:
        return max(60, int(raw))
    except ValueError:
        return 3600


def generate_signed_video_url(
    client: storage.Client,
    video_path: str,
    *,
    check_exists: bool = False,
) -> str | None:
    """
    Return a time-limited HTTPS URL for browser playback.

    Skips ``blob.exists()`` by default so list enrichment is one sign RPC per
    video instead of exists+sign.
    """
    try:
        bucket_name, object_name = parse_gs_uri(video_path)
        blob = client.bucket(bucket_name).blob(object_name)
        if check_exists and not blob.exists():
            logger.warning("Video object not found in GCS: %s", video_path)
            return None

        return blob.generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=signed_url_expiry_seconds()),
            method="GET",
        )
    except Exception as e:
        logger.error("Failed to generate signed video URL for %s: %s", video_path, str(e))
        return None


def parse_range_header(range_header: str | None, file_size: int) -> tuple[int, int]:
    """Parse an HTTP Range header into inclusive start/end byte indices."""
    if not range_header:
        return 0, file_size - 1

    match = RANGE_PATTERN.match(range_header.strip())
    if not match:
        return 0, file_size - 1

    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else file_size - 1
    end = min(end, file_size - 1)

    if start > end or start >= file_size:
        raise ValueError("Invalid range")

    return start, end


def iter_blob_bytes(blob: Blob, start: int, end: int, chunk_size: int = 256 * 1024) -> Iterator[bytes]:
    """Stream a byte range from a GCS object."""
    with blob.open("rb") as stream:
        stream.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            data = stream.read(min(chunk_size, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


def build_video_streaming_response(
    blob: Blob,
    content_type: str,
    range_header: str | None,
) -> StreamingResponse:
    """Build a full or partial (206) streaming response for a GCS video object."""
    file_size = blob.size
    if file_size is None:
        blob.reload()
        file_size = blob.size or 0

    if file_size == 0:
        raise ValueError("Video file is empty")

    try:
        start, end = parse_range_header(range_header, file_size)
    except ValueError as e:
        raise ValueError("Invalid Range header") from e

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": content_type,
        "Content-Disposition": f'inline; filename="{blob.name.split("/")[-1]}"',
    }

    if range_header:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        headers["Content-Length"] = str(end - start + 1)
        status_code = 206
    else:
        headers["Content-Length"] = str(file_size)
        status_code = 200

    return StreamingResponse(
        iter_blob_bytes(blob, start, end),
        status_code=status_code,
        media_type=content_type,
        headers=headers,
    )
