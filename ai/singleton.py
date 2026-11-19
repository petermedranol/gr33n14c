"""Single-instance guard + self-logging, shared by the detector and the bot.

- single_instance(port): bind a localhost port; if it's taken, another copy is
  already running, so exit cleanly. This makes duplicate launches harmless.
- redirect_log(path): send stdout/stderr to a log file (only the one surviving
  instance holds the handle, so there is never a file-in-use fight).
"""

import os
import socket
import sys
import tempfile


def single_instance(port: int):
    """Exit if another copy is already running; otherwise return a handle to keep.

    On Windows the socket-bind trick is unreliable (a second bind to the same
    127.0.0.1 port can succeed), so we take an exclusive OS lock on a lock file —
    ``msvcrt.locking`` with LK_NBLCK fails immediately if another process holds it,
    and the OS releases it when the process exits (so a crash leaves no stale lock).
    Other platforms keep the socket-bind guard.
    """
    if sys.platform == "win32":
        import msvcrt

        lock_path = os.path.join(tempfile.gettempdir(), f"greeniac_{port}.lock")
        handle = open(lock_path, "a+")  # noqa: SIM115 — kept open for process life
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            print(f"Ya hay otra instancia corriendo (lock {lock_path}). Saliendo.")
            sys.exit(0)
        return handle  # caller keeps this alive for the whole process

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
        sock.listen(1)
    except OSError:
        print(f"Ya hay otra instancia corriendo (puerto {port} ocupado). Saliendo.")
        sys.exit(0)
    return sock  # caller keeps this alive for the whole process


def redirect_log(path) -> None:
    handle = open(path, "a", encoding="utf-8", buffering=1)
    sys.stdout = handle
    sys.stderr = handle
