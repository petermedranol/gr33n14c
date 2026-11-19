"""Authentication router.

Endpoints:
- POST /api/login   → authenticates the user and sets JWT + CSRF cookies.
- POST /api/logout  → clears the session cookies.
- GET  /api/user    → returns the current user and refreshes the CSRF cookie.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import (
    ACCESS_COOKIE,
    XSRF_COOKIE,
    settings,
)
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    new_csrf_token,
    verify_password,
)
from app.deps import get_current_user, verify_csrf
from app.models.user import User
from app.schemas.auth import LoginRequest, LoginResponse, Preferences
from app.schemas.user import UserOut
from app.services.login_security import clear_failed, is_blocked, record_failed
from app.services.menu_service import build_menu_tree

router = APIRouter(prefix="/api", tags=["authentication"])

# Extended token lifetime when the user checks "remember me" (7 days)
REMEMBER_ME_MINUTES = 7 * 24 * 60


def _get_client_ip(request: Request) -> str:
    """Return the real client IP, honoring the X-Forwarded-For header when present.

    In deployments behind a proxy (nginx) the real IP comes in that header.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # The header may contain a list "ip1, ip2, ..."; take the first one
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"


def _is_secure(request: Request) -> bool:
    """Return True when cookies should carry the Secure flag.

    Logic:
    - Always True when ``settings.COOKIE_SECURE`` is True (explicit override).
    - Also True when Cloudflare Tunnel (or any reverse proxy) forwards
      ``X-Forwarded-Proto: https``, meaning the client is on HTTPS even though
      the backend is reached over HTTP internally.
    - Falls back to False for plain HTTP local development (``ng serve``).
    """
    return settings.COOKIE_SECURE or request.headers.get("x-forwarded-proto", "").lower() == "https"


def _set_session_cookies(
    response: JSONResponse,
    access_token: str,
    csrf_token: str,
    max_age: int,
    secure: bool,
) -> None:
    """Set the two session cookies on the response.

    - ``access_token``: httpOnly=True (inaccessible from JS, protects the JWT).
    - ``XSRF-TOKEN``:   httpOnly=False (the frontend reads it for the double-submit).

    The ``secure`` parameter is computed per-request via :func:`_is_secure` so
    that cookies are Secure when served over HTTPS (e.g. through Cloudflare
    Tunnel) and non-Secure for plain HTTP local development.
    """
    # JWT cookie: never accessible from JavaScript
    response.set_cookie(
        key=ACCESS_COOKIE,
        value=access_token,
        httponly=True,
        secure=secure,
        samesite=settings.COOKIE_SAMESITE,
        max_age=max_age,
    )
    # CSRF cookie: visible to JS so it can be sent as a header
    response.set_cookie(
        key=XSRF_COOKIE,
        value=csrf_token,
        httponly=False,
        secure=secure,
        samesite=settings.COOKIE_SAMESITE,
        max_age=max_age,
    )


@router.post("/login", response_model=LoginResponse, summary="Log in")
async def login(
    request: Request,
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate the user and set JWT + CSRF cookies.

    Brute-force protection: if the IP exceeds the thresholds configured in
    ``login_security``, the request is rejected with HTTP 429 before querying the DB.
    """
    ip = _get_client_ip(request)

    # Block IP if it has been rate-limited
    if await is_blocked(db, ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos, IP bloqueada temporalmente.",
        )

    # Look up the user by email
    result = await db.execute(
        select(User).where(User.email == body.email)
    )
    user = result.scalar_one_or_none()

    # Validate existence and password
    if user is None or not verify_password(body.password, user.password_hash):
        await record_failed(db, ip, body.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario inactivo.",
        )

    # Successful login: clear the failed-attempt history
    await clear_failed(db, ip)

    # Calculate token lifetime
    expires_minutes = (
        REMEMBER_ME_MINUTES if body.remember else settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    access_token = create_access_token(str(user.id), expires_minutes=expires_minutes)
    csrf_token = new_csrf_token()
    max_age = expires_minutes * 60  # seconds for set_cookie

    # Build the user's menu tree
    menu_items = await build_menu_tree(db, user)

    login_response = LoginResponse(
        message="Bienvenido",
        user=UserOut.from_orm_user(user),
        preferences=Preferences(menuItems=menu_items),
    )

    response = JSONResponse(content=login_response.model_dump())
    _set_session_cookies(response, access_token, csrf_token, max_age, secure=_is_secure(request))
    return response


@router.post("/logout", summary="Log out")
async def logout(
    request: Request,
    _user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    """Delete the session and CSRF cookies."""
    secure = _is_secure(request)
    response = JSONResponse(content={"message": "Sesión cerrada"})
    # Delete cookies by overwriting them with max_age=0; Secure must match the original
    response.delete_cookie(key=ACCESS_COOKIE, secure=secure, samesite=settings.COOKIE_SAMESITE)
    response.delete_cookie(key=XSRF_COOKIE, secure=secure, samesite=settings.COOKIE_SAMESITE)
    return response


@router.get("/user", summary="Current user")
async def get_user(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated user and their menu tree.

    Also refreshes the ``XSRF-TOKEN`` cookie so the SPA can obtain a valid
    CSRF token when the application loads.
    """
    menu_items = await build_menu_tree(db, user)
    csrf_token = new_csrf_token()

    response_data = {
        "user": UserOut.from_orm_user(user).model_dump(),
        "preferences": {"menuItems": [item.model_dump() for item in menu_items]},
    }
    response = JSONResponse(content=response_data)

    # Refresh the CSRF cookie (same config as login, but no explicit max_age)
    response.set_cookie(
        key=XSRF_COOKIE,
        value=csrf_token,
        httponly=False,
        secure=_is_secure(request),
        samesite=settings.COOKIE_SAMESITE,
    )
    return response
