"""
Input validation utilities
"""

import re
from typing import Literal


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



