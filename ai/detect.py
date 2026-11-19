"""Greeniac CCTV person detector (runs on the PC with the RTX 3060).

Reads the Garage camera's RTSP stream through ffmpeg (robust + lets us downscale
and cap the frame rate), runs YOLO person detection on the GPU, and sends a
Telegram alert with an annotated snapshot whenever a person appears. A cooldown
avoids spamming while someone stays in frame.

Config is read from ai/.env (see .env.example). Run:  python detect.py
"""

import datetime
import os
import pathlib
import subprocess
import time

import cv2
import numpy as np
import requests
from dotenv import load_dotenv
from ultralytics import YOLO

import singleton
import state as st

load_dotenv(pathlib.Path(__file__).with_name(".env"))

# Which camera this detector instance watches. Default "garage" keeps the original
# single-camera behaviour; the wrapper detect_patiopapas.py sets DETECT_CAMERA to
# run a second instance for another camera.
CAMERA = os.getenv("DETECT_CAMERA", "garage").strip().lower()
_CAM_LABELS = {"garage": "Garage", "patiopapas": "Patio Papás"}
CAM_LABEL = _CAM_LABELS.get(CAMERA, CAMERA)
_SINGLE_PORTS = {"garage": 47811, "patiopapas": 47816}
SINGLE_PORT = _SINGLE_PORTS.get(CAMERA, 47811)

# RTSP: garage keeps RTSP_URL; other cameras use DETECT_RTSP_<CAM>.
RTSP_URL = (os.environ["RTSP_URL"] if CAMERA == "garage"
            else os.environ[f"DETECT_RTSP_{CAMERA.upper()}"])
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
MODEL = os.getenv("MODEL", "yolo11n.pt")
CONF = float(os.getenv("CONF", "0.5"))
COOLDOWN = int(os.getenv("COOLDOWN_SECONDS", "60"))
FPS = os.getenv("FPS", "3")          # frames per second to analyse
WIDTH = int(os.getenv("WIDTH", "960"))   # analysis width (16:9 → height derived)
IMGSZ = int(os.getenv("IMGSZ", "640"))   # YOLO inference size (bigger = sees farther)
CONFIRM_FRAMES = int(os.getenv("CONFIRM_FRAMES", "2"))  # frames in a row before alerting
EVENT_DIR = pathlib.Path(os.getenv("EVENT_DIR") or pathlib.Path(__file__).with_name("events"))
PI_EVENTS_URL = os.getenv("PI_EVENTS_URL", "")      # Pi endpoint to push events to
PI_INGEST_TOKEN = os.getenv("PI_INGEST_TOKEN", "")  # shared secret for that endpoint

HEIGHT = int(WIDTH * 9 / 16)  # camera is 16:9 (3840x2160)
PERSON_CLASS = 0              # COCO class id for "person"
FRAME_BYTES = WIDTH * HEIGHT * 3
EVENT_DIR.mkdir(parents=True, exist_ok=True)


def post_event(photo_path: pathlib.Path, ts: str, count: int) -> None:
    """Push a detection event (photo + metadata) to the Pi dashboard gallery."""
    if not PI_EVENTS_URL or not PI_INGEST_TOKEN:
        return
    try:
        with open(photo_path, "rb") as fh:
            requests.post(
                PI_EVENTS_URL,
                data={"camera": CAMERA, "ts": ts, "count": count},
                files={"image": fh},
                headers={"X-Ingest-Token": PI_INGEST_TOKEN},
                timeout=10,
            )
    except Exception as exc:  # pushing events must never break detection
        print("post_event error:", exc, flush=True)


def send_telegram(photo_path: pathlib.Path, caption: str) -> None:
    """Send an annotated snapshot to the configured Telegram chat."""
    if not TG_TOKEN or not TG_CHAT:
        print("  (Telegram sin configurar en .env)")
        return
    try:
        with open(photo_path, "rb") as fh:
            resp = requests.post(
                f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto",
                data={"chat_id": TG_CHAT, "caption": caption},
                files={"photo": fh},
                timeout=30,
            )
        if not resp.ok:
            print("  Telegram error:", resp.status_code, resp.text[:200])
    except Exception as exc:  # network hiccups must not kill the detector
        print("  Telegram exception:", exc)


def open_stream() -> subprocess.Popen:
    """Start ffmpeg decoding the RTSP stream to raw BGR frames at a reduced
    resolution and frame rate."""
    cmd = [
        "ffmpeg", "-nostdin", "-loglevel", "error",
        "-rtsp_transport", "tcp", "-fflags", "nobuffer",
        "-i", RTSP_URL,
        "-an", "-vf", f"fps={FPS},scale={WIDTH}:{HEIGHT}",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1",
    ]
    return subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def main() -> None:
    os.chdir(pathlib.Path(__file__).resolve().parent)  # cwd = ai/ (any launcher)
    guard = singleton.single_instance(SINGLE_PORT)  # noqa: F841  (kept alive)
    log_name = "detector.log" if CAMERA == "garage" else f"detector_{CAMERA}.log"
    singleton.redirect_log(pathlib.Path(__file__).with_name(log_name))
    print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] --- detector '{CAMERA}' arrancando ---")
    print(f"Cargando modelo {MODEL} en GPU…")
    model = YOLO(MODEL)
    model.to("cuda")
    print("Modelo en:", next(model.model.parameters()).device)
    print(f"Analizando {WIDTH}x{HEIGHT} @ {FPS} fps (solo personas). Ctrl+C para detener.")

    last_alert = 0.0
    last_preview = 0.0
    last_person_write = 0.0
    frames = 0
    streak = 0
    last_beat = time.time()
    preview_path = EVENT_DIR / ("latest.jpg" if CAMERA == "garage" else f"latest_{CAMERA}.jpg")
    while True:
        proc = open_stream()
        try:
            while True:
                raw = proc.stdout.read(FRAME_BYTES)
                if len(raw) < FRAME_BYTES:
                    raise RuntimeError("stream terminado/cortado")
                frame = np.frombuffer(raw, np.uint8).reshape((HEIGHT, WIDTH, 3))
                frames += 1

                # Save a recent frame so the bot's /foto is instant and does not
                # open a second camera connection (the camera won't share a stream).
                if time.time() - last_preview >= 2:
                    cv2.imwrite(str(preview_path), frame)
                    last_preview = time.time()

                # Heartbeat so the log shows it is alive.
                if time.time() - last_beat >= 30:
                    print(f"[{datetime.datetime.now():%H:%M:%S}] vivo — {frames} frames analizados",
                          flush=True)
                    last_beat = time.time()

                result = model.predict(frame, classes=[PERSON_CLASS], conf=CONF,
                                       imgsz=IMGSZ, device=0, verbose=False)[0]
                if len(result.boxes) == 0:
                    streak = 0
                    continue
                # Require the person to appear in several frames in a row before
                # alerting (filters out one-frame false positives like a dog).
                streak += 1
                if streak < CONFIRM_FRAMES:
                    continue
                # Mark the moment a person is present so the bark detector can fuse
                # audio+video (bark + recent person = real alert). Throttled.
                now_fuse = time.time()
                if now_fuse - last_person_write >= 2:
                    # Mark person-present for THIS camera's bark detector (audio+video fusion).
                    st.update(**{f"last_person_ts_{CAMERA}": now_fuse})
                    last_person_write = now_fuse
                now = time.time()
                if now - last_alert < COOLDOWN:
                    continue
                last_alert = now

                ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                path = EVENT_DIR / f"person_{CAMERA}_{ts}.jpg"
                cv2.imwrite(str(path), result.plot())
                count = len(result.boxes)
                # Record the event for the bot's /ultimo (Garage drives the bot).
                if CAMERA == "garage":
                    st.update(last_event=str(path), last_event_ts=ts)
                # Push it to the dashboard gallery on the Pi (all cameras).
                post_event(path, ts, count)
                # Only notify if armed and within the alert window.
                if st.should_alert():
                    caption = f"👤 Persona detectada en {CAM_LABEL}\n{ts} · {count} persona(s)"
                    print(f"ALERTA {CAMERA} {ts} — {count} persona(s)")
                    send_telegram(path, caption)
                else:
                    print(f"DETECCION {CAMERA} {ts} (desarmado/fuera de horario, sin alerta)")
        except KeyboardInterrupt:
            print("Detenido.")
            proc.kill()
            break
        except Exception as exc:
            print(f"Error de stream, reconectando en 5s: {exc}")
            proc.kill()
            time.sleep(5)


if __name__ == "__main__":
    main()
