"""Greeniac tray app — one background app that supervises the PC-side services.

Replaces the scattered autostart entries + popup console windows with a single
system-tray icon. It shows each service's status, relaunches crashed ones, and lets
you restart them or open their log from the tray menu.

Services:
  - Detector de personas   (detect.py)      — YOLO person alerts
  - Bot de Telegram         (bot.py)         — interactive bot
  - Video en vivo           (gateway.py)     — 4K→720p HLS for the dashboard
  - Conversión grabaciones  (transcoder.py)  — 4K→1080p H.264 web copies

All children are launched windowless (CREATE_NO_WINDOW) so nothing pops up.
"""

import os
import subprocess
import sys
import threading
import time

import psutil
from PIL import Image, ImageDraw
import pystray

import singleton

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
PYW = sys.executable  # the pythonw.exe running this tray → reuse for children
_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)

SERVICES = [
    {"label": "Detector personas (Garage)",    "script": "detect.py",            "log": "detector.log"},
    {"label": "Detector personas (Patio)",     "script": "detect_patiopapas.py", "log": "detector_patiopapas.log"},
    {"label": "Ladridos (Garage)",      "script": "bark.py",            "log": "bark.log"},
    {"label": "Ladridos (Patio)",       "script": "bark_patiopapas.py", "log": "bark_patiopapas.log"},
    {"label": "Bot de Telegram",        "script": "bot.py",         "log": "bot.log"},
    {"label": "Video en vivo (HLS)",    "script": "gateway.py",     "log": "gateway.log"},
    {"label": "Conversión grabaciones", "script": "transcoder.py",  "log": "transcoder.log"},
]

ACCENT = (98, 184, 58)   # verde Greeniac
AMBER = (230, 160, 30)

# Services the user explicitly stopped — the watchdog won't relaunch these until
# they're started again. Persisted as flag files so the panel (a separate process)
# and the tray agree on what's intentionally off.
DISABLED_DIR = os.path.join(HERE, ".disabled")
os.makedirs(DISABLED_DIR, exist_ok=True)


def is_disabled(script: str) -> bool:
    return os.path.isfile(os.path.join(DISABLED_DIR, script + ".off"))


def set_disabled(script: str, off: bool) -> None:
    path = os.path.join(DISABLED_DIR, script + ".off")
    if off:
        open(path, "w").close()  # noqa: SIM115
    else:
        try:
            os.remove(path)
        except OSError:
            pass


# ─── Process helpers ─────────────────────────────────────────────────────────

def _find(script: str) -> psutil.Process | None:
    """The running python/pythonw process for a given script, or None."""
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (p.info["name"] or "").lower()
            if name not in ("python.exe", "pythonw.exe"):
                continue
            if any(script in str(arg) for arg in (p.info["cmdline"] or [])):
                return p
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def is_running(script: str) -> bool:
    return _find(script) is not None


def launch(script: str) -> None:
    if is_running(script):
        return
    subprocess.Popen(
        [PYW, "-u", os.path.join(HERE, script)],
        cwd=HERE, creationflags=_NOWIN,
    )


def stop(script: str) -> None:
    """Kill the service and its children (e.g. the ffmpeg it spawned)."""
    p = _find(script)
    if not p:
        return
    try:
        for child in p.children(recursive=True):
            try:
                child.kill()
            except psutil.Error:
                pass
        p.kill()
    except psutil.Error:
        pass


def restart(script: str) -> None:
    set_disabled(script, False)  # restarting re-enables it
    stop(script)
    time.sleep(1.5)
    launch(script)


def stop_service(script: str) -> None:
    """Stop a service and mark it off so the watchdog leaves it stopped."""
    set_disabled(script, True)
    stop(script)


def start_service(script: str) -> None:
    """Re-enable and launch a service the user had stopped."""
    set_disabled(script, False)
    launch(script)


# ─── Tray icon + menu ────────────────────────────────────────────────────────

_LOGO = os.path.join(HERE, "greeniac.png")


def make_image(all_ok: bool) -> Image.Image:
    """Greeniac logo as the tray icon; amber dot overlay if a service is down."""
    try:
        img = Image.open(_LOGO).convert("RGBA").resize((64, 64), Image.LANCZOS)
    except Exception:  # noqa: BLE001 — fall back to a drawn circle
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        ImageDraw.Draw(img).ellipse((6, 6, 58, 58), fill=ACCENT)
    if not all_ok:
        d = ImageDraw.Draw(img)
        d.ellipse((40, 40, 62, 62), fill=AMBER, outline=(255, 255, 255))
    return img


def _toggle_service(script: str) -> None:
    if is_running(script):
        stop_service(script)
    else:
        start_service(script)


def _svc_item(svc: dict) -> pystray.MenuItem:
    """A submenu for one service: status label + Start/Stop + Restart + Open log."""
    def label(_item):
        return ("● " if is_running(svc["script"]) else "○ ") + svc["label"]

    def toggle_label(_item):
        return "Detener" if is_running(svc["script"]) else "Iniciar"

    return pystray.MenuItem(label, pystray.Menu(
        pystray.MenuItem(toggle_label, lambda _i, _it: _toggle_service(svc["script"])),
        pystray.MenuItem("Reiniciar", lambda _i, _it: restart(svc["script"])),
        pystray.MenuItem("Ver log", lambda _i, _it: _open(svc["log"])),
    ))


def _open(path: str) -> None:
    try:
        os.startfile(os.path.join(HERE, path))  # noqa: S606 — local log file
    except OSError:
        pass


def open_panel() -> None:
    """Open the status/log window (a separate windowed process)."""
    subprocess.Popen([PYW, os.path.join(HERE, "panel.py")], cwd=HERE)


def build_menu() -> pystray.Menu:
    items = [
        pystray.MenuItem("Abrir panel", lambda _i, _it: open_panel(), default=True),
        pystray.Menu.SEPARATOR,
    ]
    items += [_svc_item(s) for s in SERVICES]
    items += [
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Reiniciar todo", lambda _i, _it: [restart(s["script"]) for s in SERVICES]),
        pystray.MenuItem("Abrir carpeta", lambda _i, _it: _open(".")),
        pystray.MenuItem("Salir (deja los servicios corriendo)", lambda icon, _it: icon.stop()),
    ]
    return pystray.Menu(*items)


def watchdog(icon: pystray.Icon) -> None:
    """Relaunch any crashed service and keep the icon/menu fresh."""
    while True:
        try:
            all_ok = True
            for s in SERVICES:
                if is_disabled(s["script"]):
                    continue  # user stopped it on purpose — leave it off
                if not is_running(s["script"]):
                    launch(s["script"])
                    all_ok = False
            icon.icon = make_image(all_ok)
            icon.update_menu()
        except Exception:  # noqa: BLE001 — never let the supervisor die
            pass
        time.sleep(20)


def main() -> None:
    guard = singleton.single_instance(47810)  # noqa: F841 — keep alive
    icon = pystray.Icon("greeniac", make_image(False), "Greeniac", build_menu())
    threading.Thread(target=watchdog, args=(icon,), daemon=True).start()
    icon.run()


if __name__ == "__main__":
    main()
