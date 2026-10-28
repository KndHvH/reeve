"""Detecta aldeão em produção pela fila de produção acima do painel.

A fila aparece sem precisar selecionar o TC (dica do usuário). Basta saber se
existe algum ícone de aldeão nela: NCC do template do ícone na região acima
da âncora. Nas capturas reais: TC parado ≤ 0,43; produzindo ≥ 0,70.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from PIL import Image

from .anchor import ASSETS, AnchorMatch, _Matcher, load_layout


@dataclass(frozen=True)
class Production:
    villager: bool
    score: float
    box: tuple[int, int, int, int] | None    # melhor ícone (x, y, w, h) na imagem
    region: tuple[int, int, int, int]         # onde procurou


@lru_cache(maxsize=4)
def _template(scale: float) -> np.ndarray:
    tpl = Image.open(ASSETS / load_layout()["production"]["template"]).convert("L")
    size = (max(3, round(tpl.width * scale)), max(3, round(tpl.height * scale)))
    return np.asarray(tpl.resize(size, Image.BILINEAR), np.float32)


def region(match: AnchorMatch, shape: tuple[int, int]) -> tuple[int, int, int, int]:
    x, y, w, h = load_layout()["production"]["region"]
    s = match.scale
    x0 = max(0, round(match.x + x * s))
    y0 = max(0, round(match.y + y * s))
    x1 = min(shape[1], round(match.x + (x + w) * s))
    y1 = min(shape[0], round(match.y + (y + h) * s))
    return x0, y0, x1 - x0, y1 - y0


def detect_villager_in(sub: np.ndarray, origin: tuple[int, int], match: AnchorMatch) -> Production:
    """`sub`: recorte em cinza de `region(...)`, cujo canto está em `origin`."""
    x0, y0 = origin
    reg = (x0, y0, sub.shape[1], sub.shape[0])
    tpl = _template(round(match.scale, 3))
    if sub.shape[0] <= tpl.shape[0] or sub.shape[1] <= tpl.shape[1]:
        return Production(False, 0.0, None, reg)
    r = _Matcher(sub, tpl.shape).ncc(tpl)
    iy, ix = np.unravel_index(int(r.argmax()), r.shape)
    score = float(r[iy, ix])
    box = (x0 + int(ix), y0 + int(iy), tpl.shape[1], tpl.shape[0])
    return Production(score >= load_layout()["production"]["min_score"], score, box, reg)
