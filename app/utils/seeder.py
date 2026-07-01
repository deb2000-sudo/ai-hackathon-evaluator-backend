"""
Database seeder - Initialize default data
"""

import logging

from app.services.firebase import FirebaseService
from app.services.user_service import UserService


logger = logging.getLogger(__name__)


class DatabaseSeeder:
    """
    Seeder for initializing database with default data
    Creates the default admin user and test user.
    """

    def __init__(self):
        """Initialize seeder"""
        self.firebase = FirebaseService()
        self.user_service = UserService()

    def seed_admin_user(
        self,
        email: str = "admin@nxtwave.co.in",
        password: str = "12345678",
        name: str = "Admin User",
    ) -> bool:
        """
        Create admin user if it doesn't exist
        Admin documents contain minimal fields: email, role, timestamps

        Args:
            email: Admin email
            password: Admin password
            name: Admin name

        Returns:
            True if successful or already exists
        """
        try:
            logger.info(f"Checking if admin user exists: {email}")
            
            # Check if admin user already exists in Firebase Auth
            existing_user = self.firebase.get_user_by_email(email)

            if existing_user:
                logger.info(f"Found existing user in Firebase Auth: {email}")
                user_id = existing_user.uid
                logger.info(f"User ID: {user_id}")
                
                # Check if Firestore record exists
                firestore_user = self.user_service.get_user(user_id)
                
                if firestore_user:
                    logger.info(f"Firestore record found for {email}")
                    return True
                else:
                    logger.warning(f"Firestore record MISSING for {email}")
                    logger.info(f"Creating Firestore record for existing admin user...")
                    
                    # Create minimal Firestore record for admin
                    self._create_admin_firestore_record(user_id, email, name)
                    logger.info(f"Admin Firestore record created for {email}")
                    return True

            # User doesn't exist, create new admin
            logger.info(f"Creating new admin user: {email}")
            user_data = self.firebase.create_user(
                email=email,
                password=password,
                display_name=name,
            )
            user_id = user_data["user_id"]
            logger.info(f"Firebase Auth user created. ID: {user_id}")

            # Create minimal Firestore record for admin
            logger.info(f"Creating admin Firestore record...")
            self._create_admin_firestore_record(user_id, email, name)
            logger.info(f"Admin Firestore record created")

            logger.info(f"Admin user fully created: {email}")
            return True

        except Exception as e:
            logger.error(f"ERROR in seed_admin_user: {str(e)}")
            logger.error(f"Exception type: {type(e).__name__}")
            import traceback
            logger.error(f"Traceback:\n{traceback.format_exc()}")
            raise

    def _create_admin_firestore_record(self, user_id: str, email: str, name: str) -> None:
        """
        Create admin user record in Firestore with minimal fields

        Args:
            user_id: Firebase user ID
            email: User email
            name: User name
        """
        from datetime import datetime
        
        admin_data = {
            "email": email,
            "name": name,
            "role": "admin",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }

        self.firebase.set_document("users", user_id, admin_data)
        logger.info(f"📋 Admin fields: email, name, role, created_at, updated_at")

    def seed_normal_user(
        self,
        email: str = "test@nxtwave.co.in",
        password: str = "12345678",
        name: str = "Test User",
    ) -> bool:
        """
        Create normal user if it doesn't exist
        Normal user documents contain: email, name, role, timestamps

        Args:
            email: User email
            password: User password
            name: User name

        Returns:
            True if successful or already exists
        """
        try:
            logger.info(f"🔍 Checking if normal user exists: {email}")
            
            # Check if user already exists in Firebase Auth
            existing_user = self.firebase.get_user_by_email(email)

            if existing_user:
                logger.info(f"✅ Found existing user in Firebase Auth: {email}")
                user_id = existing_user.uid
                logger.info(f"   User ID: {user_id}")
                
                # Check if Firestore record exists
                firestore_user = self.user_service.get_user(user_id)
                
                if firestore_user:
                    logger.info(f"✅ Firestore record found for {email}")
                    return True
                else:
                    logger.warning(f"⚠️ Firestore record MISSING for {email}")
                    logger.info(f"📝 Creating Firestore record for existing user...")
                    
                    # Create Firestore record for normal user
                    self._create_normal_user_firestore_record(user_id, email, name)
                    logger.info(f"✅ User Firestore record created for {email}")
                    return True

            # User doesn't exist, create new user
            logger.info(f"📝 Creating new user: {email}")
            user_data = self.firebase.create_user(
                email=email,
                password=password,
                display_name=name,
            )
            user_id = user_data["user_id"]
            logger.info(f"✅ Firebase Auth user created. ID: {user_id}")

            # Create Firestore record for normal user
            logger.info(f"📝 Creating user Firestore record...")
            self._create_normal_user_firestore_record(user_id, email, name)
            logger.info(f"✅ User Firestore record created")

            logger.info(f"✅ User fully created: {email}")
            return True

        except Exception as e:
            logger.error(f"❌ ERROR in seed_normal_user: {str(e)}")
            logger.error(f"   Exception type: {type(e).__name__}")
            import traceback
            logger.error(f"   Traceback:\n{traceback.format_exc()}")
            raise

    def _create_normal_user_firestore_record(
        self, user_id: str, email: str, name: str
    ) -> None:
        """
        Create normal user record in Firestore with basic fields

        Args:
            user_id: Firebase user ID
            email: User email
            name: User name
        """
        from datetime import datetime
        
        user_data = {
            "email": email,
            "name": name,
            "role": "user",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }

        self.firebase.set_document("users", user_id, user_data)
        logger.info(f"📋 User fields: email, name, role, created_at, updated_at")

    def seed_all(self) -> bool:
        """
        Run all seeding operations
        Creates admin user and a normal user

        Returns:
            True if all successful
        """
        try:
            logger.info("🌱 Starting database seeding...")
            
            # Seed admin user
            logger.info("\n" + "="*60)
            logger.info("🔑 SEEDING ADMIN USER")
            logger.info("="*60)
            self.seed_admin_user()
            
            # Seed normal user
            logger.info("\n" + "="*60)
            logger.info("👤 SEEDING NORMAL USER")
            logger.info("="*60)
            self.seed_normal_user(
                email="test@nxtwave.co.in",
                password="12345678",
                name="Test User"
            )
            
            logger.info("\n✅ Database seeding completed successfully!")
            return True
        except Exception as e:
            logger.error(f"❌ Error during seeding: {str(e)}")
            raise
