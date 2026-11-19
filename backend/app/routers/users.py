"""User administration router.

Endpoints:
- GET    /api/users              → list all users.
- POST   /api/users              → create a new user (password is hashed).
- PUT    /api/users/{user_id}    → update an existing user's data.
- DELETE /api/users/{user_id}    → delete a user (cannot delete yourself).

Photo endpoints (avatar upload/serve):
- POST   /api/users/{user_id}/photo  → upload/replace user avatar.
- GET    /api/users/{user_id}/photo  → serve user avatar.
- DELETE /api/users/{user_id}/photo  → delete user avatar.

All endpoints require authentication (get_current_user) and access to the
"/app/users" menu item. Mutating endpoints also require the CSRF token.
Photo GET only requires authentication (any logged-in user may view avatars).

Menu assignment lives in the access module (access.py), not here.
"""

import os

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import hash_password
from app.deps import get_current_user, require_menu_access, verify_csrf
from app.models.menu import UserMenuAccess
from app.models.user import User
from app.schemas.user import UserAdminOut, UserCreate, UserUpdate

# ---------------------------------------------------------------------------
# Avatar directory resolution
# ---------------------------------------------------------------------------
# Two levels up from this file lands at the backend root (same style as main.py)
_backend_root = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_avatar_dir: str = settings.AVATAR_DIR or os.path.join(
    _backend_root, "uploads", "avatars"
)
_avatar_dir = os.path.normpath(_avatar_dir)
os.makedirs(_avatar_dir, exist_ok=True)


def _avatar_path(user_id: int) -> str:
    """Return the filesystem path for a user's avatar file (no extension)."""
    return os.path.join(_avatar_dir, str(user_id))


# Magic-byte → MIME type mapping for the most common image formats
_MAGIC: list[tuple[bytes, str]] = [
    (b"\xff\xd8", "image/jpeg"),
    (b"\x89PNG", "image/png"),
    (b"GIF8", "image/gif"),
    # WEBP: b"RIFF" at 0 and b"WEBP" at 8
]


def _detect_media_type(data: bytes) -> str:
    """Detect image MIME type from magic bytes; defaults to image/jpeg."""
    for magic, mime in _MAGIC:
        if data[: len(magic)] == magic:
            return mime
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"

router = APIRouter(prefix="/api", tags=["users"])

# Shared dependency: only users with access to the "/app/users" menu item
_menu_access = Depends(require_menu_access("/app/users"))


# ---------------------------------------------------------------------------
# GET /api/users — full user listing
# ---------------------------------------------------------------------------


@router.get(
    "/users",
    response_model=list[UserAdminOut],
    summary="User listing",
)
async def list_users(
    db: AsyncSession = Depends(get_db),
    _current: User = Depends(get_current_user),
    _access=_menu_access,
):
    """Return all users in the system ordered by id.

    Does not require CSRF because it is a read-only operation.
    """
    result = await db.execute(select(User).order_by(User.id))
    users = result.scalars().all()
    return [UserAdminOut.from_orm_user(u) for u in users]


# ---------------------------------------------------------------------------
# POST /api/users — create user
# ---------------------------------------------------------------------------


@router.post(
    "/users",
    response_model=UserAdminOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create user",
)
async def create_user(
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
    _current: User = Depends(get_current_user),
    _access=_menu_access,
    _csrf: None = Depends(verify_csrf),
):
    """Create a new user in the system.

    Validations:
    - The email must not already be registered (HTTP 409).
    The password is hashed before storage; it is never saved as plain text.
    """
    # Check email uniqueness
    existing_email = await db.execute(
        select(User).where(User.email == body.email)
    )
    if existing_email.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ese correo ya está registrado.",
        )

    new_user = User(
        email=body.email,
        name=body.name,
        password_hash=hash_password(body.password),
        is_active=body.is_active,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return UserAdminOut.from_orm_user(new_user)


# ---------------------------------------------------------------------------
# PUT /api/users/{user_id} — update user
# ---------------------------------------------------------------------------


@router.put(
    "/users/{user_id}",
    response_model=UserAdminOut,
    summary="Update user",
)
async def update_user(
    user_id: int,
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
    _current: User = Depends(get_current_user),
    _access=_menu_access,
    _csrf: None = Depends(verify_csrf),
):
    """Update an existing user's data.

    Validations:
    - The user must exist (HTTP 404).
    - If the email changes, it must not belong to another user (HTTP 409).
    If a non-empty password is provided, it is hashed and updated; otherwise it is left unchanged.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado.",
        )

    # Ensure the new email does not belong to another user
    if body.email != user.email:
        other_email = await db.execute(
            select(User).where(User.email == body.email, User.id != user_id)
        )
        if other_email.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ese correo ya está registrado.",
            )

    user.email = body.email
    user.name = body.name
    user.is_active = body.is_active

    # Only update the password if a non-empty one was provided
    if body.password:
        user.password_hash = hash_password(body.password)

    await db.commit()
    await db.refresh(user)
    return UserAdminOut.from_orm_user(user)


# ---------------------------------------------------------------------------
# DELETE /api/users/{user_id} — delete user
# ---------------------------------------------------------------------------


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete user",
)
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
    _access=_menu_access,
    _csrf: None = Depends(verify_csrf),
):
    """Permanently delete a user from the system.

    Validations:
    - The user must exist (HTTP 404).
    - You cannot delete your own account (HTTP 400).
    All UserMenuAccess rows for the user are removed before deletion.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado.",
        )

    if user_id == current.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No puedes eliminar tu propia cuenta.",
        )

    # Remove all menu grants for this user before deleting
    await db.execute(
        delete(UserMenuAccess).where(UserMenuAccess.user_id == user_id)
    )

    await db.delete(user)
    await db.commit()
    # HTTP 204 → no response body


# ---------------------------------------------------------------------------
# POST /api/users/{user_id}/photo — upload / replace avatar
# ---------------------------------------------------------------------------


@router.post(
    "/users/{user_id}/photo",
    summary="Upload user avatar",
)
async def upload_user_photo(
    user_id: int,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    _current: User = Depends(get_current_user),
    _access=_menu_access,
    _csrf: None = Depends(verify_csrf),
):
    """Upload (or replace) the avatar for a user.

    Accepts any image/* content type. The file is stored as a single raw-bytes
    file at ``<avatar_dir>/<user_id>`` (extension-less, overwritten on re-upload).
    """
    # Validate that the uploaded file is an image
    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo debe ser una imagen.",
        )

    # Confirm the target user exists
    result = await db.execute(select(User).where(User.id == user_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado.",
        )

    data = await file.read()
    dest = _avatar_path(user_id)
    with open(dest, "wb") as fh:
        fh.write(data)

    return {"ok": True}


# ---------------------------------------------------------------------------
# GET /api/users/{user_id}/photo — serve avatar
# ---------------------------------------------------------------------------


@router.get(
    "/users/{user_id}/photo",
    summary="Get user avatar",
)
async def get_user_photo(
    user_id: int,
    _current: User = Depends(get_current_user),
):
    """Return the stored avatar for a user.

    Any authenticated user may retrieve avatars (needed for the top bar and
    autocomplete components).  Returns 404 when no avatar has been uploaded
    so the frontend can fall back to initials.
    """
    dest = _avatar_path(user_id)
    if not os.path.isfile(dest):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El usuario no tiene foto.",
        )

    with open(dest, "rb") as fh:
        header = fh.read(12)
    media_type = _detect_media_type(header)

    return FileResponse(
        dest,
        media_type=media_type,
        headers={"Cache-Control": "no-cache"},
    )


# ---------------------------------------------------------------------------
# DELETE /api/users/{user_id}/photo — delete avatar
# ---------------------------------------------------------------------------


@router.delete(
    "/users/{user_id}/photo",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete user avatar",
)
async def delete_user_photo(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _current: User = Depends(get_current_user),
    _access=_menu_access,
    _csrf: None = Depends(verify_csrf),
):
    """Delete the avatar for a user.

    Silently succeeds if the user has no avatar (idempotent).
    Returns HTTP 204 with no body.
    """
    # Confirm the target user exists
    result = await db.execute(select(User).where(User.id == user_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado.",
        )

    dest = _avatar_path(user_id)
    if os.path.isfile(dest):
        os.remove(dest)
    # HTTP 204 → no response body
