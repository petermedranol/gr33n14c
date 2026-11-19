"""CCTV router — lightweight VMS over the recordings on the USB disk.

The Greeniac Raspberry Pi records each IP camera's RTSP stream into dated MP4
segments on the USB disk (systemd service ``cctv-<camera>``). This router lets the
frontend browse and play those recordings and fetch a live JPEG snapshot.

Endpoints (prefix ``/api/cctv``, all require an authenticated user):
- GET /cameras                        → configured cameras
- GET /{camera}/days                  → dates that have recordings
- GET /{camera}/recordings?date=...   → segments for a given day
- GET /{camera}/file/{name}           → download the original H.265 segment (HTTP Range OK)
- GET /{camera}/play/{name}           → H.264 720p transcode of a recording (Chrome playback)
- GET /{camera}/live                  → smooth live H.264 720p video stream
- GET /{camera}/snapshot              → live JPEG grabbed from the camera
"""

import asyncio
import contextlib
import json
import os
import re
import urllib.request
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from PIL import Image
from pydantic import BaseModel, Field

from app import onvif_ptz
from app.core.config import settings
from app.deps import get_current_user

# Footage is sensitive: require a logged-in user for every endpoint.
router = APIRouter(
    prefix="/api/cctv",
    tags=["cctv"],
    dependencies=[Depends(get_current_user)],
)

# Separate router WITHOUT cookie auth: the PC detector pushes events here using a
# shared token (it can't do a browser login).
ingest_router = APIRouter(prefix="/api/cctv", tags=["cctv"])

# Detection-event filenames: garage_2026-11-17_20-05-01.jpg
_EVENT_RE = re.compile(
    r"^(?P<cam>[a-z0-9]+)_(?P<ts>\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})\.jpg$"
)
_EVENTS_LOG = "events.jsonl"

# Camera registry. Extend with more cameras as they are integrated.
CAMERAS: dict[str, dict] = {
    "garage": {"name": "Garage", "rtsp": settings.GARAGE_RTSP_URL},
    "patiopapas": {"name": "Patio Papás", "rtsp": settings.PATIOPAPAS_RTSP_URL},
    # Nevería 321: cloud camera, recorded on the PC and pushed here. No live RTSP
    # (its cloud stream only passes through, can't be decoded for live) — recordings
    # only. The dashboard tab shows them (download + browser playback via web copies).
    "321": {"name": "Nevería", "rtsp": ""},
}

# Segment filenames look like: garage_2026-11-17_15-30-00.mp4
_SEG_RE = re.compile(
    r"^(?P<cam>[a-z0-9]+)_(?P<ts>\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})\.mp4$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Only one live snapshot decode at a time (HEVC decode is CPU-heavy on the Pi).
_snapshot_lock = asyncio.Lock()
_SNAPSHOT_TIMEOUT = 20  # seconds

_TRANSCODE_CHUNK = 64 * 1024

# Protected media must never be cached by a CDN (Cloudflare) — otherwise a cached
# .jpg/.mp4 would be served to anyone, bypassing the session check.
_NO_CACHE = {"Cache-Control": "no-store, private"}


def _camera_or_404(camera: str) -> dict:
    cam = CAMERAS.get(camera)
    if cam is None:
        raise HTTPException(status_code=404, detail="Cámara no encontrada.")
    return cam


def _camera_dir(camera: str) -> str:
    return os.path.join(settings.CCTV_ROOT, camera)


@router.get("/cameras", summary="List configured cameras")
def list_cameras():
    """Return the cameras known to the backend."""
    return [{"id": cid, "name": c["name"]} for cid, c in CAMERAS.items()]


@router.get("/{camera}/days", summary="Dates that have recordings")
def list_days(camera: str):
    """Return the list of dates (YYYY-MM-DD) that have recordings, newest first.

    Segments are stored flat in the camera folder; the date is parsed from each
    filename (garage_YYYY-MM-DD_HH-MM-SS.mp4)."""
    _camera_or_404(camera)
    base = _camera_dir(camera)
    if not os.path.isdir(base):
        return []
    days = set()
    for name in os.listdir(base):
        m = _SEG_RE.match(name)
        if m:
            days.add(m.group("ts").split("_")[0])
    return sorted(days, reverse=True)


def _r2_backed_up_set() -> set[str]:
    """Segment names already uploaded to R2. Read from the index file that the
    backup script (cctv_backup.sh) refreshes each run. Empty if unavailable."""
    idx = os.path.join(settings.CCTV_ROOT, ".r2_index.txt")
    try:
        with open(idx, encoding="utf-8") as fh:
            return {line.strip() for line in fh if line.strip()}
    except OSError:
        return set()


@router.get("/{camera}/recordings", summary="Segments for a given day")
def list_recordings(camera: str, date: str = Query(..., description="YYYY-MM-DD")):
    """Return the recorded segments for ``camera`` on ``date``."""
    _camera_or_404(camera)
    if not _DATE_RE.match(date):
        raise HTTPException(status_code=400, detail="Fecha inválida (use YYYY-MM-DD).")
    base = _camera_dir(camera)
    if not os.path.isdir(base):
        return []
    backed = _r2_backed_up_set()  # which segments are already in R2
    web_dir = os.path.join(base, "web")  # PC-converted H.264 copies
    items = []
    for name in sorted(os.listdir(base)):
        m = _SEG_RE.match(name)
        if not m or not m.group("ts").startswith(date):
            continue
        path = os.path.join(base, name)
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        start = datetime.strptime(m.group("ts"), "%Y-%m-%d_%H-%M-%S").isoformat()
        items.append({
            "name": name, "date": date, "start": start, "size": size,
            "backed_up": name in backed,
            # The PC converts closed segments to a web-friendly H.264 copy; until
            # that's ready the browser can't play the 4K H.265 original.
            "web_ready": os.path.isfile(os.path.join(web_dir, name)),
        })
    return items


def _resolve_segment(camera: str, name: str) -> str:
    """Validate a segment filename and return its absolute path (prevents traversal)."""
    m = _SEG_RE.match(name)
    if not m or m.group("cam") != camera:
        raise HTTPException(status_code=400, detail="Nombre de archivo inválido.")
    base = os.path.normpath(_camera_dir(camera))
    path = os.path.normpath(os.path.join(base, name))
    if not path.startswith(base + os.sep):
        raise HTTPException(status_code=400, detail="Ruta inválida.")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Grabación no encontrada.")
    return path


@router.get("/{camera}/file/{name}", summary="Download the original recording")
def get_recording(camera: str, name: str):
    """Serve the original H.265 MP4 segment. ``FileResponse`` honours the Range
    header, so the browser can seek and downloads can resume. Use this for
    downloading; for in-browser playback use ``/play`` (H.264)."""
    _camera_or_404(camera)
    path = _resolve_segment(camera, name)
    return FileResponse(path, media_type="video/mp4", filename=name, headers=_NO_CACHE)


async def _stream_ffmpeg(args: tuple[str, ...]):
    """Run ffmpeg writing fragmented MP4 to stdout and yield it to the client.

    ffmpeg is killed when the client disconnects (the generator is closed), so we
    never leave an orphan transcode running."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", *args,
        "-movflags", "frag_keyframe+empty_moov", "-f", "mp4", "pipe:1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        while True:
            chunk = await proc.stdout.read(_TRANSCODE_CHUNK)
            if not chunk:
                break
            yield chunk
    finally:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
        await proc.wait()


@router.get("/{camera}/play/{name}", summary="H.264 playback for the browser")
async def play_recording(camera: str, name: str):
    """Serve a recording for in-browser playback.

    Preferred path: the PC converts each closed segment to a web-friendly H.264
    copy (``web/<name>``). If that exists we serve it directly with ``FileResponse``
    (instant start + proper seeking, no Pi CPU). Until it's ready we fall back to an
    on-the-fly transcode on the Pi (slow for 4K H.265, but better than nothing)."""
    _camera_or_404(camera)
    src = _resolve_segment(camera, name)  # validates name, ensures original exists

    web_path = os.path.join(_camera_dir(camera), "web", name)
    if os.path.isfile(web_path):
        return FileResponse(web_path, media_type="video/mp4", headers=_NO_CACHE)

    return StreamingResponse(
        _stream_ffmpeg((
            "-i", src,
            "-map", "0:v:0", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "26", "-pix_fmt", "yuv420p", "-vf", "scale=-2:720", "-an",
        )),
        media_type="video/mp4",
        headers=_NO_CACHE,
    )


def _sub_stream_url(rtsp: str) -> str:
    """Build the low-res sub-stream RTSP URL from the main one.

    The main feed is 4K H.265, which the Pi 4 cannot software-decode in real time
    (gray/garbled live). The camera also serves a light D1/H.265 "extra" stream at
    ``/h264/ch1/sub/av_stream`` (≈800x448) — tiny to decode. We transcode THAT to
    H.264 for the browser, keeping the Pi comfortable."""
    parts = urlsplit(rtsp)
    return urlunsplit((parts.scheme, parts.netloc, "/h264/ch1/sub/av_stream", "", ""))


@router.get("/{camera}/live", summary="Smooth live H.264 video stream")
async def live_stream(camera: str):
    """Transcode the camera's live sub-stream to H.264 and stream it as a
    fragmented MP4, so the browser shows smooth live video instead of a stuttering
    sequence of JPEG snapshots. The transcode stops when the viewer leaves."""
    cam = _camera_or_404(camera)
    rtsp = cam["rtsp"]
    if not rtsp:
        raise HTTPException(status_code=503, detail="Cámara sin URL RTSP configurada.")
    sub = _sub_stream_url(rtsp)
    return StreamingResponse(
        _stream_ffmpeg((
            "-rtsp_transport", "tcp", "-fflags", "nobuffer", "-i", sub,
            "-map", "0:v:0", "-c:v", "libx264", "-preset", "ultrafast",
            "-tune", "zerolatency", "-g", "24", "-pix_fmt", "yuv420p", "-an",
        )),
        media_type="video/mp4",
        headers=_NO_CACHE,
    )


# Only these HLS filenames may be proxied (playlist + numbered segments).
_HLS_FILE_RE = re.compile(r"^(stream\.m3u8|seg_\d{5}\.ts)$")


@router.get("/{camera}/hls/{filename}", summary="Live HLS (proxied from the PC gateway)")
async def hls_proxy(camera: str, filename: str):
    """Relay the PC gateway's HLS playlist/segments to the browser.

    The PC (GPU) produces a smooth 720p H.264 HLS stream on the LAN; the browser
    never talks to it directly — it asks the backend (with the user's session) and
    we fetch from the gateway adding the shared token. HLS segments are small finite
    files, so this passes cleanly through Cloudflare (unlike an endless stream)."""
    _camera_or_404(camera)
    if not settings.GARAGE_HLS_GATEWAY:
        raise HTTPException(status_code=503, detail="Gateway de video en vivo no configurado.")
    if not _HLS_FILE_RE.match(filename):
        raise HTTPException(status_code=400, detail="Archivo HLS inválido.")

    url = f"{settings.GARAGE_HLS_GATEWAY.rstrip('/')}/{camera}/{filename}"

    def _fetch() -> bytes:
        req = urllib.request.Request(url, headers={"X-Gateway-Token": settings.GARAGE_HLS_TOKEN})
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.read()

    try:
        data = await asyncio.to_thread(_fetch)
    except Exception:  # noqa: BLE001 — gateway down / unreachable
        raise HTTPException(status_code=502, detail="El gateway de video no respondió.")

    ctype = "application/vnd.apple.mpegurl" if filename.endswith(".m3u8") else "video/mp2t"
    # The playlist changes every second; if Cloudflare caches it, hls.js keeps
    # getting a stale segment list and the live view freezes. CDN-Cache-Control
    # tells Cloudflare's edge not to cache it (independent of browser caching).
    return Response(
        content=data,
        media_type=ctype,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "CDN-Cache-Control": "no-store",
            "Cloudflare-CDN-Cache-Control": "no-store",
        },
    )


@router.get("/{camera}/snapshot", summary="Live JPEG snapshot from the camera")
async def snapshot(camera: str):
    """Grab a single live frame from the camera and return it as JPEG.

    Uses the sub-stream (subtype=1) for a faster decode. The camera sends H.265,
    which ffmpeg decodes in software — fine for one frame, hence the lock/timeout.
    """
    cam = _camera_or_404(camera)
    rtsp = cam["rtsp"]
    if not rtsp:
        raise HTTPException(status_code=503, detail="Cámara sin URL RTSP configurada.")
    sub = rtsp.replace("subtype=0", "subtype=1")
    async with _snapshot_lock:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-rtsp_transport", "tcp", "-i", sub,
            "-frames:v", "1", "-vf", "scale=1280:-2", "-q:v", "4",
            "-f", "mjpeg", "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=_SNAPSHOT_TIMEOUT
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise HTTPException(status_code=504, detail="La cámara no respondió a tiempo.")
        if proc.returncode != 0 or not stdout:
            raise HTTPException(
                status_code=503,
                detail=f"No se pudo capturar imagen: {stderr.decode()[-300:]}",
            )
    return Response(
        content=stdout,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


# ---------------------------------------------------------------------------
# PTZ control (pan/tilt/zoom, presets, patrol) — Garage camera via ONVIF.
# The browser never talks to the camera directly: it calls these session-
# protected endpoints and the Pi relays the command over the LAN.
# ---------------------------------------------------------------------------

# Only the Garage camera is PTZ-capable / ONVIF-wired for now.
_PTZ_CAMERAS = {"garage"}


def _ptz_camera_or_404(camera: str) -> None:
    _camera_or_404(camera)
    if camera not in _PTZ_CAMERAS:
        raise HTTPException(status_code=400, detail="Esta cámara no soporta PTZ.")


class PtzMove(BaseModel):
    pan: float = Field(0.0, ge=-1.0, le=1.0)   # + derecha / - izquierda
    tilt: float = Field(0.0, ge=-1.0, le=1.0)  # + arriba / - abajo
    zoom: float = Field(0.0, ge=-1.0, le=1.0)  # + acercar / - alejar
    duration: float = Field(0.4, ge=0.1, le=1.5)  # step pulse length (seconds)


class PtzPreset(BaseModel):
    name: str = Field(..., min_length=1, max_length=32)


class PtzTour(BaseModel):
    action: str = Field(..., pattern="^(start|stop)$")
    dwell: int = Field(10, ge=3, le=120)  # seconds per preset


def _ptz_guard(fn):
    """Translate PTZError into a clean 502 for the client."""
    try:
        return fn()
    except onvif_ptz.PTZError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/{camera}/ptz/move", summary="Start a continuous PTZ move")
async def ptz_move(camera: str, body: PtzMove):
    """Begin moving (hold). The frontend calls this on mouse-down / touch-start
    and ``/ptz/stop`` on release."""
    _ptz_camera_or_404(camera)
    await asyncio.to_thread(
        lambda: _ptz_guard(lambda: onvif_ptz.move(body.pan, body.tilt, body.zoom))
    )
    return {"ok": True}


@router.post("/{camera}/ptz/stop", summary="Stop all PTZ motion")
async def ptz_stop(camera: str):
    _ptz_camera_or_404(camera)
    await asyncio.to_thread(lambda: _ptz_guard(onvif_ptz.stop))
    return {"ok": True}


@router.post("/{camera}/ptz/step", summary="Nudge the camera a small fixed step")
async def ptz_step(camera: str, body: PtzMove):
    """One tap = one small move then auto-stop. Controllable despite live latency."""
    _ptz_camera_or_404(camera)
    try:
        await onvif_ptz.step(body.pan, body.tilt, body.zoom, body.duration)
    except onvif_ptz.PTZError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"ok": True}


@router.get("/{camera}/ptz/presets", summary="List saved PTZ presets")
async def ptz_presets(camera: str):
    _ptz_camera_or_404(camera)
    presets = await asyncio.to_thread(lambda: _ptz_guard(onvif_ptz.list_presets))
    return {"presets": presets, "tour_active": onvif_ptz.tour_active()}


@router.post("/{camera}/ptz/goto/{token}", summary="Go to a saved preset")
async def ptz_goto(camera: str, token: str):
    _ptz_camera_or_404(camera)
    await asyncio.to_thread(lambda: _ptz_guard(lambda: onvif_ptz.goto_preset(token)))
    return {"ok": True}


@router.post("/{camera}/ptz/preset", summary="Save current position as a preset")
async def ptz_save_preset(camera: str, body: PtzPreset):
    _ptz_camera_or_404(camera)
    token = await asyncio.to_thread(
        lambda: _ptz_guard(lambda: onvif_ptz.save_preset(body.name))
    )
    return {"ok": True, "token": token}


@router.delete("/{camera}/ptz/preset/{token}", summary="Delete a saved preset")
async def ptz_delete_preset(camera: str, token: str):
    _ptz_camera_or_404(camera)
    await asyncio.to_thread(lambda: _ptz_guard(lambda: onvif_ptz.remove_preset(token)))
    return {"ok": True}


@router.post("/{camera}/ptz/tour", summary="Start/stop the preset patrol")
async def ptz_tour(camera: str, body: PtzTour):
    """Backend-driven patrol: cycle the saved presets, dwelling ``dwell`` seconds
    on each. Needs at least two presets to do anything visible."""
    _ptz_camera_or_404(camera)
    if body.action == "start":
        await onvif_ptz.start_tour(body.dwell)
    else:
        await onvif_ptz.stop_tour()
    return {"ok": True, "tour_active": onvif_ptz.tour_active()}


# ---------------------------------------------------------------------------
# Detection events (pushed by the PC detector, shown in the dashboard gallery)
# ---------------------------------------------------------------------------

def _events_dir() -> str:
    os.makedirs(settings.CCTV_EVENTS_DIR, exist_ok=True)
    return settings.CCTV_EVENTS_DIR


@ingest_router.post("/events/ingest", summary="Receive a detection event from the detector")
async def ingest_event(
    image: UploadFile = File(...),
    camera: str = Form("garage"),
    ts: str = Form(...),
    count: int = Form(1),
    x_ingest_token: str = Header(default=""),
):
    """Store a detection photo + log line. Authenticated with a shared token
    (the PC detector can't do a browser login)."""
    if not settings.CCTV_INGEST_TOKEN or x_ingest_token != settings.CCTV_INGEST_TOKEN:
        raise HTTPException(status_code=401, detail="Token de ingesta inválido.")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}", ts):
        raise HTTPException(status_code=400, detail="ts inválido.")
    cam = re.sub(r"[^a-z0-9]", "", camera.lower()) or "garage"
    name = f"{cam}_{ts}.jpg"
    path = os.path.join(_events_dir(), name)
    with open(path, "wb") as fh:
        fh.write(await image.read())
    entry = {"camera": cam, "ts": ts, "count": count, "file": name}
    with open(os.path.join(_events_dir(), _EVENTS_LOG), "a", encoding="utf-8") as log:
        log.write(json.dumps(entry) + "\n")
    return {"ok": True, "file": name}


@router.get("/events", summary="Recent detection events (newest first)")
def list_events(limit: int = Query(100, ge=1, le=500)):
    """Return the most recent detection events for the dashboard gallery."""
    log_path = os.path.join(_events_dir(), _EVENTS_LOG)
    if not os.path.isfile(log_path):
        return []
    with open(log_path, encoding="utf-8") as fh:
        lines = fh.readlines()
    events = []
    for line in lines[-limit:]:
        try:
            e = json.loads(line)
            e["start"] = datetime.strptime(e["ts"], "%Y-%m-%d_%H-%M-%S").isoformat()
            events.append(e)
        except Exception:
            continue
    events.reverse()  # newest first
    # Flag whether the recording segment holding each event already has a web copy
    # (so the gallery can enable/disable its "Ver en video" button).
    seg_cache: dict[str, list[tuple[float, str]]] = {}
    for e in events:
        cam = e.get("camera", "garage")
        if cam not in seg_cache:
            seg_cache[cam] = _segment_index(cam)
        e["web_ready"] = _web_ready_for_event(cam, seg_cache[cam], e.get("ts", ""))
    return events


def _segment_index(camera: str) -> list[tuple[float, str]]:
    """Sorted (start_epoch, filename) for a camera's recorded segments."""
    base = _camera_dir(camera)
    out: list[tuple[float, str]] = []
    if os.path.isdir(base):
        for n in os.listdir(base):
            m = _SEG_RE.match(n)
            if m and m.group("cam") == camera:
                st = datetime.strptime(m.group("ts"), "%Y-%m-%d_%H-%M-%S").timestamp()
                out.append((st, n))
        out.sort()
    return out


def _web_ready_for_event(camera: str, segments: list[tuple[float, str]], ev_ts: str) -> bool:
    """True if the 10-min segment containing the event already has a web H.264 copy."""
    try:
        et = datetime.strptime(ev_ts, "%Y-%m-%d_%H-%M-%S").timestamp()
    except ValueError:
        return False
    name = None
    for st, n in segments:
        if st <= et < st + 600:
            name = n
            break
        if st > et:
            break
    return bool(name) and os.path.isfile(os.path.join(_camera_dir(camera), "web", name))


def _event_thumbnail(src: str, name: str) -> str:
    """Return a cached ~400px JPEG thumbnail for an event image (build once).

    The full annotated frames are ~340 KB; the gallery only needs a small preview,
    so we serve a tiny thumbnail there and the full image on click. Generated lazily
    and cached on disk, so it covers old and new events without reprocessing."""
    tdir = os.path.join(_events_dir(), "thumbs")
    os.makedirs(tdir, exist_ok=True)
    tpath = os.path.join(tdir, name)
    try:
        if os.path.isfile(tpath) and os.path.getmtime(tpath) >= os.path.getmtime(src):
            return tpath
        with Image.open(src) as im:
            im.thumbnail((400, 400))
            im.convert("RGB").save(tpath, "JPEG", quality=70)
        return tpath
    except Exception:  # noqa: BLE001 — any failure → just serve the full image
        return src


@router.get("/events/img/{name}", summary="A detection event image")
def get_event_image(name: str, thumb: bool = Query(False, description="Serve a small thumbnail")):
    if not _EVENT_RE.match(name):
        raise HTTPException(status_code=400, detail="Nombre inválido.")
    base = os.path.normpath(_events_dir())
    path = os.path.normpath(os.path.join(base, name))
    if not path.startswith(base + os.sep) or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Evento no encontrado.")
    if thumb:
        path = _event_thumbnail(path, name)
    return FileResponse(path, media_type="image/jpeg", headers=_NO_CACHE)


# ---------------------------------------------------------------------------
# Bark detection events (audio) — pushed by the PC bark detector (bark.py).
# For calibration: the dashboard shows each bark's score + audio clip + snapshot
# so you can listen, validate, and tune the alert threshold.
# ---------------------------------------------------------------------------

_BARK_LOG = "bark.jsonl"
_BARK_CFG = "bark_config.json"
_BARK_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$")
_BARK_FILE_RE = re.compile(r"^bark_(?:[a-z0-9]+_)?\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.(wav|jpg)$")


def _bark_dir() -> str:
    d = os.path.join(settings.CCTV_EVENTS_DIR, "bark")
    os.makedirs(d, exist_ok=True)
    return d


class BarkThreshold(BaseModel):
    threshold: float = Field(..., ge=0.05, le=0.95)


@ingest_router.post("/bark/ingest", summary="Receive a bark event from the detector")
async def ingest_bark(
    ts: str = Form(...),
    score: float = Form(...),
    person: int = Form(0),
    camera: str = Form("garage"),
    audio: UploadFile = File(...),
    image: UploadFile | None = File(None),
    x_ingest_token: str = Header(default=""),
):
    if not settings.CCTV_INGEST_TOKEN or x_ingest_token != settings.CCTV_INGEST_TOKEN:
        raise HTTPException(status_code=401, detail="Token de ingesta inválido.")
    if not _BARK_TS_RE.match(ts):
        raise HTTPException(status_code=400, detail="ts inválido.")
    cam = re.sub(r"[^a-z0-9]", "", camera.lower()) or "garage"
    d = _bark_dir()
    wav_name = f"bark_{cam}_{ts}.wav"
    with open(os.path.join(d, wav_name), "wb") as fh:
        fh.write(await audio.read())
    img_name = ""
    if image is not None:
        img_name = f"bark_{cam}_{ts}.jpg"
        with open(os.path.join(d, img_name), "wb") as fh:
            fh.write(await image.read())
    entry = {"ts": ts, "camera": cam, "score": round(float(score), 3), "person": int(person),
             "file": wav_name, "img": img_name}
    with open(os.path.join(d, _BARK_LOG), "a", encoding="utf-8") as log:
        log.write(json.dumps(entry) + "\n")
    return {"ok": True}


@router.get("/bark/events", summary="Recent bark events (newest first)")
def list_bark_events(limit: int = Query(200, ge=1, le=1000)):
    log_path = os.path.join(_bark_dir(), _BARK_LOG)
    if not os.path.isfile(log_path):
        return []
    with open(log_path, encoding="utf-8") as fh:
        lines = fh.readlines()
    out = []
    for line in lines[-limit:]:
        try:
            e = json.loads(line)
            e.setdefault("camera", "garage")  # older entries predate multi-camera
            e["start"] = datetime.strptime(e["ts"], "%Y-%m-%d_%H-%M-%S").isoformat()
            out.append(e)
        except Exception:
            continue
    out.reverse()
    return out


@router.get("/bark/clip/{name}", summary="A bark audio clip (WAV)")
def get_bark_clip(name: str):
    if not _BARK_FILE_RE.match(name) or not name.endswith(".wav"):
        raise HTTPException(status_code=400, detail="Nombre inválido.")
    base = os.path.normpath(_bark_dir())
    path = os.path.normpath(os.path.join(base, name))
    if not path.startswith(base + os.sep) or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Clip no encontrado.")
    return FileResponse(path, media_type="audio/wav", headers=_NO_CACHE)


@router.get("/bark/img/{name}", summary="A bark event snapshot")
def get_bark_img(name: str):
    if not _BARK_FILE_RE.match(name) or not name.endswith(".jpg"):
        raise HTTPException(status_code=400, detail="Nombre inválido.")
    base = os.path.normpath(_bark_dir())
    path = os.path.normpath(os.path.join(base, name))
    if not path.startswith(base + os.sep) or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Imagen no encontrada.")
    return FileResponse(path, media_type="image/jpeg", headers=_NO_CACHE)


@router.get("/bark/threshold", summary="Get the bark alert threshold")
def get_bark_threshold():
    path = os.path.join(_bark_dir(), _BARK_CFG)
    try:
        with open(path, encoding="utf-8") as fh:
            return {"threshold": float(json.load(fh).get("threshold", 0.3))}
    except (OSError, ValueError):
        return {"threshold": 0.3}


@router.post("/bark/threshold", summary="Set the bark alert threshold")
def set_bark_threshold(body: BarkThreshold):
    path = os.path.join(_bark_dir(), _BARK_CFG)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"threshold": round(body.threshold, 3)}, fh)
    return {"ok": True, "threshold": round(body.threshold, 3)}
