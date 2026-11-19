#!/usr/bin/env bash
# Greeniac CCTV off-site backup to Cloudflare R2 (multi-camera).
#
# Uploads completed recording segments to an R2 bucket (S3-compatible) so footage
# survives even if the Pi or USB disk is lost/stolen. Only segments older than a
# few minutes are uploaded, so the file currently being recorded is never sent
# half-written. Already-uploaded files are skipped by rclone.
#
# Retention: after uploading, delete remote objects older than R2_RETENTION so the
# bucket keeps only the last few days and the cost stays bounded. With garage (4K
# ~12 GB/day) + patiopapas (sub ~3.8 GB/day) both at 5 days, R2 holds ~79 GB
# (~$1.18/month) — within the ~$2/month budget.
set -euo pipefail

CCTV_ROOT="${CCTV_ROOT:-/mnt/cctv/greeniac/cctv}"
BUCKET="r2:greeniac-cctv"
# Cameras to back up off-site. Each gets its own folder in the bucket.
CAMERAS="${CCTV_BACKUP_CAMERAS:-garage patiopapas 321}"
# Off-site window (default for every camera). Override per camera with
# R2_RETENTION_<CAM>. garage+patiopapas 5d ≈ 79 GB; 321 (cloud, ~1 Mbps, recorded on
# the PC and pushed here) kept 3d ≈ 33 GB → total ≈ 112 GB (~$1.7/mo, under ~$2).
R2_RETENTION="${R2_RETENTION:-5d}"
R2_RETENTION_321="${R2_RETENTION_321:-3d}"
# Local retention (keeps the USB bounded; R2 still holds the last R2_RETENTION off-site).
LOCAL_RETENTION_DAYS="${LOCAL_RETENTION_DAYS:-30}"   # originals kept locally (1 mes por cámara)
WEB_RETENTION_DAYS="${WEB_RETENTION_DAYS:-7}"        # browser-playable copies kept
EVENTS_DIR="${CCTV_EVENTS_DIR:-/mnt/cctv/greeniac/events}"

# Don't touch anything if the USB disk isn't mounted.
mountpoint -q /mnt/cctv || { echo "cctv_backup: /mnt/cctv not mounted, skipping"; exit 0; }

# Rebuild the R2 index from scratch each run (bare segment filenames; the camera
# prefix — garage_… / patiopapas_… — keeps them unique across cameras, which is
# exactly what the backend's cloud badge expects).
: > "$CCTV_ROOT/.r2_index.txt.tmp"
idx_ok=1

for cam in $CAMERAS; do
  src="$CCTV_ROOT/$cam"
  remote="$BUCKET/$cam"
  [ -d "$src" ] || continue

  # 1) Upload completed originals (skips ones already in R2). The web/ copies are
  #    regenerable from the originals, so uploading them would needlessly inflate
  #    the R2 bill — keep R2 to the originals only.
  rclone copy "$src" "$remote" \
    --min-age 3m \
    --exclude "web/**" \
    --exclude "*.part" \
    --exclude "*.build" \
    --transfers 4 \
    --checkers 8 \
    --retries 3 \
    --log-level INFO

  # 2) Prune remote objects older than this camera's retention window.
  cam_ret_var="R2_RETENTION_$(echo "$cam" | tr '[:lower:]' '[:upper:]')"
  cam_ret="${!cam_ret_var:-$R2_RETENTION}"
  rclone delete "$remote" \
    --min-age "$cam_ret" \
    --retries 3 \
    --log-level INFO

  # 3) Accumulate the index of what's in R2 (dashboard shows a cloud badge).
  if ! rclone lsf "$remote" --exclude "web/**" >> "$CCTV_ROOT/.r2_index.txt.tmp" 2>/dev/null; then
    idx_ok=0
  fi

  # 4) Local retention — keep the USB bounded so recording never stops for space.
  find "$src" -maxdepth 1 -name "${cam}_*.mp4" -mtime +"$LOCAL_RETENTION_DAYS" -delete 2>/dev/null || true
  [ -d "$src/web" ] && find "$src/web" -name "${cam}_*.mp4" -mtime +"$WEB_RETENTION_DAYS" -delete 2>/dev/null || true
done

# Publish the refreshed index atomically.
if [ "$idx_ok" = 1 ]; then
  mv "$CCTV_ROOT/.r2_index.txt.tmp" "$CCTV_ROOT/.r2_index.txt"
else
  rm -f "$CCTV_ROOT/.r2_index.txt.tmp"
fi

# Event snapshots (.jpg) and bark clips (.wav) live under events/ — prune both by age.
[ -d "$EVENTS_DIR" ] && find "$EVENTS_DIR" \( -name '*.jpg' -o -name '*.wav' \) -mtime +"$LOCAL_RETENTION_DAYS" -delete 2>/dev/null || true
