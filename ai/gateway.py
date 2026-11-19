"""Live video gateway — runs on the PC (RTX 3060), serves the dashboard's live view.

The Raspberry Pi can't decode the cameras' H.265 in real time, so the live view
stuttered/went gray. This PC has a 32-core CPU + NVENC, so here we, per camera:

  1. Pull the camera's RTSP, decode it (CPU) and re-encode to a clean H.264 with
     the GPU (NVENC) — cheap and smooth.
  2. Package it as HLS (rolling .m3u8 + 1-second .ts segments) in a local folder.
  3. Serve every camera's folder over one HTTP port on the LAN, gated by a token.

The Pi's FastAPI backend reverse-proxies /<camera>/<file> (adding the token) to the
browser, so the live view is high quality, survives network hiccups (HLS buffers),
and passes cleanly through Cloudflare (segments are small finite files). The Pi only
relays bytes. Recording stays on the Pi (cheap -c copy of each stream).

Cameras:
  - garage:     legacy vars GATEWAY_RTSP / GATEWAY_WIDTH / GATEWAY_BITRATE (4K main).
  - extras:     listed in GATEWAY_CAMERAS (comma-separated); each configured via
                GATEWAY_RTSP_<NAME> and optional GATEWAY_WIDTH_<NAME>/GATEWAY_BITRATE_<NAME>.
                e.g. patiopapas pulls its light 800x448 sub-stream (gentle on the
                WiFi-repeater link) and re-encodes it to H.264.

ffmpeg note: hevc_cuvid (NVDEC) is broken on this box, so decode is on the CPU
(trivial on 32 cores) and only the H.264 encode uses the GPU.
"""

import os
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from dotenv import load_dotenv

import singleton

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
load_dotenv(os.path.join(HERE, ".env"))

FFMPEG = os.getenv("FFMPEG", "ffmpeg")
PORT = int(os.getenv("GATEWAY_PORT", "8090"))
TOKEN = os.getenv("GATEWAY_TOKEN", "")

# Run ffmpeg without a console window (this script runs windowless via pythonw).
_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Only these filenames are ever served (no path traversal).
_NAME_RE = re.compile(r"^(stream\.m3u8|seg_\d{5}\.ts)$")

# Built at startup: camera name -> HLS output dir.
_HLS_DIRS: dict[str, str] = {}


def load_cameras() -> list[dict]:
    """Build the camera list from .env (see module docstring)."""
    def_width = int(os.getenv("GATEWAY_WIDTH", "1280"))
    def_bitrate = os.getenv("GATEWAY_BITRATE", "2500k")
    cams: list[dict] = []

    garage = os.getenv("GATEWAY_RTSP", "")
    if garage:
        cams.append({"name": "garage", "rtsp": garage,
                     "width": def_width, "bitrate": def_bitrate})

    for key in os.getenv("GATEWAY_CAMERAS", "").split(","):
        name = key.strip()
        if not name:
            continue
        rtsp = os.getenv(f"GATEWAY_RTSP_{name.upper()}", "")
        if not rtsp:
            print(f"(cámara {name}: sin GATEWAY_RTSP_{name.upper()}, omitida)", flush=True)
            continue
        cams.append({
            "name": name,
            "rtsp": rtsp,
            "width": int(os.getenv(f"GATEWAY_WIDTH_{name.upper()}", str(def_width))),
            "bitrate": os.getenv(f"GATEWAY_BITRATE_{name.upper()}", def_bitrate),
        })
    return cams


def ffmpeg_cmd(rtsp: str, width: int, bitrate: str, hls_dir: str) -> list[str]:
    """H.265 (CPU decode) → H.264 (NVENC) → rolling HLS."""
    maxrate = bitrate
    bufsize = f"{int(bitrate.rstrip('k')) * 2}k" if bitrate.endswith("k") else bitrate
    return [
        FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "warning",
        "-rtsp_transport", "tcp", "-fflags", "nobuffer", "-i", rtsp,
        "-vf", f"scale={width}:-2",
        "-c:v", "h264_nvenc", "-preset", "p4", "-b:v", bitrate,
        "-maxrate", maxrate, "-bufsize", bufsize, "-g", "12", "-an",
        "-f", "hls", "-hls_time", "1", "-hls_list_size", "8",
        "-hls_flags", "delete_segments+independent_segments+omit_endlist",
        "-hls_segment_type", "mpegts",
        "-hls_segment_filename", os.path.join(hls_dir, "seg_%05d.ts"),
        os.path.join(hls_dir, "stream.m3u8"),
    ]


def run_ffmpeg_forever(cam: dict, hls_dir: str) -> None:
    """Keep a camera's transcode alive; restart it if the camera/network drops it."""
    name = cam["name"]
    while True:
        print(f"[{time.strftime('%H:%M:%S')}] {name}: arrancando ffmpeg (NVENC → HLS)…", flush=True)
        try:
            proc = subprocess.Popen(
                ffmpeg_cmd(cam["rtsp"], cam["width"], cam["bitrate"], hls_dir),
                creationflags=_NOWIN,
            )
            proc.wait()
            print(f"[{time.strftime('%H:%M:%S')}] {name}: ffmpeg terminó (code={proc.returncode}); reintento en 3s", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[{time.strftime('%H:%M:%S')}] {name}: error lanzando ffmpeg: {exc!r}", flush=True)
        time.sleep(3)


class HlsHandler(BaseHTTPRequestHandler):
    """Serve each camera's HLS files to the Pi (token-gated). LAN-only."""

    def log_message(self, *args):  # silence per-request noise
        pass

    def _deny(self, code: int):
        self.send_response(code)
        self.end_headers()

    def do_GET(self):  # noqa: N802
        if TOKEN and self.headers.get("X-Gateway-Token") != TOKEN:
            return self._deny(403)
        # Path like /garage/stream.m3u8 or /patiopapas/seg_00001.ts
        parts = self.path.lstrip("/").split("?", 1)[0].split("/")
        if len(parts) != 2 or parts[0] not in _HLS_DIRS or not _NAME_RE.match(parts[1]):
            return self._deny(404)
        fpath = os.path.join(_HLS_DIRS[parts[0]], parts[1])
        try:
            with open(fpath, "rb") as fh:
                data = fh.read()
        except OSError:
            return self._deny(404)
        ctype = "application/vnd.apple.mpegurl" if parts[1].endswith(".m3u8") else "video/mp2t"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    guard = singleton.single_instance(47813)  # noqa: F841 — keep the lock alive
    singleton.redirect_log(os.path.join(HERE, "gateway.log"))
    cams = load_cameras()
    if not cams:
        print("Ninguna cámara configurada (GATEWAY_RTSP / GATEWAY_CAMERAS) — saliendo.", flush=True)
        return
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] --- gateway arrancando ({len(cams)} cámara(s)) ---", flush=True)
    for cam in cams:
        hls_dir = os.path.join(HERE, "live", cam["name"])
        os.makedirs(hls_dir, exist_ok=True)
        _HLS_DIRS[cam["name"]] = hls_dir
        print(f"  {cam['name']}: {cam['width']}px {cam['bitrate']} → {hls_dir}", flush=True)
        threading.Thread(target=run_ffmpeg_forever, args=(cam, hls_dir), daemon=True).start()

    # Serve-only cameras: their HLS folder is filled by another process (e.g. the
    # xmeye_321 cloud connector writes H.264 HLS directly). We just serve the files.
    for name in os.getenv("GATEWAY_SERVE_CAMERAS", "").split(","):
        name = name.strip()
        if not name:
            continue
        hls_dir = os.path.join(HERE, "live", name)
        os.makedirs(hls_dir, exist_ok=True)
        _HLS_DIRS[name] = hls_dir
        print(f"  {name}: (serve-only, llenado por otro proceso) → {hls_dir}", flush=True)

    server = ThreadingHTTPServer(("0.0.0.0", PORT), HlsHandler)
    print(f"Sirviendo HLS multi-cámara en http://0.0.0.0:{PORT}/<cámara>/stream.m3u8  (puerto {PORT})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
