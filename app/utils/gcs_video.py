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


def signed_url_expiry_seconds() -> int:
    raw = os.getenv("VIDEO_SIGNED_URL_EXPIRY_SECONDS", "3600")
    try:
        return max(60, int(raw))
    except ValueError:
        return 3600


def generate_signed_video_url(client: storage.Client, video_path: str) -> str | None:
    """Return a time-limited HTTPS URL for browser playback."""
    try:
        bucket_name, object_name = parse_gs_uri(video_path)
        blob = client.bucket(bucket_name).blob(object_name)
        if not blob.exists():
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
