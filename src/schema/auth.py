"""
Pydantic models for Auth (registration, login, profile).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator, AliasChoices
from src.helpers import ValidationError


class RegisterRequest(BaseModel):
    email: str
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=6, max_length=128)
    username: str | None = Field(default=None, max_length=100)

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValidationError("Invalid email address")
        return v


class LoginRequest(BaseModel):
    username: str = Field(
        validation_alias=AliasChoices("username", "email", "identifier"),
        min_length=1,
        max_length=255,
    )
    password: str = Field(min_length=1)

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValidationError("Username or email cannot be empty")
        return v

    @property
    def email(self) -> str:
        return self.username


class TokenResponse(BaseModel):
    token: str
    user_id: str
    name: str
    email: str
    username: str | None = None


class UserProfileResponse(BaseModel):
    id: str
    email: str
    name: str
    username: str | None = None
    tier: str = "registered"
    created_at: datetime
