"""Central application configuration via environment variables.

Uses pydantic-settings to read a .env file and expose a ``settings`` singleton
that the rest of the code imports directly.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


# Cookie names and CSRF header used throughout the application
ACCESS_COOKIE = "access_token"
XSRF_COOKIE = "XSRF-TOKEN"
XSRF_HEADER = "x-xsrf-token"


class Settings(BaseSettings):
    """Required/optional environment variables for Greeniac."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # PostgreSQL connection string (must use the asyncpg driver)
    DATABASE_URL: str

    # Secret key for signing JWTs
    JWT_SECRET: str

    # JWT signing algorithm
    JWT_ALGORITHM: str = "HS256"

    # Access token lifetime in minutes
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120

    # Enable the Secure flag on cookies (False in HTTP development)
    COOKIE_SECURE: bool = False

    # SameSite policy for cookies
    COOKIE_SAMESITE: str = "lax"

    # Allowed CORS origins, comma-separated
    CORS_ORIGINS: str = "http://localhost:4200"

    # Folder containing the compiled Angular frontend served by the backend
    # (Laravel-style "public" folder). Defaults to <backend-root>/public if empty.
    FRONTEND_DIST: str = ""

    # Directory where user avatar files are stored.
    # Defaults to <backend-root>/uploads/avatars if empty.
    AVATAR_DIR: str = ""

    # Base folder where CCTV recordings are stored (the mounted USB disk).
    CCTV_ROOT: str = "/mnt/cctv/greeniac/cctv"

    # RTSP URL of the Garage camera (used for live snapshots).
    GARAGE_RTSP_URL: str = ""

    # RTSP URL of the Patio Papás camera (local on the LAN via a WiFi repeater).
    # Main realmonitor URL: /live derives the sub-stream from it, snapshot uses it
    # directly. Recording uses the sub path (/h264/ch1/sub) set in cctv.env.
    PATIOPAPAS_RTSP_URL: str = ""

    # ONVIF service port of the Garage camera (XM/Xiongmai default 8899).
    # PTZ control (pan/tilt/zoom, presets, tour) talks ONVIF on this port.
    GARAGE_ONVIF_PORT: int = 8899

    # Live HLS gateway on the PC (RTX 3060): it transcodes the 4K stream to 720p
    # HLS with NVENC and serves it on the LAN. The backend reverse-proxies it so
    # the browser gets a smooth live view without the Pi doing any video work.
    GARAGE_HLS_GATEWAY: str = ""      # e.g. http://192.168.1.109:8090
    GARAGE_HLS_TOKEN: str = ""        # shared secret sent to the gateway

    # Folder where AI detection events (photos + log) are stored.
    CCTV_EVENTS_DIR: str = "/mnt/cctv/greeniac/events"

    # Shared secret the PC detector uses to push events (X-Ingest-Token header).
    CCTV_INGEST_TOKEN: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        """Return the list of CORS origins parsed from the comma-separated string."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


# Singleton — imported directly by the rest of the code
settings = Settings()
