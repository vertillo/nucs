"""Pydantic request models for the API (input validation, spec section 10)."""

from pydantic import BaseModel, Field

from app.security import MIN_PASSWORD_LENGTH


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)


class ArtistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ArtistPatch(BaseModel):
    ignored: int = Field(ge=0, le=1)
