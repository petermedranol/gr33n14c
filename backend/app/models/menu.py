"""ORM models for the navigation menu and access permissions.

- ``AccessLevelModel``: DB table ``access_levels`` — the catalogue of access levels.
- ``Menu``: menu item with tree support (self-referencing via parent_id).
- ``UserMenuAccess``: grants a user explicit access to a menu item with a specific level.
- ``AccessPreset``: named preset of menu-access pairs (table: access_presets).
- ``AccessPresetMenu``: one menu+level entry within a preset (table: access_preset_menus).
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class AccessLevelModel(Base):
    """Catalogue of access levels (table: access_levels).

    Keys: lectura, capturista, administrator, super_admin.
    Priority: 1=lowest, 4=highest.
    """

    __tablename__ = "access_levels"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # Unique string key used in the API and stored on grants
    key: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    # Human-readable name displayed in the UI
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Optional description shown in administration screens
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Priority determines hierarchy: 1=lowest access, 4=highest
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Soft-disable without deleting the record
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Grants that reference this level
    user_menu_accesses: Mapped[list["UserMenuAccess"]] = relationship(
        "UserMenuAccess", back_populates="access_level_obj", lazy="select"
    )


class Menu(Base):
    """Navigation menu item, optionally nested under a parent."""

    __tablename__ = "menus"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # FK to the same table for nested menus (None = root)
    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("menus.id"), nullable=True, index=True
    )
    # Text displayed in the UI
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    # Icon name (e.g. Material Icon name or CSS class)
    icon: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Angular route this item navigates to (None for container items)
    route: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Long description shown in administration screens
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Position within its level for ordering the menu
    order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # If True, any authenticated user can see this menu item
    is_free: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # If True, free items can still have an access level grant (e.g. dashboard stats)
    has_access_levels: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Allows hiding an item without deleting it
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Direct children of this menu item (one-to-many: parent → children)
    children: Mapped[list["Menu"]] = relationship(
        "Menu",
        foreign_keys="[Menu.parent_id]",
        back_populates="parent",
        lazy="select",
    )
    # Reference to the parent (many-to-one: child → parent)
    parent: Mapped[Optional["Menu"]] = relationship(
        "Menu",
        foreign_keys="[Menu.parent_id]",
        back_populates="children",
        remote_side="Menu.id",
        lazy="select",
    )
    # Explicit permissions granted on this item
    user_accesses: Mapped[list["UserMenuAccess"]] = relationship(
        "UserMenuAccess", back_populates="menu", lazy="select"
    )


class UserMenuAccess(Base):
    """Explicit permission for a user on a menu item, including an access level.

    Uses soft-delete (is_active=False) instead of physical deletion.
    UniqueConstraint ensures one row per (user_id, menu_id) pair.
    """

    __tablename__ = "user_menu_accesses"

    __table_args__ = (UniqueConstraint("user_id", "menu_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # FK to the user being granted access
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    # FK to the menu item being granted access
    menu_id: Mapped[int] = mapped_column(ForeignKey("menus.id"), nullable=False, index=True)
    # FK to the access level for this grant
    access_level_id: Mapped[int] = mapped_column(
        ForeignKey("access_levels.id"), nullable=False, index=True
    )
    # Soft-delete flag: False = revoked without removing the row
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # ORM navigation relationships
    user: Mapped["User"] = relationship("User", back_populates="menu_accesses")
    menu: Mapped["Menu"] = relationship("Menu", back_populates="user_accesses")
    access_level_obj: Mapped["AccessLevelModel"] = relationship(
        "AccessLevelModel", back_populates="user_menu_accesses"
    )


class AccessPreset(Base):
    """Named preset of menu-access pairs that can be applied to a user.

    Table: access_presets.
    """

    __tablename__ = "access_presets"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # Human-readable name; must be unique so upserts can match by name
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    # Optional longer description shown in the administration UI
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Soft-disable without deleting the preset
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Entries that belong to this preset
    preset_menus: Mapped[list["AccessPresetMenu"]] = relationship(
        "AccessPresetMenu", back_populates="preset", cascade="all, delete-orphan", lazy="select"
    )


class AccessPresetMenu(Base):
    """One menu+level entry within an access preset.

    Table: access_preset_menus.
    UniqueConstraint ensures a preset cannot reference the same menu twice.
    """

    __tablename__ = "access_preset_menus"

    __table_args__ = (UniqueConstraint("preset_id", "menu_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # FK to the parent preset
    preset_id: Mapped[int] = mapped_column(
        ForeignKey("access_presets.id"), nullable=False, index=True
    )
    # FK to the menu item covered by this entry
    menu_id: Mapped[int] = mapped_column(
        ForeignKey("menus.id"), nullable=False, index=True
    )
    # FK to the access level assigned for this menu in the preset
    access_level_id: Mapped[int] = mapped_column(
        ForeignKey("access_levels.id"), nullable=False, index=True
    )

    # ORM navigation relationships
    preset: Mapped["AccessPreset"] = relationship("AccessPreset", back_populates="preset_menus")
    menu: Mapped["Menu"] = relationship("Menu", lazy="select")
    access_level_obj: Mapped["AccessLevelModel"] = relationship("AccessLevelModel", lazy="select")
