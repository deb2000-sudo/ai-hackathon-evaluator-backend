"""
Authentication cookie helpers.
"""

import os

from fastapi import Response


AUTH_COOKIE_NAME = "access_token"
# Firebase ID tokens expire in 3600 seconds.
AUTH_COOKIE_MAX_AGE = 3600


def _cookie_secure() -> bool:
    return os.getenv("ENVIRONMENT", "development").lower() == "production"


def _cookie_samesite() -> str:
    return os.getenv("COOKIE_SAMESITE", "lax")


def set_auth_cookie(response: Response, id_token: str) -> None:
    """Attach the Firebase ID token as an HttpOnly session cookie."""
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=id_token,
        httponly=True,
        secure=_cookie_secure(),
        samesite=_cookie_samesite(),
        max_age=AUTH_COOKIE_MAX_AGE,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    """Remove the session cookie on logout."""
    response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=_cookie_secure(),
        samesite=_cookie_samesite(),
    )
