"""Access management router — faithful adaptation of sicaad AccessController.

Endpoints (all under prefix /api, guarded by auth + require_menu_access("/app/accesses")):
- GET  /users/search?query=          → user autocomplete (by name / email).
- GET  /menus/hierarchy              → full active menu tree for access admin UI.
- GET  /access-levels                → ordered list of active access levels.
- GET  /users/{user_id}/accesses     → active grants for a user.
- PUT  /users/{user_id}/accesses     → delta save (add / update / delete grants).
- GET  /access-presets               → active presets with their menu+level entries.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps import get_current_user, require_menu_access, verify_csrf
from app.models.menu import AccessLevelModel, AccessPreset, AccessPresetMenu, Menu, UserMenuAccess
from app.models.user import User
from app.schemas.menu import MenuHierarchyNode
from app.schemas.user import (
    AccessChanges,
    AccessLevelOut,
    AccessPresetMenuOut,
    AccessPresetOut,
    UserAccessOut,
    UserSearchResult,
)

router = APIRouter(prefix="/api", tags=["access"])

# Shared dependency: requires auth + access to the accesses menu
_access_guard = Depends(require_menu_access("/app/accesses"))


# ---------------------------------------------------------------------------
# Helper: build a nested MenuHierarchyNode tree from a flat list of menus
# ---------------------------------------------------------------------------


def _build_hierarchy(menus: list[Menu], parent_id: int | None = None, level: int = 0) -> list[MenuHierarchyNode]:
    """Recursively build the menu hierarchy for the access UI."""
    nodes: list[MenuHierarchyNode] = []
    for m in menus:
        if m.parent_id == parent_id:
            node = MenuHierarchyNode(
                id=m.id,
                parent_id=m.parent_id,
                label=m.label,
                icon=m.icon,
                route=m.route,
                description=m.description,
                order=m.order,
                is_free=m.is_free,
                has_access_levels=m.has_access_levels,
                level=level,
                children=_build_hierarchy(menus, parent_id=m.id, level=level + 1),
            )
            nodes.append(node)
    nodes.sort(key=lambda n: n.order)
    return nodes


# ---------------------------------------------------------------------------
# GET /api/users/search?query= — user autocomplete
# ---------------------------------------------------------------------------


@router.get(
    "/users/search",
    response_model=list[UserSearchResult],
    summary="Search users (autocomplete)",
)
async def search_users(
    query: str = Query(default="", description="Search terms (space-separated)"),
    db: AsyncSession = Depends(get_db),
    _current: User = Depends(get_current_user),
    _access=_access_guard,
):
    """Search users by name or email (case-insensitive).

    The query is split into whitespace-separated terms; every term must match
    the user's name OR email (AND between terms, OR within each term's fields).
    Returns at most 10 results. Each result includes a formatted ``display`` label.
    """
    q = query.strip()
    if not q:
        return []

    terms = q.split()
    stmt = select(User)
    for term in terms:
        like = f"%{term}%"
        stmt = stmt.where(
            (User.name.ilike(like)) | (User.email.ilike(like))
        )
    stmt = stmt.order_by(User.name).limit(10)

    result = await db.execute(stmt)
    users = result.scalars().all()

    return [
        UserSearchResult(
            id=u.id,
            name=u.name,
            email=u.email,
            display=f"{u.name} ({u.email})",
        )
        for u in users
    ]


# ---------------------------------------------------------------------------
# GET /api/menus/hierarchy — full active menu tree for access admin
# ---------------------------------------------------------------------------


@router.get(
    "/menus/hierarchy",
    response_model=list[MenuHierarchyNode],
    summary="Full menu hierarchy for access administration",
)
async def get_menus_hierarchy(
    db: AsyncSession = Depends(get_db),
    _current: User = Depends(get_current_user),
    _access=_access_guard,
):
    """Return all ACTIVE menus as a nested tree for the access administration UI.

    Includes free, restricted, and container items. Each node carries
    ``level`` (depth starting at 0), ``is_free``, ``has_access_levels``.
    """
    stmt = select(Menu).where(Menu.is_active.is_(True)).order_by(Menu.order)
    result = await db.execute(stmt)
    menus: list[Menu] = list(result.scalars().all())
    return _build_hierarchy(menus, parent_id=None, level=0)


# ---------------------------------------------------------------------------
# GET /api/access-levels — ordered list of active access levels
# ---------------------------------------------------------------------------


@router.get(
    "/access-levels",
    response_model=list[AccessLevelOut],
    summary="Active access levels ordered by priority",
)
async def list_access_levels(
    db: AsyncSession = Depends(get_db),
    _current: User = Depends(get_current_user),
    _access=_access_guard,
):
    """Return all active access levels ordered by priority ascending."""
    stmt = (
        select(AccessLevelModel)
        .where(AccessLevelModel.is_active.is_(True))
        .order_by(AccessLevelModel.priority)
    )
    result = await db.execute(stmt)
    levels = result.scalars().all()
    return [AccessLevelOut(key=lv.key, name=lv.name) for lv in levels]


# ---------------------------------------------------------------------------
# GET /api/users/{user_id}/accesses — active grants for a user
# ---------------------------------------------------------------------------


@router.get(
    "/users/{user_id}/accesses",
    response_model=list[UserAccessOut],
    summary="User's active menu grants",
)
async def get_user_accesses(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _current: User = Depends(get_current_user),
    _access=_access_guard,
):
    """Return the active menu grants for the specified user.

    Each entry contains ``menu_id`` and ``access_level`` (the AccessLevel key string).
    """
    # Verify user exists
    user_result = await db.execute(select(User).where(User.id == user_id))
    if user_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado.",
        )

    stmt = (
        select(UserMenuAccess)
        .where(
            UserMenuAccess.user_id == user_id,
            UserMenuAccess.is_active.is_(True),
        )
    )
    result = await db.execute(stmt)
    grants = result.scalars().all()

    # Resolve access level keys; load levels by id once
    if not grants:
        return []

    level_ids = {g.access_level_id for g in grants}
    lvl_stmt = select(AccessLevelModel).where(AccessLevelModel.id.in_(level_ids))
    lvl_result = await db.execute(lvl_stmt)
    level_map: dict[int, str] = {lv.id: lv.key for lv in lvl_result.scalars().all()}

    return [
        UserAccessOut(
            menu_id=g.menu_id,
            access_level=level_map.get(g.access_level_id, "capturista"),
        )
        for g in grants
    ]


# ---------------------------------------------------------------------------
# PUT /api/users/{user_id}/accesses — delta save grants
# ---------------------------------------------------------------------------


@router.put(
    "/users/{user_id}/accesses",
    summary="Update user's menu accesses (delta)",
)
async def update_user_accesses(
    user_id: int,
    body: AccessChanges,
    db: AsyncSession = Depends(get_db),
    _current: User = Depends(get_current_user),
    _access=_access_guard,
    _csrf: None = Depends(verify_csrf),
):
    """Apply a delta list of access changes for the specified user.

    Body format::

        {
            "cambios": [
                {"menu_id": 5, "action": "add",    "access_level": "super_admin"},
                {"menu_id": 6, "action": "update", "access_level": "capturista"},
                {"menu_id": 7, "action": "delete"}
            ]
        }

    Actions:
    - **add**: Create a new grant, OR reactivate a soft-deleted one, setting
      ``access_level_id`` and ``is_active=True``.
    - **update**: Update the ``access_level_id`` on the existing grant (active or not).
    - **delete**: Soft-delete — set ``is_active=False`` on the existing grant.

    Returns a summary of processed counts per action.
    """
    # Verify user exists
    user_result = await db.execute(select(User).where(User.id == user_id))
    if user_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado.",
        )

    procesados = {"add": 0, "update": 0, "delete": 0}

    for cambio in body.cambios:
        menu_id = cambio.menu_id
        action = cambio.action
        access_level_key = cambio.access_level

        # Validate action value
        if action not in ("add", "update", "delete"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Acción inválida: '{action}'. Debe ser add, update o delete.",
            )

        # Validate menu exists
        menu_result = await db.execute(select(Menu).where(Menu.id == menu_id))
        if menu_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"El menú con id {menu_id} no existe.",
            )

        # Resolve access level (required for add / update)
        access_level_obj: AccessLevelModel | None = None
        if action in ("add", "update"):
            if not access_level_key:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"'access_level' es requerido para la acción '{action}'.",
                )
            lvl_result = await db.execute(
                select(AccessLevelModel).where(AccessLevelModel.key == access_level_key)
            )
            access_level_obj = lvl_result.scalar_one_or_none()
            if access_level_obj is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Nivel de acceso '{access_level_key}' no encontrado.",
                )

        # Fetch existing grant (active or inactive)
        existing_result = await db.execute(
            select(UserMenuAccess).where(
                UserMenuAccess.user_id == user_id,
                UserMenuAccess.menu_id == menu_id,
            )
        )
        existing = existing_result.scalar_one_or_none()

        if action == "add":
            if existing is None:
                # Create a brand-new grant
                db.add(
                    UserMenuAccess(
                        user_id=user_id,
                        menu_id=menu_id,
                        access_level_id=access_level_obj.id,
                        is_active=True,
                    )
                )
                procesados["add"] += 1
            elif not existing.is_active:
                # Reactivate a previously soft-deleted grant
                existing.is_active = True
                existing.access_level_id = access_level_obj.id
                procesados["add"] += 1
            # If already active, no-op (idempotent)

        elif action == "update":
            if existing is not None:
                existing.access_level_id = access_level_obj.id
                procesados["update"] += 1

        elif action == "delete":
            if existing is not None:
                # Soft-delete: mark inactive instead of removing
                existing.is_active = False
                procesados["delete"] += 1

    await db.commit()

    return {
        "message": "Accesos procesados correctamente",
        "procesados": procesados,
    }


# ---------------------------------------------------------------------------
# GET /api/access-presets — active presets with their menu+level entries
# ---------------------------------------------------------------------------


@router.get(
    "/access-presets",
    response_model=list[AccessPresetOut],
    summary="Active access presets",
)
async def list_access_presets(
    db: AsyncSession = Depends(get_db),
    _current: User = Depends(get_current_user),
    _access=_access_guard,
):
    """Return all active access presets, each with its list of menu+level entries.

    Response shape per preset::

        {
            "id": 1,
            "name": "Administración general",
            "description": "...",
            "menus": [
                {"menu_id": 3, "access_level": "administrator"},
                ...
            ]
        }

    Applying a preset to a user is done client-side (build a delta from these
    entries) and then saved via the existing PUT /users/{user_id}/accesses endpoint.
    """
    # Fetch all active presets
    preset_stmt = (
        select(AccessPreset)
        .where(AccessPreset.is_active.is_(True))
        .order_by(AccessPreset.name)
    )
    preset_result = await db.execute(preset_stmt)
    presets: list[AccessPreset] = list(preset_result.scalars().all())

    if not presets:
        return []

    preset_ids = [p.id for p in presets]

    # Fetch all preset-menu rows for the active presets in one query
    pm_stmt = select(AccessPresetMenu).where(AccessPresetMenu.preset_id.in_(preset_ids))
    pm_result = await db.execute(pm_stmt)
    preset_menus: list[AccessPresetMenu] = list(pm_result.scalars().all())

    # Fetch the access level keys we need
    level_ids = {pm.access_level_id for pm in preset_menus}
    if level_ids:
        lvl_stmt = select(AccessLevelModel).where(AccessLevelModel.id.in_(level_ids))
        lvl_result = await db.execute(lvl_stmt)
        level_map: dict[int, str] = {lv.id: lv.key for lv in lvl_result.scalars().all()}
    else:
        level_map = {}

    # Group preset-menu entries by preset_id
    menus_by_preset: dict[int, list[AccessPresetMenuOut]] = {p.id: [] for p in presets}
    for pm in preset_menus:
        menus_by_preset[pm.preset_id].append(
            AccessPresetMenuOut(
                menu_id=pm.menu_id,
                access_level=level_map.get(pm.access_level_id, "capturista"),
            )
        )

    return [
        AccessPresetOut(
            id=p.id,
            name=p.name,
            description=p.description,
            menus=menus_by_preset[p.id],
        )
        for p in presets
    ]
