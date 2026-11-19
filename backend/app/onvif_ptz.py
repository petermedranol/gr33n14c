"""ONVIF PTZ control for the Garage camera (XM/Xiongmai, port 8899).

Pure-stdlib SOAP (``urllib``) with WS-Security UsernameToken digest — no extra
dependencies. Camera credentials are parsed from ``settings.GARAGE_RTSP_URL`` so
they live in a single place.

Exposed to the router:
- ``move(pan, tilt, zoom)`` / ``stop()``  — continuous joystick movement
- ``list_presets()`` / ``goto_preset(token)`` / ``save_preset(name)`` / ``remove_preset(token)``
- ``start_tour(dwell)`` / ``stop_tour()`` / ``tour_active()`` — backend-driven patrol
  that cycles the saved presets (more reliable than the camera's native tour).

All movement is clamped to the camera's velocity range (-1..1). The on-the-fly
tour is an asyncio task owned by this module; it stops cleanly on request and
when the process exits.
"""

import asyncio
import base64
import datetime
import hashlib
import os
import re
import urllib.error
import urllib.request
from urllib.parse import urlparse

from app.core.config import settings

_PTZ_NS = "http://www.onvif.org/ver20/ptz/wsdl"
_SCHEMA_NS = "http://www.onvif.org/ver10/schema"
_PROFILE = "000"  # media profile token for the main stream on this camera
_TIMEOUT = 8


class PTZError(RuntimeError):
    """Raised when the camera rejects a PTZ command or is unreachable."""


# ─── Low-level ONVIF plumbing ────────────────────────────────────────────────

def _creds() -> tuple[str, str, str]:
    """Return (host, user, password) parsed from the camera RTSP URL."""
    parsed = urlparse(settings.GARAGE_RTSP_URL)
    if not parsed.hostname:
        raise PTZError("Cámara sin URL RTSP configurada.")
    return parsed.hostname, (parsed.username or ""), (parsed.password or "")


def _security_header(user: str, pwd: str) -> str:
    """Build a WS-Security UsernameToken with a password digest (per ONVIF)."""
    nonce = os.urandom(16)
    created = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    digest = base64.b64encode(
        hashlib.sha1(nonce + created.encode() + pwd.encode()).digest()
    ).decode()
    nonce_b64 = base64.b64encode(nonce).decode()
    return (
        '<s:Header><Security s:mustUnderstand="1" '
        'xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">'
        f"<UsernameToken><Username>{user}</Username>"
        '<Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">'
        f"{digest}</Password>"
        '<Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">'
        f"{nonce_b64}</Nonce>"
        '<Created xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">'
        f"{created}</Created></UsernameToken></Security></s:Header>"
    )


def _call(body: str) -> str:
    """POST a PTZ SOAP body and return the response text (raises on failure)."""
    host, user, pwd = _creds()
    endpoint = f"http://{host}:{settings.GARAGE_ONVIF_PORT}/onvif/ptz_service"
    envelope = (
        '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
        + _security_header(user, pwd)
        + f'<s:Body xmlns="{_PTZ_NS}">{body}</s:Body></s:Envelope>'
    )
    req = urllib.request.Request(
        endpoint, data=envelope.encode(), headers={"Content-Type": "application/soap+xml"}
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise PTZError(f"La cámara rechazó el comando (HTTP {exc.code}).") from exc
    except OSError as exc:
        raise PTZError("No se pudo contactar la cámara.") from exc


def _clamp(value: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(-1.0, min(1.0, v))


# ─── Movement ────────────────────────────────────────────────────────────────

def move(pan: float, tilt: float, zoom: float = 0.0) -> None:
    """Start a continuous move. Values are velocities in -1..1 (0 = that axis
    idle). Call ``stop()`` to halt — e.g. on mouse-up / touch-end."""
    pan, tilt, zoom = _clamp(pan), _clamp(tilt), _clamp(zoom)
    _call(
        f"<ContinuousMove><ProfileToken>{_PROFILE}</ProfileToken><Velocity>"
        f'<PanTilt x="{pan}" y="{tilt}" xmlns="{_SCHEMA_NS}"/>'
        f'<Zoom x="{zoom}" xmlns="{_SCHEMA_NS}"/>'
        "</Velocity></ContinuousMove>"
    )


def stop() -> None:
    """Stop all PTZ motion (pan/tilt and zoom)."""
    _call(
        f"<Stop><ProfileToken>{_PROFILE}</ProfileToken>"
        "<PanTilt>true</PanTilt><Zoom>true</Zoom></Stop>"
    )


async def step(pan: float, tilt: float, zoom: float = 0.0, duration: float = 0.45) -> None:
    """Nudge: move briefly then stop. One tap = one small, predictable step.

    The live view has a few seconds of latency, so hold-to-move is impossible to
    aim (you overshoot by the time you see it). Discrete steps don't depend on the
    live feedback loop, so the camera is controllable despite the delay."""
    await asyncio.to_thread(move, pan, tilt, zoom)
    await asyncio.sleep(max(0.1, min(2.0, duration)))
    await asyncio.to_thread(stop)


# ─── Presets ─────────────────────────────────────────────────────────────────

_PRESET_RE = re.compile(
    r'<[^>]*Preset token="(?P<token>[^"]+)"[^>]*>(?P<inner>.*?)</[^>]*Preset>',
    re.S,
)
_NAME_RE = re.compile(r"<[^>]*Name>(?P<name>[^<]*)</[^>]*Name>")
_NEW_TOKEN_RE = re.compile(r"<[^>]*PresetToken>(?P<token>[^<]+)</[^>]*PresetToken>")


def list_presets() -> list[dict]:
    """Return saved camera presets as ``[{token, name}, ...]`` (name may be '')."""
    xml = _call(f"<GetPresets><ProfileToken>{_PROFILE}</ProfileToken></GetPresets>")
    presets = []
    for m in _PRESET_RE.finditer(xml):
        name_m = _NAME_RE.search(m.group("inner"))
        presets.append({
            "token": m.group("token"),
            "name": (name_m.group("name").strip() if name_m else ""),
        })
    return presets


def goto_preset(token: str) -> None:
    """Move the camera to a saved preset position."""
    token = _safe_token(token)
    _call(
        f"<GotoPreset><ProfileToken>{_PROFILE}</ProfileToken>"
        f"<PresetToken>{token}</PresetToken></GotoPreset>"
    )


def save_preset(name: str) -> str:
    """Store the current position as a new preset with ``name``; return its token."""
    safe_name = re.sub(r"[^\w .\-áéíóúñÁÉÍÓÚÑ]", "", name).strip()[:32] or "Posición"
    xml = _call(
        f"<SetPreset><ProfileToken>{_PROFILE}</ProfileToken>"
        f"<PresetName>{safe_name}</PresetName></SetPreset>"
    )
    m = _NEW_TOKEN_RE.search(xml)
    return m.group("token") if m else ""


def remove_preset(token: str) -> None:
    """Delete a saved preset."""
    token = _safe_token(token)
    _call(
        f"<RemovePreset><ProfileToken>{_PROFILE}</ProfileToken>"
        f"<PresetToken>{token}</PresetToken></RemovePreset>"
    )


def _safe_token(token: str) -> str:
    """Preset tokens on this camera are short alphanumerics; reject anything else."""
    token = str(token)
    if not re.fullmatch(r"[\w\-]{1,32}", token):
        raise PTZError("Token de preset inválido.")
    return token


# ─── Backend-driven tour (patrol) ────────────────────────────────────────────
# The camera's native ONVIF tour is unreliable, so we cycle the saved presets
# ourselves: go to each preset, dwell, repeat. Owned by a single asyncio task.

_tour_task: asyncio.Task | None = None
_tour_dwell: int = 10


async def _tour_loop(dwell: int) -> None:
    """Cycle through saved presets forever until the task is cancelled."""
    try:
        while True:
            presets = await asyncio.to_thread(list_presets)
            if len(presets) < 2:
                # Nothing meaningful to patrol; wait and re-check.
                await asyncio.sleep(dwell)
                continue
            for p in presets:
                await asyncio.to_thread(goto_preset, p["token"])
                await asyncio.sleep(dwell)
    except asyncio.CancelledError:
        raise
    except Exception:
        # Swallow transient camera errors so one hiccup doesn't kill the patrol.
        await asyncio.sleep(dwell)


async def start_tour(dwell: int = 10) -> None:
    """Start (or restart) the patrol, dwelling ``dwell`` seconds per preset."""
    global _tour_task, _tour_dwell
    _tour_dwell = max(3, min(120, int(dwell)))
    await stop_tour()
    _tour_task = asyncio.create_task(_tour_loop(_tour_dwell))


async def stop_tour() -> None:
    """Stop the patrol if running."""
    global _tour_task
    if _tour_task and not _tour_task.done():
        _tour_task.cancel()
        try:
            await _tour_task
        except asyncio.CancelledError:
            pass
    _tour_task = None


def tour_active() -> bool:
    return _tour_task is not None and not _tour_task.done()
