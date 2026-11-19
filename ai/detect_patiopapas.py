"""Patio Papás person detector — same engine as detect.py, different camera.

Runs a SECOND detector instance so Patio Papás gets its OWN person alerts (Telegram
says "Patio Papás", events are tagged ``patiopapas``) instead of sharing the Garage's.
The tray supervises this as a distinct service (its script name differs from
detect.py). Reads DETECT_RTSP_PATIOPAPAS from .env; uses its own singleton port and
log (detector_patiopapas.log).

The env var must be set BEFORE importing detect, which reads it at import time.
"""

import os

os.environ["DETECT_CAMERA"] = "patiopapas"

import detect  # noqa: E402 — intentional: DETECT_CAMERA must be set first


if __name__ == "__main__":
    detect.main()
