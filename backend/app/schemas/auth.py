"""Pydantic schemas for authentication (login/logout/session responses)."""

from pydantic import BaseModel, ConfigDict

from app.schemas.menu import MenuItemOut
from app.schemas.user import UserOut


class LoginRequest(BaseModel):
    """Request body for POST /api/login."""

    # str instead of EmailStr to accept local domains (.local, .lan, etc.)
    email: str
    password: str
    # If True, a longer-lived token is generated (remembered session)
    remember: bool = False


class Preferences(BaseModel):
    """User preferences and navigation menu for the authenticated session."""

    model_config = ConfigDict(from_attributes=True)

    menuItems: list[MenuItemOut]


class LoginResponse(BaseModel):
    """Response body for a successful login."""

    model_config = ConfigDict(from_attributes=True)

    message: str
    user: UserOut
    preferences: Preferences
