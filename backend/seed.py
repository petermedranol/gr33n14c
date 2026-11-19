"""Idempotent seed script for the Greeniac database.

Creates (or updates) the minimum initial data required for the application to work:
- Access levels catalogue (lectura, capturista, administrator, super_admin).
- Menu tree with free and restricted items (upserted by route or label+parent).
- Administrator user: admin@greeniac.local / Admin2026! (password only set on first create).
- Active menu access grants for the administrator on restricted items (super_admin level).
- Access presets (upserted by name; preset-menu rows are replaced each run).

Safe to run multiple times: matches existing rows and updates all fields.

Usage:
    cd backend
    python seed.py
"""

import asyncio

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.menu import AccessLevelModel, AccessPreset, AccessPresetMenu, Menu, UserMenuAccess
from app.models.user import User

ADMIN_EMAIL = "admin@greeniac.local"
ADMIN_PASSWORD = "Admin2026!"
ADMIN_NAME = "Administrador"

# ---------------------------------------------------------------------------
# Access levels catalogue (key, name, priority)
# ---------------------------------------------------------------------------

ACCESS_LEVELS = [
    {"key": "lectura",       "name": "Lectura",        "priority": 1},
    {"key": "capturista",    "name": "Capturista",      "priority": 2},
    {"key": "administrator", "name": "Administrador",   "priority": 3},
    {"key": "super_admin",   "name": "Super Administrador", "priority": 4},
]

# ---------------------------------------------------------------------------
# Menu tree definition.
# Match key: ``route`` if not None, else (label, parent_label).
# ---------------------------------------------------------------------------

MENU_ITEMS = [
    {
        "label": "Inicio",
        "icon": "🏠",
        "route": "/app/home",
        "order": 1,
        "is_free": True,
        "has_access_levels": False,
        "parent_label": None,
    },
    {
        "label": "Cámara",
        "icon": "📷",
        "route": "/app/camera",
        "order": 2,
        "is_free": True,
        "has_access_levels": False,
        "parent_label": None,
    },
    {
        "label": "Administración",
        "icon": "⚙️",
        "route": None,
        "order": 3,
        "is_free": False,
        "has_access_levels": False,
        "parent_label": None,
    },
    {
        "label": "Usuarios",
        "icon": "👥",
        "route": "/app/users",
        "order": 1,
        "is_free": False,
        "has_access_levels": False,
        "parent_label": "Administración",
    },
    {
        "label": "Menús",
        "icon": "📋",
        "route": "/app/menus",
        "order": 2,
        "is_free": False,
        "has_access_levels": False,
        "parent_label": "Administración",
    },
    {
        "label": "Accesos",
        "icon": "🔒",
        "route": "/app/accesses",
        "order": 3,
        "is_free": False,
        "has_access_levels": False,
        "parent_label": "Administración",
    },
]

# Menus the admin should have super_admin access to
ADMIN_GRANT_LABELS = ["Administración", "Usuarios", "Menús", "Accesos"]

# ---------------------------------------------------------------------------
# Access preset definitions.
# Each entry: preset name (unique match key), description, list of
# (menu_route, access_level_key) pairs. Routes must exist in MENU_ITEMS above.
# ---------------------------------------------------------------------------

ACCESS_PRESETS = [
    {
        "name": "Administración general",
        "description": "Acceso completo de administrador a usuarios, menús y accesos.",
        "is_active": True,
        "entries": [
            {"route": "/app/users",    "access_level_key": "administrator"},
            {"route": "/app/menus",    "access_level_key": "administrator"},
            {"route": "/app/accesses", "access_level_key": "administrator"},
        ],
    },
    {
        "name": "Solo lectura de accesos",
        "description": "Permite consultar la sección de accesos sin modificar nada.",
        "is_active": True,
        "entries": [
            {"route": "/app/accesses", "access_level_key": "lectura"},
        ],
    },
]


# ---------------------------------------------------------------------------
# Seed functions
# ---------------------------------------------------------------------------


async def seed_access_levels(session) -> dict[str, AccessLevelModel]:
    """Upsert access levels and return a dict key → AccessLevelModel."""
    levels: dict[str, AccessLevelModel] = {}
    for data in ACCESS_LEVELS:
        result = await session.execute(
            select(AccessLevelModel).where(AccessLevelModel.key == data["key"])
        )
        level = result.scalar_one_or_none()
        if level is None:
            level = AccessLevelModel(
                key=data["key"],
                name=data["name"],
                priority=data["priority"],
                is_active=True,
            )
            session.add(level)
            await session.flush()
            print(f"  [+] Access level created: {level.key} (id={level.id})")
        else:
            level.name = data["name"]
            level.priority = data["priority"]
            level.is_active = True
            await session.flush()
            print(f"  [~] Access level updated: {level.key} (id={level.id})")
        levels[level.key] = level
    return levels


async def _find_menu(session, data: dict, menus: dict) -> Menu | None:
    """Locate an existing menu row by route (if set) or by (label, parent_id)."""
    if data["route"] is not None:
        result = await session.execute(
            select(Menu).where(Menu.route == data["route"])
        )
        return result.scalar_one_or_none()

    # No route: match by label + parent
    parent_id = None
    if data["parent_label"]:
        parent = menus.get(data["parent_label"])
        parent_id = parent.id if parent else None

    result = await session.execute(
        select(Menu).where(Menu.label == data["label"], Menu.parent_id == parent_id)
    )
    return result.scalar_one_or_none()


async def seed_menus(session) -> dict[str, Menu]:
    """Upsert the menu tree and return a dict label→Menu."""
    menus: dict[str, Menu] = {}

    for data in MENU_ITEMS:
        parent_id = None
        if data["parent_label"]:
            parent = menus.get(data["parent_label"])
            parent_id = parent.id if parent else None

        menu = await _find_menu(session, data, menus)

        if menu is None:
            menu = Menu(
                label=data["label"],
                icon=data.get("icon"),
                route=data.get("route"),
                order=data["order"],
                is_free=data["is_free"],
                has_access_levels=data["has_access_levels"],
                parent_id=parent_id,
                is_active=True,
            )
            session.add(menu)
            await session.flush()
            print(f"  [+] Menu created: {menu.label} (id={menu.id})")
        else:
            menu.label = data["label"]
            menu.icon = data.get("icon")
            menu.order = data["order"]
            menu.is_free = data["is_free"]
            menu.has_access_levels = data["has_access_levels"]
            menu.parent_id = parent_id
            menu.is_active = True
            await session.flush()
            print(f"  [~] Menu updated: {menu.label} (id={menu.id})")

        menus[menu.label] = menu

    return menus


async def seed_admin_user(session) -> User:
    """Create the administrator user if it does not already exist.

    The password is only set on creation; it is never reset on subsequent runs.
    """
    result = await session.execute(
        select(User).where(User.email == ADMIN_EMAIL)
    )
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            email=ADMIN_EMAIL,
            password_hash=hash_password(ADMIN_PASSWORD),
            name=ADMIN_NAME,
            is_active=True,
        )
        session.add(user)
        await session.flush()
        print(f"  [+] Admin user created: {user.email}")
    else:
        # Keep the user active and correct the display name, but do NOT reset the password
        user.name = ADMIN_NAME
        user.is_active = True
        await session.flush()
        print(f"  [~] Admin user updated: {user.email}")
    return user


async def seed_menu_access(
    session,
    user: User,
    menus: dict[str, Menu],
    levels: dict[str, AccessLevelModel],
) -> None:
    """Ensure the administrator has active super_admin grants for restricted menus."""
    super_admin = levels.get("super_admin")
    if super_admin is None:
        print("  [!] super_admin level not found, skipping access grants.")
        return

    for label in ADMIN_GRANT_LABELS:
        menu = menus.get(label)
        if menu is None:
            print(f"  [!] Menu '{label}' not found, skipping access grant.")
            continue

        result = await session.execute(
            select(UserMenuAccess).where(
                UserMenuAccess.user_id == user.id,
                UserMenuAccess.menu_id == menu.id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            session.add(
                UserMenuAccess(
                    user_id=user.id,
                    menu_id=menu.id,
                    access_level_id=super_admin.id,
                    is_active=True,
                )
            )
            print(f"  [+] Access granted: {user.email} → {label} (super_admin)")
        else:
            # Ensure the existing grant is active and has the correct level
            if not existing.is_active or existing.access_level_id != super_admin.id:
                existing.is_active = True
                existing.access_level_id = super_admin.id
                print(f"  [~] Access updated: {user.email} → {label} (super_admin)")
            else:
                print(f"  [ ] Access already exists: {user.email} → {label}")


async def seed_access_presets(
    session,
    menus: dict[str, Menu],
    levels: dict[str, AccessLevelModel],
) -> None:
    """Upsert access presets and replace their menu entries on every run.

    Match key for presets: ``name`` (unique). The preset-menu rows are fully
    replaced each run so that changes to ACCESS_PRESETS are picked up cleanly.
    """
    # Build a route→Menu lookup from the already-seeded menus dict
    route_to_menu: dict[str, Menu] = {m.route: m for m in menus.values() if m.route}

    for preset_data in ACCESS_PRESETS:
        # Upsert the preset row
        result = await session.execute(
            select(AccessPreset).where(AccessPreset.name == preset_data["name"])
        )
        preset = result.scalar_one_or_none()

        if preset is None:
            preset = AccessPreset(
                name=preset_data["name"],
                description=preset_data["description"],
                is_active=preset_data["is_active"],
            )
            session.add(preset)
            await session.flush()
            print(f"  [+] Access preset created: {preset.name!r} (id={preset.id})")
        else:
            preset.description = preset_data["description"]
            preset.is_active = preset_data["is_active"]
            await session.flush()
            print(f"  [~] Access preset updated: {preset.name!r} (id={preset.id})")

        # Replace all preset-menu rows for this preset
        await session.execute(
            delete(AccessPresetMenu).where(AccessPresetMenu.preset_id == preset.id)
        )
        await session.flush()

        for entry in preset_data["entries"]:
            menu = route_to_menu.get(entry["route"])
            if menu is None:
                print(f"  [!] Route {entry['route']!r} not found, skipping preset entry.")
                continue

            level = levels.get(entry["access_level_key"])
            if level is None:
                print(
                    f"  [!] Access level {entry['access_level_key']!r} not found, "
                    f"skipping preset entry for {entry['route']!r}."
                )
                continue

            session.add(
                AccessPresetMenu(
                    preset_id=preset.id,
                    menu_id=menu.id,
                    access_level_id=level.id,
                )
            )
            print(
                f"  [+] Preset entry: {preset.name!r} → {entry['route']!r} "
                f"({entry['access_level_key']})"
            )

        await session.flush()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    """Run all seed operations within a single DB session."""
    print("=== Greeniac Seed ===")
    async with AsyncSessionLocal() as session:
        async with session.begin():
            print("\n-- Access levels --")
            levels = await seed_access_levels(session)

            print("\n-- Menus --")
            menus = await seed_menus(session)

            print("\n-- Administrator user --")
            admin_user = await seed_admin_user(session)

            print("\n-- Administrator menu permissions --")
            await seed_menu_access(session, admin_user, menus, levels)

            print("\n-- Access presets --")
            await seed_access_presets(session, menus, levels)

    print("\n=== Seed complete ===")


if __name__ == "__main__":
    asyncio.run(main())
