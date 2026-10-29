"""Entry point of the packaged app (Reeve.exe).

- `Reeve.exe` starts the overlay with its tray icon. If Reeve is already
  running (a named mutex says so), it asks that app to show its hub (a named
  event) and exits, so launching it again from the Start menu never starts a
  second overlay, and the running app owns the hub (Quit closes it).
  Started by hand it opens the hub, so starting it always shows something;
  `--startup` (the start-with-Windows entry) only shows a notification.
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
OPEN_HUB_EVENT = "Local\\Reeve.OpenHub"
QUIT_EVENT = "Local\\Reeve.Quit"   # the hub asks the app to quit (to install an update)
ERROR_ALREADY_EXISTS = 183
EVENT_MODIFY_STATE = 0x0002
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


def listen_for(name: str, callback) -> None:
    """In the running app: calls `callback` each time the named auto-reset event
    is signalled (another start asking for the hub, the hub asking to quit)."""
    import threading

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateEventW.restype = ctypes.c_void_p
    handle = kernel32.CreateEventW(None, False, False, name)

    def wait():
        while kernel32.WaitForSingleObject(ctypes.c_void_p(handle), 0xFFFFFFFF) == 0:
            callback()

    threading.Thread(target=wait, name=f"event {name}", daemon=True).start()


def signal(name: str) -> bool:
    """From another process: signals the running app; False if none listens."""
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenEventW.restype = ctypes.c_void_p
    handle = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, name)
    if not handle:
        return False
    ok = bool(kernel32.SetEvent(ctypes.c_void_p(handle)))
    kernel32.CloseHandle(ctypes.c_void_p(handle))
    return ok


def main() -> None:
    _log_to_file()
    if sys.argv[1:2] == ["hub"]:
        from .hub import main as hub_main

        hub_main()
        return
    if already_running():
        if not signal(OPEN_HUB_EVENT):   # an older Reeve without the event: start a hub of our own
            hub = [sys.executable, "hub"] if getattr(sys, "frozen", False) else [sys.executable, "-m", "reeve.hub"]
            subprocess.Popen(hub)
        return
    from .tray import main as tray_main

    tray_main(startup="--startup" in sys.argv[1:])


if __name__ == "__main__":
    main()
