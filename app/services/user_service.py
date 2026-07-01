"""
User service for managing user operations
"""

import logging
from datetime import datetime
from typing import Any, Optional

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
        role: str = "user",
    ) -> bool:
        """
        Create user in Firestore

        Args:
            user_id: Firebase user ID
            name: User name
            email: User email
            role: User role

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
            }

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
        Get all users except admins.

        Returns:
            List of non-admin users
        """
        try:
            users = self.firebase.get_collection("users")
            return [user for user in users if user.get("role") != "admin"]
        except Exception as e:
            logger.error(f"Error getting users: {str(e)}")
            return []

    def delete_user(self, user_id: str) -> bool:
        """
        Delete user from Firestore and Firebase Auth

        Args:
            user_id: User ID

        Returns:
            True if successful
        """
        try:
            # Delete from Firestore
            self.firebase.delete_document("users", user_id)

            # Delete from Firebase Auth
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
