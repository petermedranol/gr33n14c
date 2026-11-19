"""Greeniac Telegram bot: interactive commands for the Garage camera.

Long-polls Telegram for commands and answers them. Shares state with the detector
through ai/state.json (arm/disarm, alert schedule, last event).

Commands:
  /foto               live snapshot now
  /ultimo             last detection photo
  /estado             current state
  /armar /desarmar    enable / silence alerts
  /horario HH:MM HH:MM  set the window during which alerts fire
"""

import os
import pathlib
import subprocess
import time

import requests
from dotenv import load_dotenv

import singleton
import state as st

load_dotenv(pathlib.Path(__file__).with_name(".env"))
TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT = os.environ["TELEGRAM_CHAT_ID"]
RTSP = os.environ["RTSP_URL"]
API = f"https://api.telegram.org/bot{TOKEN}"
EVENT_DIR = pathlib.Path(os.getenv("EVENT_DIR") or pathlib.Path(__file__).with_name("events"))

HELP = (
    "Comandos de Greeniac 🌱\n"
    "/foto — imagen en vivo del Garage\n"
    "/ultimo — última persona detectada\n"
    "/estado — estado actual\n"
    "/armar — activar alertas\n"
    "/desarmar — silenciar alertas\n"
    "/horario HH:MM HH:MM — ventana de alertas (ej. /horario 20:00 07:00)"
)


def send_message(text: str) -> None:
    try:
        requests.post(f"{API}/sendMessage", data={"chat_id": CHAT, "text": text}, timeout=20)
    except Exception as exc:
        print("sendMessage error:", exc, flush=True)


def send_photo(path: str, caption: str = "") -> None:
    try:
        with open(path, "rb") as fh:
            requests.post(f"{API}/sendPhoto", data={"chat_id": CHAT, "caption": caption},
                          files={"photo": fh}, timeout=60)
    except Exception as exc:
        print("sendPhoto error:", exc, flush=True)


def snapshot() -> pathlib.Path | None:
    """Return a live frame. Prefer the detector's latest frame (no extra camera
    connection); only if it's missing/stale open the camera directly."""
    import time as _t

    EVENT_DIR.mkdir(parents=True, exist_ok=True)
    latest = EVENT_DIR / "latest.jpg"
    if latest.exists() and (_t.time() - latest.stat().st_mtime) < 10:
        return latest

    # Fallback: the detector isn't running — grab it ourselves.
    out = EVENT_DIR / "_snap.jpg"
    cmd = [
        "ffmpeg", "-nostdin", "-loglevel", "error", "-rtsp_transport", "tcp",
        "-i", RTSP, "-frames:v", "1", "-q:v", "4", "-vf", "scale=1280:-2",
        "-y", str(out),
    ]
    try:
        subprocess.run(cmd, timeout=30, check=False)
    except Exception as exc:
        print("snapshot error:", exc, flush=True)
    return out if out.exists() else None


def _valid_time(t: str) -> bool:
    try:
        h, m = t.split(":")
        return 0 <= int(h) < 24 and 0 <= int(m) < 60
    except Exception:
        return False


def handle(text: str) -> None:
    cmd = text.strip().split()[0].lower().lstrip("/").split("@")[0]
    if cmd in ("start", "ayuda", "help"):
        send_message(HELP)
    elif cmd == "foto":
        send_message("📸 Tomando foto…")
        path = snapshot()
        if path:
            send_photo(str(path), "Garage · en vivo")
        else:
            send_message("No pude capturar la imagen (¿cámara ocupada?).")
    elif cmd == "ultimo":
        s = st.load()
        last = s.get("last_event")
        if last and pathlib.Path(last).exists():
            send_photo(last, f"Última detección · {s.get('last_event_ts', '')}")
        else:
            send_message("Aún no hay detecciones registradas.")
    elif cmd == "estado":
        s = st.load()
        send_message(
            ("🟢 ARMADO" if s["armed"] else "🔴 DESARMADO")
            + f"\nVentana de alertas: {s['from']}–{s['to']}"
            + f"\nÚltima detección: {s.get('last_event_ts') or '—'}"
        )
    elif cmd == "armar":
        st.update(armed=True)
        send_message("🟢 Alertas ACTIVADAS.")
    elif cmd == "desarmar":
        st.update(armed=False)
        send_message("🔴 Alertas SILENCIADAS. (El detector sigue grabando eventos.)")
    elif cmd == "horario":
        parts = text.split()
        if len(parts) == 3 and _valid_time(parts[1]) and _valid_time(parts[2]):
            st.update(**{"from": parts[1], "to": parts[2]})
            send_message(f"⏰ Ventana de alertas: {parts[1]}–{parts[2]}")
        else:
            send_message("Uso: /horario HH:MM HH:MM  (ej. /horario 20:00 07:00)")
    else:
        send_message("No entendí ese comando.\n\n" + HELP)


OFFSET_FILE = pathlib.Path(__file__).with_name("offset.txt")


def _load_offset():
    try:
        return int(OFFSET_FILE.read_text())
    except Exception:
        return None


def _save_offset(value: int) -> None:
    try:
        OFFSET_FILE.write_text(str(value))
    except Exception:
        pass


def main() -> None:
    os.chdir(pathlib.Path(__file__).resolve().parent)  # cwd = ai/ (any launcher)
    guard = singleton.single_instance(47812)  # noqa: F841  (kept alive)
    singleton.redirect_log(pathlib.Path(__file__).with_name("bot.log"))
    print("Bot escuchando comandos…", flush=True)
    send_message("🤖 Bot Greeniac en línea. Escribe /ayuda para ver los comandos.")
    offset = _load_offset()
    while True:
        try:
            resp = requests.get(
                f"{API}/getUpdates",
                params={"offset": offset, "timeout": 30},
                timeout=40,
            ).json()
            for upd in resp.get("result", []):
                offset = upd["update_id"] + 1
                _save_offset(offset)  # ack so restarts don't reprocess
                try:
                    msg = upd.get("message") or {}
                    if str(msg.get("chat", {}).get("id")) != str(CHAT):
                        continue  # ignore anyone who is not the owner
                    text = msg.get("text", "")
                    if text:
                        print("cmd:", text, flush=True)
                        handle(text)
                except Exception as exc:  # a bad command must never kill the bot
                    print("handle error:", exc, flush=True)
        except Exception as exc:
            print("bot error:", exc, flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
