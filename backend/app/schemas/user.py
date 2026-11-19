"""Pydantic schemas for representing users in API responses."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator


class UserOut(BaseModel):
    """Public representation of a user (never exposes password_hash)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str
    is_active: bool

    @classmethod
    def from_orm_user(cls, user: object) -> "UserOut":
        """Build the schema from the ORM User model."""
        return cls(
            id=user.id,  # type: ignore[attr-defined]
            email=user.email,  # type: ignore[attr-defined]
            name=user.name,  # type: ignore[attr-defined]
            is_active=user.is_active,  # type: ignore[attr-defined]
        )


# ---------------------------------------------------------------------------
# Schemas for the user administration CRUD
# ---------------------------------------------------------------------------


class UserAdminOut(BaseModel):
    """Full user view for the administration panel.

    Includes the creation date. Never exposes password_hash.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str
    is_active: bool
    created_at: datetime

    @classmethod
    def from_orm_user(cls, user: object) -> "UserAdminOut":
        """Build the schema from the ORM User model."""
        return cls(
            id=user.id,  # type: ignore[attr-defined]
            email=user.email,  # type: ignore[attr-defined]
            name=user.name,  # type: ignore[attr-defined]
            is_active=user.is_active,  # type: ignore[attr-defined]
            created_at=user.created_at,  # type: ignore[attr-defined]
        )


class UserCreate(BaseModel):
    """Data required to create a new user from the administration panel."""

    email: str
    name: str
    # Minimum 6-character password validated at the Pydantic level
    password: str
    # By default the user is created as active
    is_active: bool = True

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        """Verify that the password has at least 6 characters."""
        if len(v) < 6:
            raise ValueError("La contraseña debe tener al menos 6 caracteres.")
        return v


class UserUpdate(BaseModel):
    """Fields allowed when updating an existing user.

    Password is optional: if omitted or empty, it is not modified.
    """

    email: str
    name: str
    is_active: bool
    # If password is None or an empty string, the password is not updated
    password: Optional[str] = None


# ---------------------------------------------------------------------------
# Schemas for the access module
# ---------------------------------------------------------------------------


class UserSearchResult(BaseModel):
    """User search result for the access administration autocomplete."""

    id: int
    name: str
    email: str
    # Formatted label: "name (email)"
    display: str


class UserAccessOut(BaseModel):
    """Active grant row returned by GET /users/{user_id}/accesses."""

    menu_id: int
    # Key of the access level (e.g. "super_admin")
    access_level: str


class AccessChange(BaseModel):
    """Single change item in the delta save body."""

    menu_id: int
    action: str  # "add" | "update" | "delete"
    access_level: Optional[str] = None


class AccessChanges(BaseModel):
    """Body for PUT /users/{user_id}/accesses — delta save format."""

    cambios: list[AccessChange]


class AccessLevelOut(BaseModel):
    """Access level entry returned by GET /access-levels."""

    model_config = ConfigDict(from_attributes=True)

    key: str
    name: str


# ---------------------------------------------------------------------------
# Schemas for the access presets module
# ---------------------------------------------------------------------------


class AccessPresetMenuOut(BaseModel):
    """Single menu entry within an access preset."""

    menu_id: int
    # Key of the access level assigned to this menu in the preset
    access_level: str


class AccessPresetOut(BaseModel):
    """Access preset returned by GET /access-presets."""

    id: int
    name: str
    description: Optional[str] = None
    # List of menu+level pairs that make up this preset
    menus: list[AccessPresetMenuOut]
