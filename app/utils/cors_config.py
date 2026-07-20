"""
CORS and cookie configuration helpers.
"""

import os


DEFAULT_DEV_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:8000",
    "http://localhost:8080",
    "http://localhost:5173",
]

# Fallback when ALLOWED_ORIGINS is not set in production.
DEFAULT_PROD_ORIGINS = [
    "https://hackniat.vercel.app",
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
