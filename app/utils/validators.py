"""
Input validation utilities
"""

import re

from app.models.user_model import USER_ROLES, UserRole


def validate_email(email: str) -> bool:
    """
    Validate email format

    Args:
        email: Email address to validate

    Returns:
        True if valid, False otherwise
    """
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return re.match(pattern, email) is not None


def validate_password(password: str) -> tuple[bool, str]:
    """
    Validate password strength

    Args:
        password: Password to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if len(password) < 6:
        return False, "Password must be at least 6 characters"
    return True, ""


def validate_name(name: str) -> tuple[bool, str]:
    """
    Validate name

    Args:
        name: Name to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not name or len(name) == 0:
        return False, "Name cannot be empty"
    if len(name) > 100:
        return False, "Name must be less than 100 characters"
    return True, ""


def validate_role(role: str) -> tuple[bool, str]:
    """
    Validate user role.

    Args:
        role: Role to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if role not in USER_ROLES:
        return False, f"Role must be one of: {', '.join(USER_ROLES)}"
    return True, ""


def is_valid_role(role: str) -> role is UserRole:
    """Return True if role is a supported UserRole."""
    return role in USER_ROLES


