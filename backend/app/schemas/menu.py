"""Pydantic schemas for navigation menu items."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class MenuItemOut(BaseModel):
    """Menu item serialized for the Angular frontend sidebar.

    The ``children`` field allows building a nested tree.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    # Icon name (may be None if the item has no icon)
    icon: str | None = None
    # Angular route (may be None for items that are grouping containers only)
    route: str | None = None
    order: int
    # Direct children; empty list if the item is a leaf
    children: list[MenuItemOut] = []


# Required for Pydantic to resolve the circular reference in the children field
MenuItemOut.model_rebuild()


# ---------------------------------------------------------------------------
# Schemas for menu administration CRUD
# ---------------------------------------------------------------------------


class MenuAdminOut(BaseModel):
    """Full menu representation for the administration panel (new field set)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    parent_id: Optional[int] = None
    label: str
    icon: Optional[str] = None
    route: Optional[str] = None
    description: Optional[str] = None
    order: int
    is_free: bool
    has_access_levels: bool
    is_active: bool


class MenuCreate(BaseModel):
    """Data required to create a new menu item."""

    parent_id: Optional[int] = None
    label: str
    icon: Optional[str] = None
    route: Optional[str] = None
    description: Optional[str] = None
    order: int = 0
    is_free: bool = False
    has_access_levels: bool = False
    is_active: bool = True


class MenuUpdate(BaseModel):
    """Fields allowed when updating an existing menu item."""

    parent_id: Optional[int] = None
    label: str
    icon: Optional[str] = None
    route: Optional[str] = None
    description: Optional[str] = None
    order: int = 0
    is_free: bool = False
    has_access_levels: bool = False
    is_active: bool = True


# ---------------------------------------------------------------------------
# Schemas for the access module hierarchy endpoint
# ---------------------------------------------------------------------------


class MenuHierarchyNode(BaseModel):
    """Menu node with depth level for the access administration UI."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    parent_id: Optional[int] = None
    label: str
    icon: Optional[str] = None
    route: Optional[str] = None
    description: Optional[str] = None
    order: int
    is_free: bool
    has_access_levels: bool
    # Depth starting at 0 for root nodes
    level: int
    children: list[MenuHierarchyNode] = []


# Required for Pydantic to resolve the circular reference
MenuHierarchyNode.model_rebuild()
