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
    """Two rectangles: bottom-left corner (panel + queue) and top center
    (clock, plus the age numeral and age-up bar above it)."""
    from .anchor import load_layout, project_rois

    rois = project_rois(match, win.width)
    clock = rois.pop("clock")
    boxes = list(rois.values()) + [production_region(match, shape)]
    x0 = max(0, min(b[0] for b in boxes))
    y0 = max(0, min(b[1] for b in boxes))
    x1 = min(win.width, max(b[0] + b[2] for b in boxes))
    y1 = min(win.height, max(b[1] + b[3] for b in boxes))
    ax, ay, aw, ah = load_layout()["age_region"]["rect"]
    s, mid = match.scale, win.width / 2
    age = (round(mid + ax * s), round(ay * s), round(aw * s), round(ah * s))
    tx0 = max(0, min(clock[0], age[0]))
    ty0 = max(0, min(clock[1], age[1]))
    tx1 = min(win.width, max(clock[0] + clock[2], age[0] + age[2]))
    ty1 = min(win.height, max(clock[1] + clock[3], age[1] + age[3]))
    return [(x0, y0, x1 - x0, y1 - y0), (tx0, ty0, tx1 - tx0, ty1 - ty0)]
