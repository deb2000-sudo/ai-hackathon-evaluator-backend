"""
User data models and schemas
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


UserRole = Literal["admin", "evaluator", "student"]
ApprovalStatus = Literal["pending", "approved"]

USER_ROLES: tuple[UserRole, ...] = ("admin", "evaluator", "student")
NXTWAVE_EMAIL_DOMAIN = "@nxtwave.co.in"


class StudentRegisterRequest(BaseModel):
    """Schema for student self-registration."""

    first_name: str = Field(..., min_length=1, max_length=50)
    last_name: str = Field(..., min_length=1, max_length=50)
    niat_id: str = Field(..., min_length=1, max_length=50)
    email: EmailStr
    mobile_no: str = Field(..., min_length=10, max_length=15)
    password: str = Field(..., min_length=6)
    confirm_password: str = Field(..., min_length=6)

    @model_validator(mode="after")
    def validate_registration(self) -> "StudentRegisterRequest":
        if self.password != self.confirm_password:
            raise ValueError("Password and confirm password do not match")
        if not self.mobile_no.isdigit():
            raise ValueError("Mobile number must contain digits only")
        return self


class EvaluatorRegisterRequest(BaseModel):
    """Schema for evaluator self-registration."""

    first_name: str = Field(..., min_length=1, max_length=50)
    last_name: str = Field(..., min_length=1, max_length=50)
    employee_id: str = Field(..., min_length=1, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6)
    confirm_password: str = Field(..., min_length=6)

    @field_validator("email")
    @classmethod
    def validate_nxtwave_email(cls, value: str) -> str:
        if not value.lower().endswith(NXTWAVE_EMAIL_DOMAIN):
            raise ValueError(f"Evaluator email must be a Nxtwave address ({NXTWAVE_EMAIL_DOMAIN})")
        return value.lower()

    @model_validator(mode="after")
    def validate_registration(self) -> "EvaluatorRegisterRequest":
        if self.password != self.confirm_password:
            raise ValueError("Password and confirm password do not match")
        return self


class UserUpdate(BaseModel):
    """Schema for user updates"""

    name: Optional[str] = Field(None, min_length=1, max_length=100)


class UserResponse(BaseModel):
    """Schema for user response"""

    id: str
    first_name: str = ""
    last_name: str = ""
    name: str
    email: str
    role: UserRole
    niat_id: Optional[str] = None
    employee_id: Optional[str] = None
    mobile_no: Optional[str] = None
    approval_status: Optional[ApprovalStatus] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RegisterResponse(BaseModel):
    """Schema for registration response"""

    user_id: str
    email: str
    first_name: str
    last_name: str
    role: UserRole
    approval_status: ApprovalStatus
    message: str


class LoginRequest(BaseModel):
    """Schema for login request"""

    email: EmailStr
    password: str = Field(..., min_length=6)


class LoginResponse(BaseModel):
    """Schema for login response"""

    id_token: str
    user_id: str
    email: str
    name: str
    role: UserRole
    approval_status: Optional[ApprovalStatus] = None


class CurrentUser(BaseModel):
    """Schema for current authenticated user"""

    user_id: str
    email: str
    role: UserRole
    name: str
    approval_status: Optional[ApprovalStatus] = None
