"""
CORS and cookie configuration helpers.
"""

import os

from app.utils.auth_cookies import CSRF_HEADER_NAME


DEFAULT_DEV_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:8000",
    "http://localhost:8080",
    "http://localhost:5173",
    "https://hackniat.vercel.app",
]

# Fallback when ALLOWED_ORIGINS is not set in production.
DEFAULT_PROD_ORIGINS = [
    "https://hackniat.vercel.app",
]

# Headers the Vercel SPA / browsers may send (incl. Phase 5b CSRF).
DEFAULT_ALLOW_HEADERS = [
    "Authorization",
    "Content-Type",
    "Accept",
    "Origin",
    "X-Requested-With",
    CSRF_HEADER_NAME,
]


def get_allowed_origins() -> list[str]:
    """
    Return CORS allowed origins.

    Production uses ALLOWED_ORIGINS from the environment (required for
    credentialed cross-origin cookie auth). Development merges env origins
    with local defaults.
    """
    env_origins = [
        origin.strip()
        for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    ]

    if os.getenv("ENVIRONMENT", "development").lower() == "production":
        return env_origins or DEFAULT_PROD_ORIGINS

    return list(dict.fromkeys(DEFAULT_DEV_ORIGINS + env_origins))


def get_cors_allow_headers() -> list[str]:
    """
    CORS allow-headers.

    Defaults to ``*`` (unchanged behaviour) unless ``CORS_ALLOW_HEADERS`` is set
    to a comma-separated list. Always ensures ``X-CSRF-Token`` is permitted when
    using an explicit list.
    """
    raw = os.getenv("CORS_ALLOW_HEADERS", "").strip()
    if not raw or raw == "*":
        return ["*"]

    headers = [h.strip() for h in raw.split(",") if h.strip()]
    if CSRF_HEADER_NAME not in headers and CSRF_HEADER_NAME.lower() not in {
        h.lower() for h in headers
    }:
        headers.append(CSRF_HEADER_NAME)
    return headers or list(DEFAULT_ALLOW_HEADERS)
