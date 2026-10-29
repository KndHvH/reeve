"""First-run and environment checks, told to the user as tray notifications.

- WebView2: the hub runs on the Microsoft Edge WebView2 Runtime (shipped with
  Windows 11 and most Windows 10 installs). Without it, "Open hub" opens the
  download page instead of failing silently.
- Exclusive fullscreen: no window can draw over a game in exclusive
  fullscreen, so the overlay would be invisible. Windows reports it through
  SHQueryUserNotificationState (the same signal it uses to hold back
  notifications during games); the notice asks for Borderless or Windowed.
- First calibration: the first time the resource panel is found, the user is
  told the overlay is reading the match (resolution and UI scale). If the game
  is in the foreground for a long time and the panel has never been found,
  a notice says what to check.

`Notices` only decides what to say; the tray shows it. What was already said
for good (welcome, first calibration) is kept in state.json in the data
folder. `reeve doctor` prints every check.
"""

from __future__ import annotations

import ctypes
import json
import time
import winreg
from dataclasses import dataclass, field
from typing import Callable

from .paths import data_dir

WEBVIEW2_DOWNLOAD = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
_WEBVIEW2_CLIENT = r"Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
QUNS_RUNNING_D3D_FULL_SCREEN = 3
FULLSCREEN_EVERY_S = 10     # how often the fullscreen state is asked while the game is up
NO_PANEL_AFTER_S = 300      # game in the foreground this long without ever finding the panel


def webview2_version() -> str | None:
    """Installed WebView2 Runtime version, or None when it is missing."""
    places = [(winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\WOW6432Node\\" + _WEBVIEW2_CLIENT),
              (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\" + _WEBVIEW2_CLIENT),
              (winreg.HKEY_CURRENT_USER, "Software\\" + _WEBVIEW2_CLIENT)]
    for root, key in places:
        try:
            with winreg.OpenKey(root, key) as k:
                version, _ = winreg.QueryValueEx(k, "pv")
        except OSError:
            continue
        if version and version != "0.0.0.0":
            return version
    return None


def exclusive_fullscreen() -> bool:
    """True while a Direct3D app holds exclusive fullscreen."""
    state = ctypes.c_int(0)
    if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
        return False
    return state.value == QUNS_RUNNING_D3D_FULL_SCREEN


def window_mode(hwnd: int) -> str:
    """"windowed" when the game window has a title bar, else "borderless or
    fullscreen" (both cover the monitor; exclusive_fullscreen() tells them
    apart while the game is in front)."""
    GWL_STYLE, WS_CAPTION = -16, 0x00C00000
    style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
    return "windowed" if style & WS_CAPTION == WS_CAPTION else "borderless or fullscreen"


APP_ID = "Reeve"


def use_app_identity() -> None:
    """Makes Windows show notifications and taskbar buttons as "Reeve" with
    its icon instead of "Python". An unpackaged app does this by registering
    an AppUserModelID with a display name and icon under the current user
    (HKCU, no admin rights) and declaring it in each of its processes."""
    from .paths import ROOT

    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Software\\Classes\\AppUserModelId\\" + APP_ID) as k:
            winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, "Reeve")
            winreg.SetValueEx(k, "IconUri", 0, winreg.REG_SZ, str(ROOT / "assets" / "app.ico"))
    except OSError:
        pass
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)


def _state_path():
    return data_dir() / "state.json"


def load_state() -> dict:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    _state_path().write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


@dataclass
class Notices:
    """Watches the overlay's cycles and returns (title, message) pairs to show."""
    fullscreen: Callable[[], bool] = exclusive_fullscreen
    clock: Callable[[], float] = time.monotonic
    state: dict = field(default_factory=load_state)
    _fullscreen_said: bool = False
    _fullscreen_checked: float = float("-inf")
    _no_panel_said: bool = False
    _game_since: float | None = None

    def start(self) -> list[tuple[str, str]]:
        """At app start: the welcome, once ever."""
        if self.state.get("welcomed"):
            return []
        self._remember(welcomed=True)
        return [("Reeve is running",
                 "Alerts appear over the game once a match starts. "
                 "Double-click the tray icon to open the hub: matches, reports and settings.")]

    def observe(self, step) -> list[tuple[str, str]]:
        out = []
        now = self.clock()
        if step.status == "no_game":
            self._game_since = None
            return out
        if self._game_since is None:
            self._game_since = now

        if not self._fullscreen_said and now - self._fullscreen_checked >= FULLSCREEN_EVERY_S:
            self._fullscreen_checked = now
            if self.fullscreen():
                self._fullscreen_said = True
                out.append(("AoE4 is in exclusive fullscreen",
                            "Reeve can't draw over it. In the game, set Settings > Graphics > "
                            "Display mode to Borderless (or Windowed)."))

        if step.status == "reading" and step.match is not None and not self.state.get("calibrated"):
            w, h = step.win.width, step.win.height
            ui = round(100 * step.match.scale * 720 / h)
            self._remember(calibrated={"width": w, "height": h, "scale": round(step.match.scale, 3)})
            out.append(("Reeve found the resource panel",
                        f"Reading your match at {w}×{h} (UI scale about {ui}%). Alerts are on."))

        if (step.status == "waiting" and not self.state.get("calibrated") and not self._no_panel_said
                and now - self._game_since >= NO_PANEL_AFTER_S):
            self._no_panel_said = True
            out.append(("Reeve hasn't found the resource panel yet",
                        "It appears when a match starts. If a match is running: keep the game UI "
                        "visible (not hidden), use Borderless or Windowed mode, and run "
                        "`reeve doctor` for details."))
        return out

    def _remember(self, **kv) -> None:
        self.state.update(kv)
        try:
            save_state(self.state)
        except OSError:
            pass
