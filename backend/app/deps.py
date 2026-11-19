"""Reusable FastAPI dependencies.

- ``get_current_user``: validates the JWT from the cookie and loads the user from the DB.
- ``verify_csrf``: checks the CSRF double-submit cookie pattern.
- ``require_menu_access``: factory that generates an access-control dependency
  based on the Angular route of the menu item.
"""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import ACCESS_COOKIE, XSRF_COOKIE, XSRF_HEADER
from app.core.database import get_db
from app.core.security import decode_token
from app.models.menu import Menu, UserMenuAccess
from app.models.user import User


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Read the JWT from the ``access_token`` cookie and return the active user.

    Raises:
        HTTPException 401: if the cookie is missing, the token is invalid,
                           the user is not found, or the user is inactive.
    """
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado.",
        )

    payload = decode_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado.",
        )

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token malformado.",
        )

    result = await db.execute(
        select(User).where(User.id == int(user_id_str))
    )
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado o inactivo.",
        )

    return user


def verify_csrf(request: Request) -> None:
    """Dependency that validates the CSRF double-submit token.

    The ``X-XSRF-TOKEN`` header must match the ``XSRF-TOKEN`` cookie.
    Used on all mutating endpoints except /login.

    Raises:
        HTTPException 403: if the header and cookie do not match or are missing.
    """
    cookie_value = request.cookies.get(XSRF_COOKIE)
    header_value = request.headers.get(XSRF_HEADER)

    if not cookie_value or not header_value or cookie_value != header_value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF inválido.",
        )


def require_menu_access(route: str):
    """Dependency factory: checks that the user has access to the given route.

    Args:
        route: Angular route of the menu item (e.g. ``/app/users``).

    Returns:
        FastAPI dependency that raises HTTP 403 if the user has no access.

    If no menu with that route exists in the catalogue, access is allowed
    (ungoverned route). If the menu is free, access is allowed. Otherwise
    the user must have an active (is_active=True) UserMenuAccess grant.
    """

    async def _check(
        request: Request,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> None:
        # Find the menu item with that route
        result = await db.execute(
            select(Menu).where(Menu.route == route)
        )
        menu = result.scalar_one_or_none()

        if menu is None:
            # Route not in the catalogue → allow (ungoverned)
            return

        # Free menus are accessible to everyone
        if menu.is_free:
            return

        # Check for an active explicit grant
        access_result = await db.execute(
            select(UserMenuAccess).where(
                UserMenuAccess.user_id == user.id,
                UserMenuAccess.menu_id == menu.id,
                UserMenuAccess.is_active.is_(True),
            )
        )
        if access_result.scalar_one_or_none() is not None:
            return  # allowed

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes acceso a esta sección.",
        )

    return _check
