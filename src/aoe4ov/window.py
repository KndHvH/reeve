"""Localiza a janela do AoE4 e devolve a área cliente em pixels físicos de tela.

Usa só ctypes (sem pywin32). A resolução vem do próprio Windows, então não há
nada fixo por perfil: funciona em janela, borderless e em monitor secundário.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

GAME_TITLE = "Age of Empires IV"

user32 = ctypes.windll.user32

# Sem isso, em telas com escala do Windows != 100% as coordenadas vêm "virtualizadas".
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
        """mss copia o que está visível na tela: só vale ler com o jogo na frente."""
        return user32.GetForegroundWindow() == self.hwnd

    @property
    def rect(self) -> dict[str, int]:
        """Formato aceito por `mss.grab`."""
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}


def _title(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def find_game_window(title: str = GAME_TITLE) -> GameWindow | None:
    """Primeira janela visível cujo título contém `title`, ou None."""
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
