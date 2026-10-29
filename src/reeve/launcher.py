"""Entry point of the packaged app (Reeve.exe).

- `Reeve.exe` starts the overlay with its tray icon. If Reeve is already
  running (a named mutex says so), it opens the hub instead, so launching it
  again from the Start menu never starts a second overlay.
- `Reeve.exe hub` starts the hub; the tray uses it, since a packaged
  executable cannot run `python -m reeve.hub`.
- The packaged app has no console: output and errors go to reeve.log in the
  data folder (kept small: started fresh when above 1 MB).
"""

from __future__ import annotations

import ctypes
import subprocess
import sys

MUTEX_NAME = "Local\\Reeve.App"
ERROR_ALREADY_EXISTS = 183
LOG_MAX = 1024 * 1024


def _log_to_file() -> None:
    if sys.stdout is not None and sys.stderr is not None:
        return
    from .paths import data_dir

    log = data_dir() / "reeve.log"
    mode = "w" if log.exists() and log.stat().st_size > LOG_MAX else "a"
    f = open(log, mode, encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = f


def already_running() -> bool:
    """Takes the app's mutex; True when another Reeve holds it. The handle is
    kept for the life of the process (Windows frees it on exit)."""
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    already_running._handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return kernel32.GetLastError() == ERROR_ALREADY_EXISTS


def main() -> None:
    _log_to_file()
    if sys.argv[1:2] == ["hub"]:
        from .hub import main as hub_main

        hub_main()
        return
    if already_running():
        hub = [sys.executable, "hub"] if getattr(sys, "frozen", False) else [sys.executable, "-m", "reeve.hub"]
        subprocess.Popen(hub)
        return
    from .tray import main as tray_main

    tray_main()


if __name__ == "__main__":
    main()
