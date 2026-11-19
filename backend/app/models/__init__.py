# Import all models so Alembic autogenerate detects them
from app.models.user import User  # noqa: F401
from app.models.menu import AccessLevelModel, Menu, UserMenuAccess, AccessPreset, AccessPresetMenu  # noqa: F401
from app.models.security import FailedLoginAttempt, BlockedIp  # noqa: F401
