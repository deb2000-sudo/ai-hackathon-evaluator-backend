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

    def update_user_password(self, user_id: str, new_password: str) -> bool:
        """
        Update a Firebase user's password.

        Args:
            user_id: User ID whose password should be changed
            new_password: The new plaintext password

        Returns:
            True if successful
        """
        try:
            self._auth.update_user(user_id, password=new_password)
            logger.info(f"Password updated for user: {user_id}")
            return True
        except auth.UserNotFoundError:
            raise ValueError("User not found")
        except ValueError as e:
            raise ValueError(str(e))
        except Exception as e:
            logger.error(f"Error updating password for user {user_id}: {str(e)}")
            raise Exception(f"Error updating password: {str(e)}")

    def verify_id_token(
        self, token: str, check_revoked: bool = True
    ) -> dict[str, Any]:
        """
        Verify Firebase ID token.

        ``check_revoked=True`` (default, Phase 5a) rejects tokens after password
        change / admin revoke so stolen cookies stop working sooner.
        """
        try:
            decoded_token = self._auth.verify_id_token(
                token, check_revoked=check_revoked
            )
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

    def verify_password(self, email: str, password: str) -> bool:
        """
        Verify email/password via Identity Toolkit (same path as login).

        Used by change-password when ``current_password`` is supplied or required.
        """
        web_api_key = os.getenv("FIREBASE_WEB_API_KEY")
        if not web_api_key:
            raise ValueError("Firebase configuration error")

        import requests

        try:
            response = requests.post(
                "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword",
                json={
                    "email": email.lower().strip(),
                    "password": password,
                    "returnSecureToken": True,
                },
                params={"key": web_api_key},
                timeout=10,
            )
        except requests.exceptions.RequestException as e:
            logger.error("Network error verifying password: %s", str(e))
            raise Exception("Error verifying password") from e

        return response.status_code == 200

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

    # ==================== Transactions (Phase 3) ====================

    def run_transaction(self, callback):
        """
        Run ``callback(transaction)`` inside a Firestore transaction.

        The callback must use ``txn_get`` / ``txn_set`` / ``txn_update`` for
        reads and writes so concurrent updates cannot clobber each other.
        """
        from google.cloud.firestore_v1 import transactional

        transaction = self._db.transaction()

        @transactional
        def _run(txn):
            return callback(txn)

        return _run(transaction)

    def txn_get(
        self, transaction, collection: str, document_id: str
    ) -> Optional[dict[str, Any]]:
        """Read a document inside an open transaction."""
        ref = self._db.collection(collection).document(document_id)
        snapshot = ref.get(transaction=transaction)
        return snapshot.to_dict() if snapshot.exists else None

    def txn_set(
        self,
        transaction,
        collection: str,
        document_id: str,
        data: dict[str, Any],
    ) -> None:
        """Create/overwrite a document inside an open transaction."""
        ref = self._db.collection(collection).document(document_id)
        transaction.set(ref, data)

    def txn_update(
        self,
        transaction,
        collection: str,
        document_id: str,
        data: dict[str, Any],
    ) -> None:
        """Update fields on a document inside an open transaction."""
        ref = self._db.collection(collection).document(document_id)
        transaction.update(ref, data)