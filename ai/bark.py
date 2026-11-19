"""Greeniac bark detector — listens to the Garage camera's audio and flags barks.

Runs on the PC (reuses the torch+CUDA venv). Reads the camera's audio via ffmpeg,
runs PANNs (CNN14, AudioSet) on ~1s windows on the GPU, and detects dog-bark events.

Audio+video fusion: a bark while a person is (or was just) on camera is an **alert**
(someone is at the door); a bark with nobody visible is logged as ambient (wind /
other dogs). The person detector writes ``last_person_ts`` to state.json; we read it.

Config in ai/.env. Single-instance guarded. Managed by the tray app.
"""

import collections
import datetime
import os
import pathlib
import shutil
import subprocess
import time
import wave

import numpy as np
import requests
from dotenv import load_dotenv
from panns_inference import AudioTagging
from panns_inference.config import labels

import singleton
import state as st

load_dotenv(pathlib.Path(__file__).with_name(".env"))

# Which camera this bark detector listens to. Default "garage" keeps the original
# behaviour; bark_patiopapas.py sets BARK_CAMERA to run a second instance.
CAMERA = os.getenv("BARK_CAMERA", "garage").strip().lower()
_CAM_LABELS = {"garage": "Garage", "patiopapas": "Patio Papás"}
CAM_LABEL = _CAM_LABELS.get(CAMERA, CAMERA)
_SINGLE_PORTS = {"garage": 47815, "patiopapas": 47817}
SINGLE_PORT = _SINGLE_PORTS.get(CAMERA, 47815)

# RTSP audio source: garage uses BARK_RTSP (its sub carries audio); other cameras use
# BARK_RTSP_<CAM>. open_audio() pulls ONLY the audio track, so a camera whose sub is
# already maxed on connections can serve bark from its main stream cheaply.
if CAMERA == "garage":
    RTSP = os.getenv("BARK_RTSP") or os.environ["RTSP_URL"]
else:
    RTSP = os.environ[f"BARK_RTSP_{CAMERA.upper()}"]
EVENT_DIR = pathlib.Path(os.getenv("EVENT_DIR") or pathlib.Path(__file__).with_name("events"))
BARK_DIR = EVENT_DIR / "bark"
# During calibration we log every candidate bark above this low floor (so the webapp
# shows real scores to tune with). The alert threshold is set later from the webapp.
BARK_LOG_CONF = float(os.getenv("BARK_LOG_CONF", "0.15"))
BARK_CONFIRM = int(os.getenv("BARK_CONFIRM", "2"))        # consecutive windows before logging
BARK_COOLDOWN = int(os.getenv("BARK_COOLDOWN", "10"))     # seconds between logged events
FUSION_WINDOW = int(os.getenv("FUSION_WINDOW_SECONDS", "20"))  # person "recent" window
PI_BARK_URL = os.getenv("PI_BARK_URL", "")               # Pi endpoint to push bark events
PI_INGEST_TOKEN = os.getenv("PI_INGEST_TOKEN", "")

SR = 32000                 # PANNs expects 32 kHz
WIN = SR                   # 1-second analysis window
WIN_BYTES = WIN * 2        # 16-bit mono
CLIP_SECONDS = 3           # audio saved around each bark (for listening in the webapp)
_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
EVENT_DIR.mkdir(parents=True, exist_ok=True)
BARK_DIR.mkdir(parents=True, exist_ok=True)


def save_wav(path: pathlib.Path, pcm: bytes) -> None:
    """Write raw 16-bit mono 32 kHz PCM as a WAV the browser can play."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm)


def push_bark(ts: str, score: float, person: bool, wav_path: pathlib.Path,
              jpg_path: pathlib.Path | None) -> None:
    """Send a bark event (score + context + audio clip + snapshot) to the Pi."""
    if not PI_BARK_URL or not PI_INGEST_TOKEN:
        return
    try:
        files = {"audio": open(wav_path, "rb")}
        if jpg_path and jpg_path.exists():
            files["image"] = open(jpg_path, "rb")
        requests.post(
            PI_BARK_URL,
            data={"camera": CAMERA, "ts": ts, "score": f"{score:.3f}", "person": "1" if person else "0"},
            files=files,
            headers={"X-Ingest-Token": PI_INGEST_TOKEN},
            timeout=10,
        )
        for f in files.values():
            f.close()
    except Exception as exc:  # noqa: BLE001 — pushing must never break detection
        print("push_bark error:", exc, flush=True)

# Specific canine classes (exclude generic "Animal"/"Domestic animals" to avoid
# false positives from cats, birds, etc.).
_DOG_NAMES = {"dog", "bark", "bow-wow", "growling", "howl", "yip", "whimper (dog)"}
DOG_IDX = [i for i, lbl in enumerate(labels) if lbl.strip().lower() in _DOG_NAMES]


def open_audio() -> subprocess.Popen:
    """ffmpeg piping the camera audio as raw 16-bit mono 32 kHz PCM."""
    cmd = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
        # Only set up the audio track — avoids transporting the video (light, and a
        # different stream slot than the video consumers).
        "-rtsp_transport", "tcp", "-allowed_media_types", "audio", "-i", RTSP,
        "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "pipe:1",
    ]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            creationflags=_NOWIN)


def main() -> None:
    os.chdir(pathlib.Path(__file__).resolve().parent)
    guard = singleton.single_instance(SINGLE_PORT)  # noqa: F841 — kept alive
    log_name = "bark.log" if CAMERA == "garage" else f"bark_{CAMERA}.log"
    singleton.redirect_log(pathlib.Path(__file__).with_name(log_name))
    print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] --- detector de ladridos '{CAMERA}' arrancando ---")
    print(f"Cargando PANNs (CNN14) en GPU… clases caninas: {len(DOG_IDX)}")
    at = AudioTagging(checkpoint_path=None, device="cuda")
    print(f"Escuchando audio @ {SR} Hz. Log>= {BARK_LOG_CONF}, confirm={BARK_CONFIRM}, cooldown={BARK_COOLDOWN}s.")

    preview = EVENT_DIR / ("latest.jpg" if CAMERA == "garage" else f"latest_{CAMERA}.jpg")
    last_log = 0.0
    streak = 0
    windows = 0
    last_beat = time.time()

    while True:
        proc = open_audio()
        buf = b""
        ring: collections.deque[bytes] = collections.deque(maxlen=CLIP_SECONDS)  # ~3s of audio
        try:
            while True:
                chunk = proc.stdout.read(WIN_BYTES - len(buf))
                if not chunk:
                    raise RuntimeError("audio del stream cortado")
                buf += chunk
                if len(buf) < WIN_BYTES:
                    continue
                window = buf
                buf = b""
                ring.append(window)
                samples = np.frombuffer(window, np.int16).astype(np.float32) / 32768.0
                windows += 1

                out, _ = at.inference(samples[None, :])
                score = float(max(out[0][i] for i in DOG_IDX)) if DOG_IDX else 0.0

                if time.time() - last_beat >= 60:
                    print(f"[{datetime.datetime.now():%H:%M:%S}] vivo — {windows} ventanas, "
                          f"último bark-score {score:.2f}", flush=True)
                    last_beat = time.time()

                if score < BARK_LOG_CONF:
                    streak = 0
                    continue
                streak += 1
                if streak < BARK_CONFIRM:
                    continue
                now = time.time()
                if now - last_log < BARK_COOLDOWN:
                    continue
                last_log = now

                ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                last_person = float(st.load().get(f"last_person_ts_{CAMERA}", 0) or 0)
                person_present = (now - last_person) < FUSION_WINDOW

                # Save the ~3s audio clip + a snapshot, then push to the Pi for the webapp.
                wav_path = BARK_DIR / f"bark_{CAMERA}_{ts}.wav"
                save_wav(wav_path, b"".join(ring))
                jpg_path = None
                if preview.exists() and time.time() - preview.stat().st_mtime < 12:
                    jpg_path = BARK_DIR / f"bark_{CAMERA}_{ts}.jpg"
                    shutil.copyfile(preview, jpg_path)

                tag = "ALERTA (persona)" if person_present else "ambiente"
                print(f"ladrido {CAMERA} {ts} — score {score:.2f} · {tag}", flush=True)
                push_bark(ts, score, person_present, wav_path, jpg_path)
        except KeyboardInterrupt:
            break
        except Exception as exc:  # noqa: BLE001 — reconnect on stream drop
            print(f"[{datetime.datetime.now():%H:%M:%S}] reconectando audio: {exc!r}", flush=True)
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
        time.sleep(2)


if __name__ == "__main__":
    main()
