"""
User service for managing user operations
"""

import logging
from datetime import datetime
from typing import Any, Optional

from app.models.user_model import ApprovalStatus, UserResponse, UserRole
from app.services.firebase import FirebaseService


logger = logging.getLogger(__name__)


class UserService:
    """
    Service for user-related operations
    """

    def __init__(self):
        """Initialize user service"""
        self.firebase = FirebaseService()

    def create_user_with_firestore(
        self,
        user_id: str,
        name: str,
        email: str,
        role: UserRole = "student",
        approval_status: ApprovalStatus | None = None,
        **extra_fields: Any,
    ) -> bool:
        """
        Create user in Firestore

        Args:
            user_id: Firebase user ID
            name: User name
            email: User email
            role: User role
            approval_status: Approval status for evaluators/students only
            extra_fields: Additional profile fields

        Returns:
            True if successful
        """
        try:
            user_data = {
                "name": name,
                "email": email,
                "role": role,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
                **extra_fields,
            }
            if role in ("evaluator", "student") and approval_status is not None:
                user_data["approval_status"] = approval_status

            self.firebase.set_document("users", user_id, user_data)
            logger.info(f"User created in Firestore: {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error creating user in Firestore: {str(e)}")
            raise

    def get_user(self, user_id: str) -> Optional[dict[str, Any]]:
        """
        Get user from Firestore

        Args:
            user_id: User ID

        Returns:
            User data or None
        """
        try:
            return self.firebase.get_document("users", user_id)
        except Exception as e:
            logger.error(f"Error getting user: {str(e)}")
            return None

    def find_by_field(self, field: str, value: str) -> Optional[dict[str, Any]]:
        """Find a user document by a unique field value."""
        try:
            matches = self.firebase.query_collection("users", field, "==", value)
            return matches[0] if matches else None
        except Exception as e:
            logger.error("Error finding user by %s: %s", field, str(e))
            return None

    def update_user(self, user_id: str, data: dict[str, Any]) -> bool:
        """
        Update user in Firestore

        Args:
            user_id: User ID
            data: Data to update

        Returns:
            True if successful
        """
        try:
            data["updated_at"] = datetime.utcnow().isoformat()
            self.firebase.update_document("users", user_id, data)
            logger.info(f"User updated: {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error updating user: {str(e)}")
            raise

    def get_non_admin_users(self) -> list[dict[str, Any]]:
        """
        Get all users except admins (students and evaluators).

        Returns:
            List of non-admin users
        """
        try:
            users = self.firebase.get_collection("users")
            return [user for user in users if user.get("role") != "admin"]
        except Exception as e:
            logger.error(f"Error getting users: {str(e)}")
            return []

    def get_evaluators(self, approval_status: Optional[ApprovalStatus] = None) -> list[dict[str, Any]]:
        """Get evaluator users, optionally filtered by approval status."""
        try:
            users = self.firebase.query_collection("users", "role", "==", "evaluator")
            if approval_status:
                return [
                    user for user in users if user.get("approval_status") == approval_status
                ]
            return users
        except Exception as e:
            logger.error("Error getting evaluators: %s", str(e))
            return []

    def approve_evaluator(self, user_id: str) -> dict[str, Any]:
        """Approve a pending evaluator account."""
        user_data = self.get_user(user_id)
        if not user_data:
            raise ValueError("User not found")
        if user_data.get("role") != "evaluator":
            raise ValueError("User is not an evaluator")
        if user_data.get("approval_status") == "approved":
            raise ValueError("Evaluator is already approved")

        self.update_user(user_id, {"approval_status": "approved"})
        updated = self.get_user(user_id)
        if not updated:
            raise ValueError("Failed to load updated evaluator profile")
        return updated

    def delete_user(self, user_id: str) -> bool:
        """
        Delete user from Firestore and Firebase Auth

        Args:
            user_id: User ID

        Returns:
            True if successful
        """
        try:
            self.firebase.delete_document("users", user_id)
            self.firebase.delete_user(user_id)
            logger.info(f"User deleted: {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting user: {str(e)}")
            raise

    def user_exists(self, email: str) -> bool:
        """
        Check if user exists by email

        Args:
            email: User email

        Returns:
            True if user exists
        """
        try:
            users = self.firebase.query_collection("users", "email", "==", email)
            return len(users) > 0
        except Exception as e:
            logger.error(f"Error checking user existence: {str(e)}")
            return False

    @staticmethod
    def to_user_response(user_id: str, user_data: dict[str, Any]) -> UserResponse:
        """Map a Firestore user document to an API response."""
        role = user_data.get("role", "student")
        approval_status = None
        if role == "evaluator":
            approval_status = user_data.get("approval_status", "pending")
        elif role == "student":
            approval_status = user_data.get("approval_status", "approved")

        return UserResponse(
            id=user_id,
            first_name=user_data.get("first_name", ""),
            last_name=user_data.get("last_name", ""),
            name=user_data.get("name", ""),
            email=user_data.get("email", ""),
            role=role,
            niat_id=user_data.get("niat_id"),
            employee_id=user_data.get("employee_id"),
            mobile_no=user_data.get("mobile_no"),
            approval_status=approval_status,
            created_at=user_data.get("created_at"),
            updated_at=user_data.get("updated_at"),
        )
