"""ORM model for user accounts.

- ``User``: user account with credentials. No role/type — access is governed
  entirely by the menus explicitly granted to the user via UserMenuAccess.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    # Deferred import to avoid circular dependencies; used in type annotations only
    from app.models.menu import UserMenuAccess


class User(Base):
    """System user with credentials. Access is governed by menu grants."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # Unique, indexed email for fast login lookups
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    # Argon2 hash of the password (never store as plain text)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Display name shown in the UI
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Allows disabling a user without deleting them
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Creation timestamp managed by the database
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationship to the user's menu permissions
    menu_accesses: Mapped[list["UserMenuAccess"]] = relationship(
        "UserMenuAccess", back_populates="user", lazy="select"
    )
