"""Navigation menu router.

Endpoints:
- GET    /api/menus              → current user's menu tree (sidebar nav).
- GET    /api/menus/manage       → flat list of ALL menus (admin).
- POST   /api/menus              → create a menu item (admin).
- PUT    /api/menus/{menu_id}    → update a menu item (admin).
- DELETE /api/menus/{menu_id}    → delete a menu item if it has no children (admin).

All management endpoints require access to the "/app/menus" menu item.
Mutating endpoints also require the CSRF token.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps import get_current_user, require_menu_access, verify_csrf
from app.models.menu import Menu, UserMenuAccess
from app.models.user import User
from app.schemas.menu import MenuAdminOut, MenuCreate, MenuItemOut, MenuUpdate
from app.services.menu_service import build_menu_tree

router = APIRouter(prefix="/api", tags=["menu"])

# Shared dependency: only users with access to "/app/menus" can manage menus
_menus_admin_access = Depends(require_menu_access("/app/menus"))


# ---------------------------------------------------------------------------
# GET /api/menus — current user's menu tree
# ---------------------------------------------------------------------------


@router.get("/menus", response_model=list[MenuItemOut], summary="User menu tree")
async def get_menus(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the navigation menu tree visible to the authenticated user.

    Items are filtered by permissions (is_free or active UserMenuAccess grant) and
    nested by parent_id, ordered by the ``order`` field within each level.
    """
    return await build_menu_tree(db, user)


# ---------------------------------------------------------------------------
# GET /api/menus/manage — flat admin listing
# ---------------------------------------------------------------------------


@router.get(
    "/menus/manage",
    response_model=list[MenuAdminOut],
    summary="All menus (admin)",
)
async def list_menus_admin(
    db: AsyncSession = Depends(get_db),
    _current: User = Depends(get_current_user),
    _access=_menus_admin_access,
):
    """Return ALL menus as a flat list ordered by parent_id (nulls first) then order.

    Used by the administration screen to display and manage the full menu catalogue.
    Includes has_access_levels and description; does not include access_level.
    """
    result = await db.execute(
        select(Menu).order_by(Menu.parent_id.nullsfirst(), Menu.order)
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# POST /api/menus — create menu
# ---------------------------------------------------------------------------


@router.post(
    "/menus",
    response_model=MenuAdminOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create menu item",
)
async def create_menu(
    body: MenuCreate,
    db: AsyncSession = Depends(get_db),
    _current: User = Depends(get_current_user),
    _access=_menus_admin_access,
    _csrf: None = Depends(verify_csrf),
):
    """Create a new menu item.

    Validates that parent_id, if provided, references an existing menu.
    """
    if body.parent_id is not None:
        parent_result = await db.execute(
            select(Menu).where(Menu.id == body.parent_id)
        )
        if parent_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El menú padre indicado no existe.",
            )

    new_menu = Menu(
        parent_id=body.parent_id,
        label=body.label,
        icon=body.icon,
        route=body.route,
        description=body.description,
        order=body.order,
        is_free=body.is_free,
        has_access_levels=body.has_access_levels,
        is_active=body.is_active,
    )
    db.add(new_menu)
    await db.commit()
    await db.refresh(new_menu)
    return new_menu


# ---------------------------------------------------------------------------
# PUT /api/menus/{menu_id} — update menu
# ---------------------------------------------------------------------------


@router.put(
    "/menus/{menu_id}",
    response_model=MenuAdminOut,
    summary="Update menu item",
)
async def update_menu(
    menu_id: int,
    body: MenuUpdate,
    db: AsyncSession = Depends(get_db),
    _current: User = Depends(get_current_user),
    _access=_menus_admin_access,
    _csrf: None = Depends(verify_csrf),
):
    """Update an existing menu item.

    Prevents setting a menu's parent to itself.
    """
    result = await db.execute(select(Menu).where(Menu.id == menu_id))
    menu = result.scalar_one_or_none()
    if menu is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Menú no encontrado.",
        )

    if body.parent_id == menu_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Un menú no puede ser su propio padre.",
        )

    if body.parent_id is not None:
        parent_result = await db.execute(
            select(Menu).where(Menu.id == body.parent_id)
        )
        if parent_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El menú padre indicado no existe.",
            )

    menu.parent_id = body.parent_id
    menu.label = body.label
    menu.icon = body.icon
    menu.route = body.route
    menu.description = body.description
    menu.order = body.order
    menu.is_free = body.is_free
    menu.has_access_levels = body.has_access_levels
    menu.is_active = body.is_active

    await db.commit()
    await db.refresh(menu)
    return menu


# ---------------------------------------------------------------------------
# DELETE /api/menus/{menu_id} — delete menu
# ---------------------------------------------------------------------------


@router.delete(
    "/menus/{menu_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete menu item",
)
async def delete_menu(
    menu_id: int,
    db: AsyncSession = Depends(get_db),
    _current: User = Depends(get_current_user),
    _access=_menus_admin_access,
    _csrf: None = Depends(verify_csrf),
):
    """Permanently delete a menu item.

    Refused (HTTP 400) if the menu has child menus. All UserMenuAccess rows
    referencing this menu are removed before deletion.
    """
    result = await db.execute(select(Menu).where(Menu.id == menu_id))
    menu = result.scalar_one_or_none()
    if menu is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Menú no encontrado.",
        )

    # Refuse deletion if the menu has children
    children_result = await db.execute(
        select(Menu).where(Menu.parent_id == menu_id)
    )
    if children_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No puedes eliminar un menú con submenús.",
        )

    # Remove all user grants for this menu
    await db.execute(
        delete(UserMenuAccess).where(UserMenuAccess.menu_id == menu_id)
    )

    await db.delete(menu)
    await db.commit()
    # HTTP 204 → no response body
