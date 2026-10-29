"""The app: overlay plus a tray icon, no terminal needed.

The tray (pystray, which drives the Windows notification area through
ctypes) runs in its own thread. Its menu only flips attributes on the
overlay; the overlay's Tk loop, in the main thread, applies them on the next
tick, since Tk must only be touched from the thread that created it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading

from PIL import Image, ImageDraw

from .version import shown as shown_version
from .overlay import Overlay
from .paths import data_dir, sessions_dir

ICON_SIZE = 64


def _tray_image(size: int = ICON_SIZE) -> Image.Image:
    """Gold villager on a night-blue rounded square, like the overlay cards.
    Also the source of assets/app.ico (hub window and installer)."""
    from .report import ICONS

    k = size / ICON_SIZE
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((2 * k, 2 * k, size - 3 * k, size - 3 * k), radius=12 * k, fill=(21, 28, 37, 255),
                        outline=(201, 164, 92, 255), width=max(1, round(3 * k)))
    villager = Image.open(ICONS / "villager.png").convert("RGBA")
    h = round(size - 18 * k)
    villager = villager.resize((max(1, round(villager.width * h / villager.height)), h), Image.LANCZOS)
    im.alpha_composite(villager, ((size - villager.width) // 2, round(9 * k)))
    return im


def _bring_to_front(pid: int) -> None:
    """Restores and focuses the visible top-level window of process `pid`."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def check(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd):
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(check, 0)
    if found:
        SW_RESTORE = 9
        user32.ShowWindow(found[0], SW_RESTORE)
        user32.SetForegroundWindow(found[0])


def latest_report():
    reports = sorted(sessions_dir().glob("*/report.html"))
    return reports[-1] if reports else None


class TrayApp:
    def __init__(self, every: float = 2.0, debug: bool = False, mute: bool = False, startup: bool = False):
        import pystray

        self.startup = startup   # started with Windows: no hub, just a notification
        self.overlay = Overlay(every, mute, debug)
        self._hub: subprocess.Popen | None = None
        item, menu = pystray.MenuItem, pystray.Menu
        self.icon = pystray.Icon(
            "reeve", _tray_image(), f"Reeve {shown_version()}",
            menu=menu(
                item("Overlay", self._toggle_enabled, checked=lambda _: self.overlay.enabled),
                item("Debug view", self._toggle_debug, checked=lambda _: self.overlay.debug),
                item("Mute", self._toggle_mute, checked=lambda _: self.overlay.muted),
                menu.SEPARATOR,
                item("Open hub", self._open_hub, default=True),
                item("Open last report", self._open_report, enabled=lambda _: latest_report() is not None),
                item("Open data folder", lambda: os.startfile(data_dir())),
                menu.SEPARATOR,
                item("Quit", self._quit),
            ),
        )

    # Menu actions: only flip attributes; the overlay applies them on its next tick.
    def _toggle_enabled(self):
        self.overlay.enabled = not self.overlay.enabled

    def _toggle_debug(self):
        self.overlay.debug = not self.overlay.debug

    def _toggle_mute(self):
        self.overlay.set_muted(not self.overlay.muted)

    def _notify(self, title: str, message: str) -> None:
        try:
            self.icon.notify(message, title)
        except Exception:   # a notice must never stop the overlay
            pass

    def _on_ready(self, icon) -> None:
        """Runs once the tray icon exists. Every start shows something: started
        by hand, the hub opens; started with Windows, a notification says
        Reeve is in the tray (the first-run welcome, when due, says it)."""
        from .checks import webview2_version

        icon.visible = True
        notices = self.overlay.notices.start()
        if webview2_version() is None:
            notices.append(("The hub needs Microsoft Edge WebView2",
                            "Alerts work without it. Choose \"Open hub\" to get the free runtime from Microsoft."))
        elif not self.startup:
            self._open_hub()
        elif not notices:
            notices.append(("Reeve is running",
                            "Alerts appear over the game once a match starts. The hub is in the tray."))
        for title, message in notices:
            self._notify(title, message)

    def _open_hub(self):
        """The hub is its own process: it costs nothing while closed and does
        not compete with the overlay's Tk loop for the main thread. Without
        WebView2 it opens Microsoft's download page instead."""
        from .checks import WEBVIEW2_DOWNLOAD, webview2_version

        if webview2_version() is None:
            os.startfile(WEBVIEW2_DOWNLOAD)
            return
        if self._hub is not None and self._hub.poll() is None:
            _bring_to_front(self._hub.pid)   # already open: show it instead of a second hub
            return
        # Packaged, the app's executable starts the hub with an argument (no -m there).
        args = [sys.executable, "hub"] if getattr(sys, "frozen", False) else [sys.executable, "-m", "reeve.hub"]
        self._hub = subprocess.Popen(args)

    def _close_hub(self) -> None:
        """The hub belongs to the app: quitting Reeve closes it too."""
        if self._hub is not None and self._hub.poll() is None:
            self._hub.terminate()

    def _open_report(self):
        r = latest_report()
        if r is not None:
            os.startfile(r)

    def _quit(self):
        self.overlay.quit_requested = True
        self.icon.stop()

    def _watch_updates(self):
        """Background: asks GitHub for a newer Reeve (at most once a day, see
        updates.check) and tells the user once per version, never while a
        match is open."""
        import time

        from . import updates
        from .checks import load_state, save_state
        from .paths import load_config

        time.sleep(30)                          # let the app settle first
        while not self.overlay.quit_requested:
            try:
                if (load_config().get("updates") or {}).get("check", True):
                    latest = updates.check()
                    state = load_state()
                    if (updates.newer(latest) and state.get("update_told") != latest.version
                            and self.overlay.last_status not in ("reading", "hidden")):
                        self._notify(f"Reeve {latest.version} is available",
                                     "Open the hub to see what's new and update.")
                        save_state(load_state() | {"update_told": latest.version})
            except Exception:                   # never let this disturb the overlay
                pass
            time.sleep(60)

    @staticmethod
    def _clean_sessions():
        from .retention import apply

        try:
            apply()
        except Exception:   # housekeeping must never stop the overlay
            pass

    def run(self) -> None:
        from .launcher import OPEN_HUB_EVENT, QUIT_EVENT, listen_for

        threading.Thread(target=self._clean_sessions, name="retention").start()
        threading.Thread(target=self._watch_updates, name="updates", daemon=True).start()
        self.overlay.notify = self._notify
        listen_for(OPEN_HUB_EVENT, self._open_hub)   # Reeve started again: show the hub
        listen_for(QUIT_EVENT, self._quit)           # the hub is installing an update
        threading.Thread(target=self.icon.run, args=(self._on_ready,), name="tray", daemon=True).start()
        try:
            self.overlay.run()
        finally:
            self._close_hub()
            self.icon.stop()


def main(startup: bool = False) -> None:
    """Entry point of the windowless app (`reeve-app`)."""
    from .checks import use_app_identity

    use_app_identity()   # notifications from "Reeve", not "Python"
    TrayApp(startup=startup).run()
