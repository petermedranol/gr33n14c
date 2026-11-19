#!/usr/bin/env bash
# Greeniac CCTV retention: free up space by deleting the oldest recordings.
#
# Runs periodically (cctv-prune.timer). Keeps deleting the oldest .mp4 segment
# until the USB disk has at least MIN_FREE_GB free, then removes empty day dirs.
set -euo pipefail

CCTV_ROOT="${CCTV_ROOT:-/mnt/cctv/greeniac/cctv}"
MOUNT="/mnt/cctv"
MIN_FREE_GB="${MIN_FREE_GB:-50}"

# Do nothing if the disk is not mounted (avoid touching the SD card).
mountpoint -q "$MOUNT" || { echo "cctv_prune: $MOUNT not mounted, skipping"; exit 0; }
[ -d "$CCTV_ROOT" ] || exit 0

free_gb() { df -BG --output=avail "$MOUNT" | tail -1 | tr -dc '0-9'; }

while [ "$(free_gb)" -lt "$MIN_FREE_GB" ]; do
  oldest="$(find "$CCTV_ROOT" -type f -name '*.mp4' -printf '%T@ %p\n' \
            | sort -n | head -1 | cut -d' ' -f2-)"
  [ -z "$oldest" ] && break   # nothing left to delete
  echo "cctv_prune: removing $oldest (free=$(free_gb)GB < ${MIN_FREE_GB}GB)"
  rm -f "$oldest"
done

# Clean up now-empty day folders.
find "$CCTV_ROOT" -mindepth 1 -type d -empty -delete 2>/dev/null || true
