"""Security utilities: password hashing, JWT, and CSRF tokens.

All functions are pure (stateless) to ease unit testing.
"""

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash

from app.core.config import settings


# Hashing context: pwdlib.recommended() uses Argon2 as the primary algorithm
# (the most robust today) and also accepts bcrypt hashes for verification/migration.
_password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """Return the Argon2 hash of the plain-text password."""
    return _password_hash.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Compare a plain-text password against its stored hash."""
    return _password_hash.verify(plain, hashed)


def create_access_token(
    subject: str,
    expires_minutes: int | None = None,
) -> str:
    """Generate a signed JWT for the given subject.

    Args:
        subject: User identifier (usually str(user.id)).
        expires_minutes: Custom lifetime; uses the settings value if None.

    Returns:
        JWT as a string.
    """
    expire_delta = timedelta(
        minutes=expires_minutes if expires_minutes is not None
        else settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": now + expire_delta,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    """Decode and validate a JWT.

    Returns:
        The payload as a dict, or None if the token is invalid or expired.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except jwt.PyJWTError:
        return None


def new_csrf_token() -> str:
    """Generate a cryptographically secure random CSRF token."""
    return secrets.token_urlsafe(32)
