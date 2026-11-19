"""Entorno de Alembic con soporte asíncrono (asyncpg + SQLAlchemy 2.0).

Lee la URL de la BD desde ``settings.DATABASE_URL`` y usa ``Base.metadata``
para la generación automática de migraciones (autogenerate).
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool

# ---------------------------------------------------------------------------
# Importar configuración y modelos para que Alembic conozca el esquema
# ---------------------------------------------------------------------------
# IMPORTANTE: hay que importar todos los modelos antes de acceder a Base.metadata
from app.core.config import settings
from app.core.database import Base
import app.models  # noqa: F401 — activa las importaciones en models/__init__.py

# ---------------------------------------------------------------------------
# Configuración de logging de Alembic
# ---------------------------------------------------------------------------
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata con todos los modelos registrados
target_metadata = Base.metadata


def get_url() -> str:
    """Devuelve la URL de la BD desde la configuración de la aplicación."""
    return settings.DATABASE_URL


# ---------------------------------------------------------------------------
# Migraciones offline (sin conexión real a la BD)
# ---------------------------------------------------------------------------

def run_migrations_offline() -> None:
    """Ejecuta las migraciones en modo offline (genera SQL sin conectarse)."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Migraciones online (con conexión real a la BD, modo asíncrono)
# ---------------------------------------------------------------------------

def do_run_migrations(connection):
    """Ejecuta las migraciones sincronamente dentro de una conexión existente."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Crea el motor asíncrono y ejecuta las migraciones en modo online."""
    # Construir la configuración del motor inyectando la URL desde settings
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # sin pool para las migraciones
    )

    async with connectable.connect() as connection:
        # Las migraciones usan la API síncrona de Alembic; run_sync las envuelve
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
