"""Captura ao vivo só das regiões necessárias (nunca a tela inteira no loop).

As regiões são copiadas para um buffer do tamanho da área do jogo, alocado uma
vez, para que o reader use as mesmas coordenadas da imagem inteira.
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
        """Área inteira do jogo (usada só para detectar a âncora)."""
        shot = self.sct.grab(win.rect)
        return np.asarray(shot)[..., 2::-1]  # BGRA → RGB

    def calibrate(self, win: GameWindow) -> AnchorMatch:
        match = self.probe(win)
        self.adopt(match, win)
        return match

    def probe(self, win: GameWindow) -> AnchorMatch:
        """Procura a âncora na tela inteira sem mudar o que é capturado."""
        return detect(to_gray(self.full(win)))

    def adopt(self, match: AnchorMatch, win: GameWindow) -> None:
        """Passa a capturar as regiões de `match`."""
        self.buf = np.zeros((win.height, win.width, 3), np.uint8)
        self.rects = _union_rects(match, win, self.buf.shape)

    def grab(self, win: GameWindow) -> np.ndarray:
        """Copia só as regiões calibradas para o buffer e devolve o buffer."""
        assert self.buf is not None, "chame calibrate() antes"
        for x, y, w, h in self.rects:
            shot = self.sct.grab({"left": win.left + x, "top": win.top + y, "width": w, "height": h})
            self.buf[y:y + h, x:x + w] = np.asarray(shot)[..., 2::-1]
        return self.buf


def _union_rects(match: AnchorMatch, win: GameWindow, shape) -> list[tuple[int, int, int, int]]:
    """Dois retângulos: canto inferior esquerdo (painel + fila) e topo (relógio)."""
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
