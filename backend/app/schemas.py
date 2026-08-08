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
    """Add-artist payload (phase 15: ``url`` allows tracking by URL, like the
    retry flow; the URL is parsed locally, never fetched server-side)."""

    name: str | None = Field(default=None, max_length=200)
    provider: str | None = Field(default=None, max_length=20)
    provider_id: str | None = Field(default=None, max_length=200)
    external_url: str | None = Field(default=None, max_length=500)
    url: str | None = Field(default=None, max_length=500)


class ArtistLink(BaseModel):
    """Track-by-URL payload (phase 12b); only parsed, never fetched server-side.

    Either ``url`` (parsed into provider + id) or the explicit
    ``provider``/``provider_id`` pair from the candidate picker.
    """

    url: str | None = Field(default=None, max_length=500)
    provider: str | None = Field(default=None, max_length=20)
    provider_id: str | None = Field(default=None, max_length=200)


class ArtistPatch(BaseModel):
    ignored: int = Field(ge=0, le=1)


class ErrorReport(BaseModel):
    """Client-reported error (phase 12b); scrubbed before persistence."""

    message: str = Field(min_length=1, max_length=2000)
    context: str | None = Field(default=None, max_length=2000)


class ReleaseStatePatch(BaseModel):
    """Partial state merge for POST /releases/{id}/state (spec 10)."""

    model_config = ConfigDict(extra="forbid")

    seen: bool | None = None
    hidden: bool | None = None
    favorite: bool | None = None


class SeenAllRequest(BaseModel):
    """Optional ISO-date range for POST /releases/seen-all (spec 10)."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    from_: str | None = Field(default=None, alias="from", max_length=10)
    to: str | None = Field(default=None, max_length=10)
