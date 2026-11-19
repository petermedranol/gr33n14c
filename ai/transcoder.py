"""Recording transcode queue — runs on the PC (RTX 3060). Multi-camera.

The Raspberry Pi records each camera in H.265 (reliable, untouched — it keeps
recording even if this PC is off). But the browser can't play H.265, and the Pi
can't transcode in real time. So this worker converts each *closed* recording to a
web-friendly H.264 copy (NVENC) and stores it next to the original on the Pi
(``<cam>/web/<name>``). The dashboard then serves that copy instantly for playback.

Flow every cycle, for every camera:
  1. List the Pi's recordings and which already have a web copy.
  2. Convert the newest missing ones first (skip the one still being recorded).
  3. Delete web copies whose original is gone (keeps storage in sync).

Cameras are listed in TRANSCODE_CAMERAS (space-separated, default "garage
patiopapas"). The scale filter never upscales (patiopapas' 800px sub stays 800px;
garage's 4K caps at WEB_WIDTH).

Decode is on the CPU (32 cores, faster than real time; hevc_cuvid is broken on this
box); only the H.264 encode uses the GPU.
"""

import datetime
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

import singleton

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
load_dotenv(os.path.join(HERE, ".env"))

FFMPEG = os.getenv("FFMPEG", "ffmpeg")
PI = os.getenv("PI_SSH", "gr33n")                       # ssh alias for the Pi
CCTV_ROOT = os.getenv("PI_CCTV_ROOT", "/mnt/cctv/greeniac/cctv")
CAMERAS = [c for c in os.getenv("TRANSCODE_CAMERAS", "garage patiopapas 321").split() if c]
# Cloud cameras recorded locally on THIS PC (the connector writes MP4 here) that we
# push up to the Pi so its normal R2 backup handles them. name -> local folder.
LOCAL_REC = {"321": os.path.join(HERE, "rec", "321")}
# Web copies are just for viewing in the browser (download the original for
# evidence), so a modest width keeps them small. Never upscales (see convert_one).
WEB_WIDTH = os.getenv("WEB_WIDTH", "1280")
WEB_BITRATE = os.getenv("WEB_BITRATE", "1500k")
WORK = os.path.join(HERE, "work")
# How many segments to convert at once (across all cameras). The GPU (NVENC) + 32
# cores handle several in parallel; 3 is safe for a GeForce NVENC.
WORKERS = int(os.getenv("WEB_WORKERS", "3"))
CYCLE_SECONDS = 60         # idle wait when fully caught up
# Only convert recordings within this window — matches the Pi's web-copy retention,
# so we don't endlessly re-convert old segments the Pi just deleted.
WEB_RETENTION_DAYS = int(os.getenv("WEB_RETENTION_DAYS", "7"))

# Segment filenames look like: <cam>_2026-11-19_15-30-00.mp4
_SEG_RE = re.compile(r"^[a-z0-9]+_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.mp4$")
_TS_RE = re.compile(r"^[a-z0-9]+_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})")


def _remote_dir(cam: str) -> str:
    return f"{CCTV_ROOT}/{cam}"


def _remote_web(cam: str) -> str:
    return f"{CCTV_ROOT}/{cam}/web"


def _seg_epoch(name: str) -> float:
    """Recording time (epoch) parsed from the segment filename, 0 if unparseable."""
    m = _TS_RE.match(name)
    if not m:
        return 0.0
    try:
        return datetime.datetime.strptime(m.group(1), "%Y-%m-%d_%H-%M-%S").timestamp()
    except ValueError:
        return 0.0


# Run child processes (ssh/scp/ffmpeg) without flashing a console window — this
# script runs windowless (pythonw), so otherwise each child pops its own cmd box.
_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)

os.makedirs(WORK, exist_ok=True)


def _ssh(cmd: str) -> str:
    """Run a command on the Pi over ssh; return stdout ('' on failure)."""
    try:
        out = subprocess.run(
            ["ssh", PI, cmd], capture_output=True, text=True, timeout=30,
            creationflags=_NOWIN,
        )
        return out.stdout
    except Exception as exc:  # noqa: BLE001
        print(f"[{time.strftime('%H:%M:%S')}] ssh error: {exc!r}", flush=True)
        return ""


def _remote_list(path_glob: str) -> list[str]:
    """Basenames matching a remote glob (empty if none)."""
    out = _ssh(f"ls -1 {path_glob} 2>/dev/null")
    names = [os.path.basename(line.strip()) for line in out.splitlines() if line.strip()]
    return [n for n in names if _SEG_RE.match(n)]


def convert_one(task: tuple[str, str]) -> bool:
    """Pull one original, transcode to H.264, push the web copy back."""
    cam, name = task
    rdir, rweb = _remote_dir(cam), _remote_web(cam)
    local_in = os.path.join(WORK, name)
    local_out = os.path.join(WORK, f"web_{name}")
    # Per-camera target bitrate (small sub-streams don't need garage's 1500k).
    bitrate = os.getenv(f"WEB_BITRATE_{cam.upper()}", WEB_BITRATE)
    _kb = int("".join(ch for ch in bitrate if ch.isdigit()) or "1500")
    maxrate, bufsize = f"{int(_kb * 1.7)}k", f"{_kb * 2}k"
    try:
        # 1) pull the original from the Pi
        r = subprocess.run(["scp", f"{PI}:{rdir}/{name}", local_in], timeout=180,
                           creationflags=_NOWIN)
        if r.returncode != 0 or not os.path.isfile(local_in):
            return False
        # 2) transcode: CPU decode (H.265) + NVENC H.264, faststart for web. The
        #    scale never upscales — small sub-streams keep their size.
        r = subprocess.run([
            FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", local_in,
            "-c:v", "h264_nvenc", "-preset", "p5",
            "-vf", f"scale='min({WEB_WIDTH},iw)':-2",
            "-b:v", bitrate, "-maxrate", maxrate, "-bufsize", bufsize,
            "-c:a", "aac", "-b:a", "48k",  # keep the camera audio in the web copy
            # Keyframe every ~2s so the dashboard's hover-scrub preview lands close.
            "-g", "24", "-movflags", "+faststart", local_out,
        ], timeout=600, creationflags=_NOWIN)
        if r.returncode != 0 or not os.path.isfile(local_out):
            print(f"[{time.strftime('%H:%M:%S')}] ffmpeg falló: {name}", flush=True)
            return False
        # 3) push the web copy back to the Pi (atomic: temp name then move)
        _ssh(f"mkdir -p {rweb}")
        if subprocess.run(["scp", local_out, f"{PI}:{rweb}/.{name}.tmp"], timeout=180,
                          creationflags=_NOWIN).returncode != 0:
            return False
        _ssh(f"mv {rweb}/.{name}.tmp {rweb}/{name}")
        print(f"[{time.strftime('%H:%M:%S')}] convertido: {cam}/{name}", flush=True)
        return True
    finally:
        for f in (local_in, local_out):
            try:
                os.remove(f)
            except OSError:
                pass


def cleanup_orphans(cam: str, originals: set[str], web: list[str]) -> None:
    """Delete a camera's web copies whose original no longer exists on the Pi."""
    rweb = _remote_web(cam)
    orphans = [w for w in web if w not in originals]
    for w in orphans:
        _ssh(f"rm -f {rweb}/{w}")
    if orphans:
        print(f"[{time.strftime('%H:%M:%S')}] {cam}: limpié {len(orphans)} copias web huérfanas", flush=True)


def push_local_recordings() -> None:
    """Push closed MP4 segments recorded locally on the PC (cloud cams like 321) up to
    the Pi, then delete the local copy. The Pi's cctv_backup then uploads them to R2."""
    for cam, local_dir in LOCAL_REC.items():
        if not os.path.isdir(local_dir):
            continue
        files = sorted(f for f in os.listdir(local_dir) if _SEG_RE.match(f))
        for name in files[:-1]:  # skip the newest — still being written
            src = os.path.join(local_dir, name)
            try:
                if time.time() - os.path.getmtime(src) < 30:  # not fully closed yet
                    continue
            except OSError:
                continue
            rdir = _remote_dir(cam)
            _ssh(f"mkdir -p {rdir}")
            tmp = f"{rdir}/.{name}.tmp"
            if subprocess.run(["scp", src, f"{PI}:{tmp}"], timeout=300,
                              creationflags=_NOWIN).returncode == 0:
                _ssh(f"mv {tmp} {rdir}/{name}")
                try:
                    os.remove(src)
                except OSError:
                    pass
                print(f"[{time.strftime('%H:%M:%S')}] push {cam}/{name} → Pi", flush=True)


def main() -> None:
    guard = singleton.single_instance(47814)  # noqa: F841 — keep alive
    singleton.redirect_log(os.path.join(HERE, "transcoder.log"))
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] --- transcoder arrancando ---", flush=True)
    print(f"Pi={PI} cámaras={CAMERAS} -> ≤{WEB_WIDTH}px H.264 @ {WEB_BITRATE}  x{WORKERS} en paralelo", flush=True)

    pool = ThreadPoolExecutor(max_workers=WORKERS)
    while True:
        try:
            # Push PC-recorded cloud-cam segments (321) up to the Pi for R2 backup.
            push_local_recordings()
            tasks: list[tuple[str, str]] = []
            cutoff = time.time() - WEB_RETENTION_DAYS * 86400
            for cam in CAMERAS:
                originals = sorted(_remote_list(f"{_remote_dir(cam)}/{cam}_*.mp4"))
                web = _remote_list(f"{_remote_web(cam)}/{cam}_*.mp4")
                # Skip the newest original — it's probably still being written.
                closed = originals[:-1] if originals else []
                todo = [n for n in closed if n not in web and _seg_epoch(n) >= cutoff]
                cleanup_orphans(cam, set(originals), web)
                tasks.extend((cam, n) for n in todo)
            if not tasks:
                time.sleep(CYCLE_SECONDS)  # caught up — idle
                continue
            # Newest footage becomes playable first, across all cameras.
            tasks.sort(key=lambda t: _seg_epoch(t[1]), reverse=True)
            # Convert a batch concurrently, then loop again immediately (no pause)
            # so the backlog keeps clearing at full throughput.
            list(pool.map(convert_one, tasks[:WORKERS]))
        except Exception as exc:  # noqa: BLE001 — never let the loop die
            print(f"[{time.strftime('%H:%M:%S')}] error de ciclo: {exc!r}", flush=True)
            time.sleep(CYCLE_SECONDS)


if __name__ == "__main__":
    main()
