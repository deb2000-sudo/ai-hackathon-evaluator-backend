"""
Firebase service for authentication and Firestore database
"""

import json
import logging
import os
from typing import Any, Optional

import firebase_admin
from firebase_admin import auth, credentials, firestore


logger = logging.getLogger(__name__)


class FirebaseService:
    """
    Service for Firebase operations - Authentication and Firestore
    """

    _instance = None
    _db = None
    _auth = None

    def __new__(cls):
        """Singleton pattern for Firebase service"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize Firebase app"""
        if not self._initialized:
            try:
                # Check if Firebase app is already initialized
                firebase_admin.get_app()
            except ValueError:
                # Firebase app not initialized, initialize it
                # Note: In production, use environment variables for sensitive data
                from dotenv import load_dotenv

                load_dotenv()

                # Get Firebase credentials from environment
                firebase_project_id = os.getenv("FIREBASE_PROJECT_ID")
                firebase_private_key = os.getenv("FIREBASE_PRIVATE_KEY")
                firebase_client_email = os.getenv("FIREBASE_CLIENT_EMAIL")

                missing = [
                    key
                    for key, value in {
                        "FIREBASE_PROJECT_ID": firebase_project_id,
                        "FIREBASE_PRIVATE_KEY": firebase_private_key,
                        "FIREBASE_CLIENT_EMAIL": firebase_client_email,
                    }.items()
                    if not value
                ]
                if missing:
                    raise ValueError(
                        "Missing Firebase configuration: " + ", ".join(missing)
                    )

                # Parse and use credentials
                cred_dict = {
                    "type": "service_account",
                    "project_id": firebase_project_id,
                    "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID", ""),
                    "private_key": firebase_private_key.replace("\\n", "\n"),
                    "client_email": firebase_client_email,
                    "client_id": os.getenv("FIREBASE_CLIENT_ID", ""),
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }

                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(
                    cred,
                    {
                        "projectId": firebase_project_id,
                        "databaseURL": os.getenv(
                            "FIREBASE_DATABASE_URL", ""
                        ),
                    },
                )

            self._db = firestore.client()
            self._auth = auth
            self._initialized = True

    # ==================== Authentication Methods ====================

    def create_user(
        self, email: str, password: str, display_name: str = ""
    ) -> dict[str, Any]:
        """
        Create a new Firebase user

        Args:
            email: User email
            password: User password
            display_name: User display name

        Returns:
            Dictionary with user_id and additional info
        """
        try:
            user = self._auth.create_user(
                email=email, password=password, display_name=display_name
            )
            logger.info(f"User created successfully: {user.uid}")
            return {"user_id": user.uid, "email": user.email}
        except auth.EmailAlreadyExistsError:
            raise ValueError(f"Email {email} already exists")
        except Exception as e:
            logger.error(f"Error creating user: {str(e)}")
            raise Exception(f"Error creating user: {str(e)}")

    def delete_user(self, user_id: str) -> bool:
        """
        Delete a Firebase user

        Args:
            user_id: User ID to delete

        Returns:
            True if successful
        """
        try:
            self._auth.delete_user(user_id)
            logger.info(f"User deleted: {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting user {user_id}: {str(e)}")
            raise Exception(f"Error deleting user: {str(e)}")

    def verify_id_token(self, token: str) -> dict[str, Any]:
        """
        Verify Firebase ID token

        Args:
            token: ID token to verify

        Returns:
            Decoded token containing user_id and claims
        """
        try:
            decoded_token = self._auth.verify_id_token(token)
            return decoded_token
        except auth.InvalidIdTokenError:
            raise ValueError("Invalid ID token")
        except auth.ExpiredIdTokenError:
            raise ValueError("ID token has expired")
        except auth.RevokedIdTokenError:
            raise ValueError("ID token has been revoked")
        except ValueError as e:
            raise ValueError(str(e))
        except Exception as e:
            logger.error(f"Error verifying token: {str(e)}")
            raise Exception(f"Error verifying token: {str(e)}")

    def get_user(self, user_id: str) -> Any:
        """
        Get user by ID

        Args:
            user_id: User ID

        Returns:
            Firebase user object
        """
        try:
            return self._auth.get_user(user_id)
        except Exception as e:
            logger.error(f"Error getting user {user_id}: {str(e)}")
            return None

    def get_user_by_email(self, email: str) -> Any:
        """
        Get user by email

        Args:
            email: User email

        Returns:
            Firebase user object
        """
        try:
            return self._auth.get_user_by_email(email)
        except Exception as e:
            logger.error(f"Error getting user by email {email}: {str(e)}")
            return None

    # ==================== Firestore Methods ====================

    def set_document(
        self, collection: str, document_id: str, data: dict[str, Any]
    ) -> bool:
        """
        Set a document in Firestore

        Args:
            collection: Collection name
            document_id: Document ID
            data: Document data

        Returns:
            True if successful
        """
        try:
            self._db.collection(collection).document(document_id).set(data)
            logger.info(f"Document set: {collection}/{document_id}")
            return True
        except Exception as e:
            logger.error(f"Error setting document: {str(e)}")
            raise Exception(f"Error setting document: {str(e)}")

    def get_document(self, collection: str, document_id: str) -> Optional[dict[str, Any]]:
        """
        Get a document from Firestore

        Args:
            collection: Collection name
            document_id: Document ID

        Returns:
            Document data or None if not found
        """
        try:
            doc = self._db.collection(collection).document(document_id).get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error(f"Error getting document: {str(e)}")
            return None

    def update_document(
        self, collection: str, document_id: str, data: dict[str, Any]
    ) -> bool:
        """
        Update a document in Firestore

        Args:
            collection: Collection name
            document_id: Document ID
            data: Data to update

        Returns:
            True if successful
        """
        try:
            self._db.collection(collection).document(document_id).update(data)
            logger.info(f"Document updated: {collection}/{document_id}")
            return True
        except Exception as e:
            logger.error(f"Error updating document: {str(e)}")
            raise Exception(f"Error updating document: {str(e)}")

    def delete_document(self, collection: str, document_id: str) -> bool:
        """
        Delete a document from Firestore

        Args:
            collection: Collection name
            document_id: Document ID

        Returns:
            True if successful
        """
        try:
            self._db.collection(collection).document(document_id).delete()
            logger.info(f"Document deleted: {collection}/{document_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting document: {str(e)}")
            raise Exception(f"Error deleting document: {str(e)}")

    def get_collection(
        self, collection: str, filters: Optional[dict[str, Any]] = None
    ) -> list[dict[str, Any]]:
        """
        Get all documents from a collection

        Args:
            collection: Collection name
            filters: Optional filters (not implemented simply here)

        Returns:
            List of documents with their IDs
        """
        try:
            docs = self._db.collection(collection).stream()
            return [{"id": doc.id, **doc.to_dict()} for doc in docs]
        except Exception as e:
            logger.error(f"Error getting collection: {str(e)}")
            return []

    def query_collection(
        self, collection: str, field: str, operator: str, value: Any
    ) -> list[dict[str, Any]]:
        """
        Query a collection

        Args:
            collection: Collection name
            field: Field to query
            operator: Comparison operator (==, <, >, <=, >=)
            value: Value to compare

        Returns:
            List of matching documents
        """
        try:
            query = self._db.collection(collection)

            if operator == "==":
                query = query.where(field, "==", value)
            elif operator == "<":
                query = query.where(field, "<", value)
            elif operator == ">":
                query = query.where(field, ">", value)
            elif operator == "<=":
                query = query.where(field, "<=", value)
            elif operator == ">=":
                query = query.where(field, ">=", value)

            docs = query.stream()
            return [{"id": doc.id, **doc.to_dict()} for doc in docs]
        except Exception as e:
            logger.error(f"Error querying collection: {str(e)}")
            return []

    def batch_write(self, operations: list[dict[str, Any]]) -> bool:
        """
        Perform batch write operations

        Args:
            operations: List of operations
                       (set, update, delete)

        Returns:
            True if successful
        """
        try:
            batch = self._db.batch()

            for operation in operations:
                op_type = operation.get("type")
                collection = operation.get("collection")
                document_id = operation.get("document_id")
                data = operation.get("data", {})

                ref = self._db.collection(collection).document(document_id)

                if op_type == "set":
                    batch.set(ref, data)
                elif op_type == "update":
                    batch.update(ref, data)
                elif op_type == "delete":
                    batch.delete(ref)

            batch.commit()
            logger.info("Batch write completed")
            return True
        except Exception as e:
            logger.error(f"Error during batch write: {str(e)}")
            raise Exception(f"Error during batch write: {str(e)}")
