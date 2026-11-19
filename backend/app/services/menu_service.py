"""Service that builds the navigation menu tree for a user.

Visibility logic for a menu item:
1. ``is_active`` must be True.
2. A menu is "directly visible" if:
   a) ``is_free`` is True, OR
   b) a ``UserMenuAccess`` row exists for (user.id, menu.id) AND is_active=True.
3. Additionally, every ANCESTOR (parent chain) of a directly-visible menu is
   included so the tree is navigable even if the parent itself is not free/granted.

Visible items are organized into a nested tree by parent_id,
with each level sorted by the ``order`` field.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.menu import Menu, UserMenuAccess
from app.models.user import User
from app.schemas.menu import MenuItemOut


async def build_menu_tree(db: AsyncSession, user: User) -> list[MenuItemOut]:
    """Return the menu tree visible to the given user.

    Args:
        db: Async database session.
        user: Authenticated user.

    Returns:
        List of root items, each with their nested children.
    """
    # Load all active menus in one query
    stmt = select(Menu).where(Menu.is_active.is_(True)).order_by(Menu.order)
    result = await db.execute(stmt)
    all_menus: list[Menu] = list(result.scalars().all())

    # Load the set of menu_ids explicitly granted to this user (ACTIVE grants only)
    access_stmt = select(UserMenuAccess.menu_id).where(
        UserMenuAccess.user_id == user.id,
        UserMenuAccess.is_active.is_(True),
    )
    access_result = await db.execute(access_stmt)
    granted_ids: set[int] = set(access_result.scalars().all())

    # Index all menus by id for O(1) ancestor traversal
    menu_by_id: dict[int, Menu] = {m.id: m for m in all_menus}

    # Determine directly-visible menu ids
    directly_visible: set[int] = set()
    for m in all_menus:
        if m.is_free or m.id in granted_ids:
            directly_visible.add(m.id)

    # Expand to include all ancestors of directly-visible items
    visible_ids: set[int] = set(directly_visible)
    for menu_id in directly_visible:
        m = menu_by_id.get(menu_id)
        while m is not None and m.parent_id is not None:
            if m.parent_id in visible_ids:
                break  # already included; no need to walk further
            visible_ids.add(m.parent_id)
            m = menu_by_id.get(m.parent_id)

    # Filter to only the visible menus, preserving original order
    visible_menus = [m for m in all_menus if m.id in visible_ids]

    return _to_tree(visible_menus)


def _to_tree(menus: list[Menu]) -> list[MenuItemOut]:
    """Convert a flat list of menu items into a nested tree of MenuItemOut."""
    # Index all items by their id for O(1) access
    items: dict[int, MenuItemOut] = {
        m.id: MenuItemOut(
            id=m.id,
            label=m.label,
            icon=m.icon,
            route=m.route,
            order=m.order,
            children=[],
        )
        for m in menus
    }

    roots: list[MenuItemOut] = []

    for menu in menus:
        item = items[menu.id]
        if menu.parent_id is None or menu.parent_id not in items:
            # Root node (or its parent is not visible to this user)
            roots.append(item)
        else:
            # Attach as a child of the visible parent
            items[menu.parent_id].children.append(item)

    # Sort each level (already ordered from the DB, but guaranteed here too)
    _sort_tree(roots)
    return roots


def _sort_tree(items: list[MenuItemOut]) -> None:
    """Recursively sort items and their children by the ``order`` field."""
    items.sort(key=lambda i: i.order)
    for item in items:
        if item.children:
            _sort_tree(item.children)
