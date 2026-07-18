from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.user import UserRole
from app.schemas.common import PaginationMetadata

_USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{3,32}$")


def _validate_password_strength(password: str) -> str:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long")
    if not any(char.isalpha() for char in password):
        raise ValueError("Password must contain at least one letter")
    if not any(char.isdigit() for char in password):
        raise ValueError("Password must contain at least one digit")
    return password


def _validate_username(username: str) -> str:
    if not _USERNAME_PATTERN.match(username):
        raise ValueError(
            "Username must be 3-32 characters and contain only letters, digits, '-' or '_'"
        )
    return username


class UserCreate(BaseModel):
    email: EmailStr
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        return _validate_username(value)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return _validate_password_strength(value)


class UserUpdate(BaseModel):
    """Self-service profile update. Cannot change role or active status."""

    email: EmailStr | None = None
    username: str | None = None

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str | None) -> str | None:
        return _validate_username(value) if value is not None else value


class UserAdminUpdate(BaseModel):
    """Administrative update. May change any mutable field, including role and status."""

    email: EmailStr | None = None
    username: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str | None) -> str | None:
        return _validate_username(value) if value is not None else value


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        return _validate_password_strength(value)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    username: str
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserListResponse(BaseModel):
    items: list[UserResponse]
    pagination: PaginationMetadata


class UserFilterParams(BaseModel):
    role: UserRole | None = None
    is_active: bool | None = None
    search: str | None = Field(default=None, max_length=255)
