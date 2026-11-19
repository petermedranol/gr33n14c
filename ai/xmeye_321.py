"""Supervised launcher for the 321 (ice-cream shop) cloud camera connector.

Runs xmeye/xmeye_cloud_to_rtsp.py --camera 321 --port 8091 as a tray-managed
service: logs into the XMeye cloud (P2P) and republishes 321 as MPEG-TS on
http://127.0.0.1:8091/live. The gateway consumes that single stream and produces
HLS; the dashboard (live), the 321 person-detector and the Pi recorder all read
the gateway's HLS (the connector's HTTP output only serves one client).
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))  # ai/ (on sys.path as the script dir)

import singleton

# Keep the guard referenced for the process lifetime (single instance).
_guard = singleton.single_instance(47818)  # noqa: F841
singleton.redirect_log(os.path.join(HERE, "xmeye_321.log"))

# The connector lives in ai/xmeye and expects to run from there (DLLs, ffmpeg.exe,
# _credentials.py are all relative to its own folder).
XMEYE = os.path.join(HERE, "xmeye")
sys.path.insert(0, XMEYE)
os.chdir(XMEYE)
# 321's cloud stream has broken HEVC framing that ffmpeg can't DECODE (so live
# transcode / detection are out — see memory), but it records fine with -c copy
# (passthrough). Record MP4 segments locally; the transcoder pushes them to the Pi,
# which backs them up to R2. (When 321 moves onto the VPN it becomes a clean local
# RTSP cam and gets the full treatment.)
_REC_321 = os.path.join(HERE, "rec", "321")
sys.argv = ["xmeye_cloud_to_rtsp.py", "--camera", "321", "--protocol", "record",
            "--rec-dir", _REC_321]

import xmeye_cloud_to_rtsp  # noqa: E402 — argv/cwd must be set first


if __name__ == "__main__":
    xmeye_cloud_to_rtsp.main()
