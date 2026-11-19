"""Main entry point for the Greeniac application.

Creates the FastAPI instance, configures CORS, includes all routers, and —
if the compiled Angular frontend is present — serves it as static files.

Alembic manages the database schema; this module does NOT create tables on startup.
"""

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.core.config import settings
from app.routers import access, auth, camera, cctv, menu, users

# ---------------------------------------------------------------------------
# Main application instance
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Greeniac",
    version="0.2.0",
    description="Home and greenhouse control — Raspberry Pi 🌱",
)

# ---------------------------------------------------------------------------
# CORS middleware
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,  # required to send/receive cookies
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# API routers
# ---------------------------------------------------------------------------
app.include_router(auth.router)
app.include_router(menu.router)
app.include_router(camera.router)
app.include_router(cctv.router)
app.include_router(cctv.ingest_router)
app.include_router(users.router)
app.include_router(access.router)

# ---------------------------------------------------------------------------
# Serve the compiled Angular frontend (Laravel-style "public" folder)
# ---------------------------------------------------------------------------
# The backend always serves the pre-built app; ``ng serve`` is for local dev only.
# The folder is settings.FRONTEND_DIST or <backend-root>/public.
_backend_root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_frontend_base = settings.FRONTEND_DIST or os.path.join(_backend_root, "public")
_frontend_base = os.path.normpath(_frontend_base)


def _find_frontend_dir(base: str) -> str | None:
    """Locate the folder containing index.html (also accepts Angular's ``browser`` subfolder)."""
    if not os.path.isdir(base):
        return None
    if os.path.isfile(os.path.join(base, "index.html")):
        return base
    # Angular 17+ generates dist/<app>/browser/index.html → descend one level
    for entry in sorted(os.listdir(base)):
        candidate = os.path.join(base, entry)
        if os.path.isdir(candidate) and os.path.isfile(os.path.join(candidate, "index.html")):
            return candidate
    return None


_frontend_dir = _find_frontend_dir(_frontend_base)
if _frontend_dir:
    _index_file = os.path.join(_frontend_dir, "index.html")
    # index.html must always revalidate so browsers pick up the new hashed
    # asset names after each deploy (otherwise a stale index points at a
    # main-*.js that no longer exists → the app fails to boot).
    _index_headers = {"Cache-Control": "no-cache, must-revalidate"}

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        """Serve build files; fall back to index.html only for SPA routes.

        A request that looks like a file (has an extension) but does not exist
        returns 404 — never index.html — so a stale/missing asset fails cleanly
        instead of being served HTML that the browser would try to run as JS.
        """
        if full_path:
            candidate = os.path.normpath(os.path.join(_frontend_dir, full_path))
            # Prevent path traversal outside the frontend folder
            if candidate.startswith(_frontend_dir) and os.path.isfile(candidate):
                return FileResponse(candidate)
            # Missing asset (path with a file extension) → 404, not index.html
            if os.path.splitext(full_path)[1]:
                raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(_index_file, headers=_index_headers)
