#!/usr/bin/env bash
# Greeniac CCTV continuous recorder.
#
# Records an RTSP camera stream into clock-aligned MP4 segments on the USB disk.
# Designed to be driven by systemd (cctv-<cam>.service) with Restart=always, so
# a dropped camera/network connection is recovered automatically.
#
# Config comes from the environment (systemd EnvironmentFile /etc/greeniac/cctv.env):
#   <CAM>_RTSP_URL    full rtsp:// URL including credentials (CAM upper-cased)
#   CCTV_ROOT         base recordings folder (default /mnt/cctv/greeniac/cctv)
#   SEGMENT_SECONDS   segment length in seconds (default 600 = 10 min)
#
# Usage: cctv_record.sh <camera_name>
set -euo pipefail

CAM="${1:?usage: cctv_record.sh <camera_name>}"
CCTV_ROOT="${CCTV_ROOT:-/mnt/cctv/greeniac/cctv}"
SEGMENT_SECONDS="${SEGMENT_SECONDS:-600}"

# Resolve the per-camera RTSP URL from an env var like GARAGE_RTSP_URL.
url_var="$(echo "$CAM" | tr '[:lower:]' '[:upper:]')_RTSP_URL"
URL="${!url_var:?missing env var $url_var}"

# Never write to the SD card if the USB disk is not mounted.
if ! mountpoint -q /mnt/cctv; then
  echo "cctv_record: /mnt/cctv is not mounted, aborting" >&2
  exit 1
fi

OUT_DIR="$CCTV_ROOT/$CAM"
mkdir -p "$OUT_DIR"

# -map 0:v:0 -c:v copy      : save the camera's H.265 video as-is (no re-encode, ~0% CPU).
# -map 0:a:0? -c:a aac 32k  : include the camera mic, transcoded G.711→AAC (MP4-friendly,
#                             tiny CPU); '?' keeps it optional so no audio never breaks it.
# segment muxer         : split into mp4 files aligned to the clock, one dir per day.
# -timeout (us)         : fail instead of hanging forever if the stream stalls;
#                         systemd then restarts us. Flag name differs across ffmpeg
#                         versions, so it is injected by the caller via $RTSP_TIMEOUT_OPT.
# Flat layout: all segments live directly in OUT_DIR with the date+time in the
# filename (ffmpeg's segment muxer cannot create per-day subfolders in this build).
exec ffmpeg -nostdin -hide_banner -loglevel warning \
  -fflags +genpts -rtsp_transport tcp ${RTSP_TIMEOUT_OPT:-} \
  -i "$URL" \
  -map 0:v:0 -map 0:a:0? -c:v copy -c:a aac -b:a 32k \
  -f segment -segment_time "$SEGMENT_SECONDS" -segment_atclocktime 1 \
  -reset_timestamps 1 -strftime 1 \
  -segment_format mp4 \
  "$OUT_DIR/${CAM}_%Y-%m-%d_%H-%M-%S.mp4"
