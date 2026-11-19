"""Async database engine and SQLAlchemy 2.0 session factory.

Provides:
- ``engine``: AsyncEngine connected to PostgreSQL via asyncpg.
- ``AsyncSessionLocal``: async session factory.
- ``Base``: declarative base class inherited by all models.
- ``get_db``: FastAPI dependency that injects a session and closes it when done.
"""

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


# Async engine; echo=False in production to avoid log noise
engine = create_async_engine(settings.DATABASE_URL, echo=False, future=True)

# Session factory: autocommit and autoflush disabled by convention
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class inherited by all Greeniac ORM models."""
    pass


async def get_db():
    """FastAPI dependency: opens an async session and closes it after the request."""
    async with AsyncSessionLocal() as session:
        yield session
