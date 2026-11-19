# Copy to _credentials.py (gitignored) and fill in your cloud cameras.
# These are the same CloudID / user / password you'd type in the XMeye app or
# the VMS "Device Manager".

CAMERAS = {
    "mycam": {"cloud_id": "YOUR_CLOUD_ID", "user": "admin", "password": "YOUR_PASSWORD"},
}

# Flat default (used when --camera is omitted)
CLOUD_ID = "YOUR_CLOUD_ID"
DEVICE_USER = "admin"
DEVICE_PASS = "YOUR_PASSWORD"
