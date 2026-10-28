"""Live capture of only the needed regions (never the full screen in the loop).

The regions are copied into a buffer the size of the game area, allocated
once, so the reader uses the same coordinates as for the full image.
"""

from __future__ import annotations

import mss
import numpy as np

from .anchor import AnchorMatch, detect, to_gray
from .production import region as production_region
from .window import GameWindow


class Capture:
    def __init__(self):
        self.sct = mss.MSS()
        self.buf: np.ndarray | None = None
        self.rects: list[tuple[int, int, int, int]] = []

    def full(self, win: GameWindow) -> np.ndarray:
        """The whole game area (used only to detect the anchor)."""
        shot = self.sct.grab(win.rect)
        return np.asarray(shot)[..., 2::-1]  # BGRA → RGB

    def calibrate(self, win: GameWindow) -> AnchorMatch:
        match = self.probe(win)
        self.adopt(match, win)
        return match

    def probe(self, win: GameWindow) -> AnchorMatch:
        """Searches for the anchor on the full screen without changing what is captured."""
        return detect(to_gray(self.full(win)))

    def adopt(self, match: AnchorMatch, win: GameWindow) -> None:
        """Switches to capturing the regions of `match`."""
        self.buf = np.zeros((win.height, win.width, 3), np.uint8)
        self.rects = _union_rects(match, win, self.buf.shape)

    def grab(self, win: GameWindow) -> np.ndarray:
        """Copies only the calibrated regions into the buffer and returns the buffer."""
        assert self.buf is not None, "call calibrate() first"
        for x, y, w, h in self.rects:
            shot = self.sct.grab({"left": win.left + x, "top": win.top + y, "width": w, "height": h})
            self.buf[y:y + h, x:x + w] = np.asarray(shot)[..., 2::-1]
        return self.buf


def _union_rects(match: AnchorMatch, win: GameWindow, shape) -> list[tuple[int, int, int, int]]:
    """Two rectangles: bottom-left corner (panel + queue) and top (clock)."""
    from .anchor import project_rois

    rois = project_rois(match, win.width)
    clock = rois.pop("clock")
    boxes = list(rois.values()) + [production_region(match, shape)]
    x0 = max(0, min(b[0] for b in boxes))
    y0 = max(0, min(b[1] for b in boxes))
    x1 = min(win.width, max(b[0] + b[2] for b in boxes))
    y1 = min(win.height, max(b[1] + b[3] for b in boxes))
    cx, cy, cw, ch = clock
    cx0, cy0 = max(0, cx), max(0, cy)
    return [(x0, y0, x1 - x0, y1 - y0), (cx0, cy0, min(win.width, cx + cw) - cx0, min(win.height, cy + ch) - cy0)]
