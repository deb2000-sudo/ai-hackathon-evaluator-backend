"""
Email transport for verification OTPs.

Providers (swap with EMAIL_PROVIDER):
- ``firestore`` (default): write to the ``mail`` collection for the Firebase
  Trigger Email extension.
- ``smtp``: stdlib smtplib when SMTP_HOST is set.

Never log the OTP.
"""

from __future__ import annotations

import logging
import os
import smtplib
import uuid
from email.message import EmailMessage
from typing import Protocol

from app.services.firebase import FirebaseService


logger = logging.getLogger(__name__)

OTP_SUBJECT = "Your Drop verification code"
OTP_BODY_TEMPLATE = (
    "Your Drop verification code is: {code}\n\n"
    "This code expires in 10 minutes.\n"
    "If you didn't request it, you can ignore this email.\n"
)


class EmailService(Protocol):
    def send_verification_code(self, to_email: str, code: str) -> None: ...


class FirestoreTriggerEmailService:
    """Queue mail via Firebase Trigger Email extension (``mail`` collection)."""

    def __init__(self, firebase: FirebaseService | None = None):
        self.firebase = firebase or FirebaseService()

    def send_verification_code(self, to_email: str, code: str) -> None:
        body = OTP_BODY_TEMPLATE.format(code=code)
        self.firebase.set_document(
            "mail",
            str(uuid.uuid4()),
            {
                "to": [to_email],
                "message": {
                    "subject": OTP_SUBJECT,
                    "text": body,
                },
            },
        )
        logger.info("Queued verification email via Firestore mail collection")


class SmtpEmailService:
    def send_verification_code(self, to_email: str, code: str) -> None:
        host = os.getenv("SMTP_HOST", "")
        port = int(os.getenv("SMTP_PORT", "587"))
        username = os.getenv("SMTP_USERNAME", "")
        password = os.getenv("SMTP_PASSWORD", "")
        from_addr = os.getenv("SMTP_FROM", username)
        if not host or not from_addr:
            raise RuntimeError("SMTP is not configured")

        message = EmailMessage()
        message["Subject"] = OTP_SUBJECT
        message["From"] = from_addr
        message["To"] = to_email
        message.set_content(OTP_BODY_TEMPLATE.format(code=code))

        with smtplib.SMTP(host, port, timeout=20) as smtp:
            smtp.starttls()
            if username and password:
                smtp.login(username, password)
            smtp.send_message(message)
        logger.info("Sent verification email via SMTP")


class ConsoleEmailService:
    """Local dev — prints OTP to the server log (never returned in API responses)."""

    def send_verification_code(self, to_email: str, code: str) -> None:
        logger.warning(
            "DEV EMAIL OTP for %s: %s (configure EMAIL_PROVIDER=smtp or Trigger Email in prod)",
            to_email,
            code,
        )


class RecordingEmailService:
    """Test double — records recipients, never exposes codes via logs."""

    def __init__(self) -> None:
        self.sent_to: list[str] = []
        self._last_code: str | None = None

    def send_verification_code(self, to_email: str, code: str) -> None:
        self.sent_to.append(to_email)
        self._last_code = code

    def pop_last_code(self) -> str | None:
        code = self._last_code
        self._last_code = None
        return code


def get_email_service(firebase: FirebaseService | None = None) -> EmailService:
    explicit = os.getenv("EMAIL_PROVIDER", "").strip().lower()
    if explicit == "smtp":
        return SmtpEmailService()
    if explicit == "console":
        return ConsoleEmailService()
    if explicit == "firestore":
        return FirestoreTriggerEmailService(firebase=firebase)
    # Default: log OTP locally in development; queue via Firestore elsewhere.
    if os.getenv("ENVIRONMENT", "").strip().lower() == "development":
        return ConsoleEmailService()
    return FirestoreTriggerEmailService(firebase=firebase)
