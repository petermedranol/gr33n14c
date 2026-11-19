"""Camera router and basic utility endpoints.

Endpoints:
- GET /api/camera/photo  → captures and returns a freshly taken JPEG photo.
- GET /api/health        → service liveness check.
- GET /api/hello         → greeting endpoint (quick tests).
"""

import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

router = APIRouter(prefix="/api", tags=["camera"])

# Temporary path where rpicam-jpeg saves the snapshot
SNAP_PATH = "/tmp/greeniac_snap.jpg"

# Global lock: the camera is a unique resource; only one capture at a time
_camera_lock = asyncio.Lock()


async def capture_photo(width: int = 1280, height: int = 720) -> bytes:
    """Capture a photo with rpicam-jpeg and return the JPEG bytes.

    Args:
        width: Image width in pixels.
        height: Image height in pixels.

    Returns:
        Binary content of the captured JPEG.

    Raises:
        HTTPException 503: if rpicam-jpeg returns a non-zero exit code.
    """
    async with _camera_lock:  # ensures only one capture at a time
        proc = await asyncio.create_subprocess_exec(
            "rpicam-jpeg", "-n", "-t", "800",
            "--width", str(width), "--height", str(height),
            "-o", SNAP_PATH,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise HTTPException(
                status_code=503,
                detail=f"Cámara no disponible: {stderr.decode()[-300:]}",
            )
        with open(SNAP_PATH, "rb") as f:
            return f.read()


@router.get("/camera/photo", summary="Live photo from the camera")
async def camera_photo():
    """Return a freshly taken JPEG photo from the greenhouse camera.

    The ``Cache-Control: no-store`` header prevents the browser from caching
    old images.
    """
    jpeg = await capture_photo()
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/health", summary="Service health check")
def health():
    """Liveness check for the Greeniac service."""
    return {"status": "ok", "service": "greeniac"}


@router.get("/hello", summary="Greeting test endpoint")
def hello(name: str = "world"):
    """Test endpoint. Example: ``GET /api/hello?name=Pedro``."""
    return {"message": f"Hello {name} from Greeniac on the Raspberry Pi!"}
