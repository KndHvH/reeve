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

from . import __version__
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


def latest_report():
    reports = sorted(sessions_dir().glob("*/report.html"))
    return reports[-1] if reports else None


class TrayApp:
    def __init__(self, every: float = 2.0, debug: bool = False, mute: bool = False):
        import pystray

        self.overlay = Overlay(every, mute, debug)
        self._hub: subprocess.Popen | None = None
        item, menu = pystray.MenuItem, pystray.Menu
        self.icon = pystray.Icon(
            "aoe4ov", _tray_image(), f"aoe4-overlay {__version__}",
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

    def _open_hub(self):
        """The hub is its own process: it costs nothing while closed and does
        not compete with the overlay's Tk loop for the main thread."""
        if self._hub is None or self._hub.poll() is not None:
            self._hub = subprocess.Popen([sys.executable, "-m", "aoe4ov.hub"])

    def _open_report(self):
        r = latest_report()
        if r is not None:
            os.startfile(r)

    def _quit(self):
        self.overlay.quit_requested = True
        self.icon.stop()

    def run(self) -> None:
        threading.Thread(target=self.icon.run, name="tray", daemon=True).start()
        try:
            self.overlay.run()
        finally:
            self.icon.stop()


def main() -> None:
    """Entry point of the windowless app (`aoe4ov-app`)."""
    TrayApp().run()
