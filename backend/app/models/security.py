"""ORM models for access control and IP blocking.

- ``FailedLoginAttempt``: records each failed login attempt.
- ``BlockedIp``: IPs temporarily blocked for exceeding attempt thresholds.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FailedLoginAttempt(Base):
    """Records a failed login attempt to detect brute-force attacks."""

    __tablename__ = "failed_login_attempts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # IP address of the client that attempted to authenticate
    ip: Mapped[str] = mapped_column(String(45), nullable=False, index=True)
    # Email that was tried (may be None if the field was empty)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Exact timestamp of the failed attempt
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class BlockedIp(Base):
    """IP temporarily blocked for exceeding the failed-attempt threshold."""

    __tablename__ = "blocked_ips"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # Blocked IP (unique because only one active block per IP should exist)
    ip: Mapped[str] = mapped_column(String(45), unique=True, index=True, nullable=False)
    # Timestamp until which the IP remains blocked
    blocked_until: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # Reason for the block to aid auditing
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
