"""Locates the AoE4 window and returns its client area in physical screen pixels.

Uses only ctypes (no pywin32). The resolution comes from Windows itself, so
nothing is hardcoded per profile: it works windowed, borderless and on a
secondary monitor.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

GAME_TITLE = "Age of Empires IV"

user32 = ctypes.windll.user32

# Without this, on displays with Windows scaling != 100% the coordinates come back "virtualized".
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
except (AttributeError, OSError):
    user32.SetProcessDPIAware()


@dataclass(frozen=True)
class GameWindow:
    hwnd: int
    title: str
    left: int
    top: int
    width: int
    height: int

    @property
    def foreground(self) -> bool:
        """mss copies what is visible on screen: reading is only valid with the game in front."""
        return user32.GetForegroundWindow() == self.hwnd

    @property
    def rect(self) -> dict[str, int]:
        """Format accepted by `mss.grab`."""
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}


def _title(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def find_game_window(title: str = GAME_TITLE) -> GameWindow | None:
    """First visible window whose title contains `title`, or None."""
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def on_window(hwnd, _):
        if user32.IsWindowVisible(hwnd) and title.lower() in _title(hwnd).lower():
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(on_window, 0)
    if not found:
        return None

    hwnd = found[0]
    rc = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rc))
    origin = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    return GameWindow(hwnd, _title(hwnd), origin.x, origin.y, rc.right - rc.left, rc.bottom - rc.top)
