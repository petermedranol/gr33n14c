"""Patio Papás bark detector — same engine as bark.py, different camera.

Runs a SECOND PANNs bark detector for Patio Papás so its dog barks are logged and
fused with ITS person detector (bark + person on that camera = alert). The tray
supervises this as a distinct service. Reads BARK_RTSP_PATIOPAPAS from .env (the
camera's main stream — bark pulls only the audio track, see bark.open_audio), uses
its own singleton port and log (bark_patiopapas.log).

The env var must be set BEFORE importing bark, which reads it at import time.
"""

import os

os.environ["BARK_CAMERA"] = "patiopapas"

import bark  # noqa: E402 — intentional: BARK_CAMERA must be set first


if __name__ == "__main__":
    bark.main()
