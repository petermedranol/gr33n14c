"""Quick pipeline self-test: open the RTSP stream, run YOLO on the GPU for a few
frames, and report device, speed and detections. No Telegram needed."""

import os
import pathlib
import time

from dotenv import load_dotenv

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
from ultralytics import YOLO  # noqa: E402

load_dotenv(pathlib.Path(__file__).with_name(".env"))
RTSP_URL = os.environ["RTSP_URL"]

model = YOLO(os.getenv("MODEL", "yolo11n.pt"))
model.to("cuda")  # force GPU
print("Modelo en:", next(model.model.parameters()).device)
print("Abriendo stream y corriendo 30 frames en GPU…")

frames = 0
people = 0
t0 = time.time()
for result in model.predict(source=RTSP_URL, stream=True, classes=[0],
                            conf=0.4, vid_stride=3, imgsz=640,
                            device=0, verbose=False):
    frames += 1
    n = len(result.boxes)
    people += n
    if n:
        print(f"  frame {frames}: {n} persona(s)")
    if frames >= 30:
        break

dt = time.time() - t0
print(f"OK — {frames} frames procesados en {dt:.1f}s "
      f"({frames/dt:.1f} fps), detecciones de persona: {people}")
print("Dispositivo:", model.device)
