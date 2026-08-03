"""Pydantic request models for the API (input validation, spec section 10)."""

from pydantic import BaseModel, ConfigDict, Field

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


class ReleaseStatePatch(BaseModel):
    """Partial state merge for POST /releases/{id}/state (spec 10)."""

    model_config = ConfigDict(extra="forbid")

    seen: bool | None = None
    hidden: bool | None = None
    favorite: bool | None = None


class SeenAllRequest(BaseModel):
    """Optional ISO-date range for POST /releases/seen-all (spec 10)."""

    model_config = ConfigDict(populate_by_name=True)

    from_: str | None = Field(default=None, alias="from", max_length=10)
    to: str | None = Field(default=None, max_length=10)
