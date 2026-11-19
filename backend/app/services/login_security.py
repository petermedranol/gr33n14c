"""Login security service: brute-force detection and IP blocking.

Automatic blocking thresholds by IP:
- 10 failures in the last 15 minutes  → block for 15 minutes
- 20 failures in the last 1 hour      → block for 1 hour
- 50 failures in the last 24 hours    → block for 24 hours

Thresholds are evaluated in that order; the first one triggered is applied and the function returns.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.security import BlockedIp, FailedLoginAttempt


async def is_blocked(db: AsyncSession, ip: str) -> bool:
    """Return True if the IP has an active block at the current moment."""
    now = datetime.now(UTC)
    result = await db.execute(
        select(BlockedIp).where(
            BlockedIp.ip == ip,
            BlockedIp.blocked_until > now,
        )
    )
    return result.scalar_one_or_none() is not None


async def record_failed(db: AsyncSession, ip: str, email: str | None = None) -> None:
    """Record a failed attempt and apply a block if any threshold is exceeded.

    Args:
        db: Async database session.
        ip: Client IP address.
        email: Email used in the attempt (may be None).
    """
    now = datetime.now(UTC)

    # Insert the new failed attempt
    db.add(FailedLoginAttempt(ip=ip, email=email, created_at=now))
    await db.flush()  # persist the record without committing yet

    # Evaluate thresholds from most to least severe

    # Threshold 3: 50 failures in 24 hours → block for 24 hours
    window_24h = now - timedelta(hours=24)
    count_24h = await _count_failed_since(db, ip, window_24h)
    if count_24h >= 50:
        await _upsert_block(db, ip, timedelta(hours=24), "50 attempts in 24 hours")
        await db.commit()
        return

    # Threshold 2: 20 failures in 1 hour → block for 1 hour
    window_1h = now - timedelta(hours=1)
    count_1h = await _count_failed_since(db, ip, window_1h)
    if count_1h >= 20:
        await _upsert_block(db, ip, timedelta(hours=1), "20 attempts in 1 hour")
        await db.commit()
        return

    # Threshold 1: 10 failures in 15 minutes → block for 15 minutes
    window_15m = now - timedelta(minutes=15)
    count_15m = await _count_failed_since(db, ip, window_15m)
    if count_15m >= 10:
        await _upsert_block(db, ip, timedelta(minutes=15), "10 attempts in 15 minutes")
        await db.commit()
        return

    # No threshold reached; just save the attempt
    await db.commit()


async def clear_failed(db: AsyncSession, ip: str) -> None:
    """Delete all failed attempts and the active block for an IP.

    Called on successful authentication to reset the counter.
    """
    await db.execute(delete(FailedLoginAttempt).where(FailedLoginAttempt.ip == ip))
    await db.execute(delete(BlockedIp).where(BlockedIp.ip == ip))
    await db.commit()


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

async def _count_failed_since(
    db: AsyncSession, ip: str, since: datetime
) -> int:
    """Count failed attempts from an IP since a given date/time."""
    result = await db.execute(
        select(func.count()).where(
            FailedLoginAttempt.ip == ip,
            FailedLoginAttempt.created_at >= since,
        )
    )
    return result.scalar_one()


async def _upsert_block(
    db: AsyncSession, ip: str, duration: timedelta, reason: str
) -> None:
    """Insert or update the block for an IP with the given duration."""
    now = datetime.now(UTC)
    blocked_until = now + duration

    # Check whether a block already exists for this IP
    existing = await db.execute(select(BlockedIp).where(BlockedIp.ip == ip))
    block = existing.scalar_one_or_none()

    if block is None:
        db.add(BlockedIp(ip=ip, blocked_until=blocked_until, reason=reason))
    else:
        # Only extend if the new block is longer (never shorten an existing block)
        if blocked_until > block.blocked_until:
            block.blocked_until = blocked_until
            block.reason = reason
