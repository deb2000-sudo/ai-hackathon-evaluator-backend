"""
Video upload type detection for browser screen recordings and file uploads.
"""

from pathlib import Path


# MIME types accepted for hackathon submission videos.
ALLOWED_VIDEO_TYPES: dict[str, str] = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
    "video/x-matroska": ".mkv",
    "video/mpeg": ".mpeg",
    "video/ogg": ".ogv",
    "video/x-msvideo": ".avi",
}

# Browser MediaRecorder / upload clients may send these instead of base MIME types.
MIME_ALIASES: dict[str, str] = {
    "video/x-webm": "video/webm",
    "application/webm": "video/webm",
    "video/avi": "video/x-msvideo",
}

EXTENSION_TO_MIME: dict[str, str] = {
    ext: mime for mime, ext in ALLOWED_VIDEO_TYPES.items()
}


def _normalize_mime(content_type: str | None) -> str | None:
    if not content_type:
        return None

    base = content_type.split(";")[0].strip().lower()
    if base in ALLOWED_VIDEO_TYPES:
        return base
    return MIME_ALIASES.get(base)


def _mime_from_filename(filename: str | None) -> str | None:
    if not filename:
        return None

    extension = Path(filename).suffix.lower()
    return EXTENSION_TO_MIME.get(extension)


def _mime_from_magic(file_bytes: bytes) -> str | None:
    if len(file_bytes) < 12:
        return None

    header = file_bytes[:12]

    # WebM / Matroska (common for browser screen recordings)
    if header[:4] == b"\x1a\x45\xdf\xa3":
        return "video/webm"

    # MP4 / MOV (ftyp at offset 4)
    if header[4:8] == b"ftyp":
        brand = header[8:12]
        if brand.startswith(b"qt"):
            return "video/quicktime"
        return "video/mp4"

    # MPEG program stream
    if header[:3] == b"\x00\x00\x01":
        return "video/mpeg"

    return None


def resolve_video_content_type(
    content_type: str | None,
    filename: str | None,
    file_bytes: bytes,
) -> tuple[str, str]:
    """
    Resolve a supported video MIME type and file extension.

    Browser screen recordings often send values like
    ``video/webm;codecs=vp9,opus`` or ``application/octet-stream`` which are
    normalized here using the base MIME type, filename extension, or magic bytes.

    Returns:
        Tuple of (content_type, extension)

    Raises:
        ValueError: If the upload cannot be recognized as a supported video.
    """
    candidates = [
        _normalize_mime(content_type),
        _mime_from_filename(filename),
        _mime_from_magic(file_bytes),
    ]

    for mime in candidates:
        if mime and mime in ALLOWED_VIDEO_TYPES:
            return mime, ALLOWED_VIDEO_TYPES[mime]

    received = content_type or "unknown"
    allowed = ", ".join(sorted(ALLOWED_VIDEO_TYPES))
    raise ValueError(
        f"Unsupported video format ({received}). "
        f"Allowed types: {allowed}. "
        "If recording in the browser, try WebM or MP4."
    )
