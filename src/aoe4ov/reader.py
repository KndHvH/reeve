"""Lê o estado do jogo de uma imagem: âncora → regiões → números.

`read_frame` é usado tanto ao vivo (com a captura do mss) quanto offline
(screenshots, testes, inspect), então o mesmo código é o que você valida.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from .anchor import AnchorMatch, detect, project_rois, to_gray
from .digits import DIGIT_H_REF, H_RANGE, GlyphBank, Reading, read
from .production import Production, detect_villager_in
from .production import region as production_region

CLOCK_HINT_CONF = 0.85  # na posição do cache, aceita direto acima disso
PANEL_FIELDS = ["pop", "idle", "food", "wood", "gold", "stone", "vil_food", "vil_wood", "vil_gold", "vil_stone"]


@dataclass
class Frame:
    match: AnchorMatch
    rois: dict[str, tuple[int, int, int, int]]
    readings: dict[str, Reading] = field(default_factory=dict)
    values: dict[str, object] = field(default_factory=dict)
    production: Production | None = None


def clock_seconds(digits: str) -> int | None:
    """'0036' → 36, '10217' → 3737 (1:02:17). Dois-pontos já foram descartados."""
    if not digits.isdigit() or not 4 <= len(digits) <= 6:
        return None
    h = int(digits[:-4] or 0)
    mm, ss = int(digits[-4:-2]), int(digits[-2:])
    if mm >= 60 or ss >= 60:
        return None
    return h * 3600 + mm * 60 + ss


def parse(name: str, text: str):
    """Texto lido → valor. None se o formato não bate."""
    if name == "pop":
        m = re.fullmatch(r"(\d+)/(\d+)", text)
        return (int(m[1]), int(m[2])) if m else None
    if name == "clock":
        return clock_seconds(text)
    return int(text) if text.isdigit() else None


_clock_y_hint: dict[float, int] = {}


def read_clock(rgb: np.ndarray, scale: float, bank: GlyphBank | None = None) -> Reading:
    """O relógio muda de altura (ex.: na troca de era) e o fundo dele é
    semitransparente. Uma janela da altura de um dígito desce pela região; das
    posições lidas como relógio válido (dígitos de alturas iguais), fica a de
    maior confiança. Não basta a primeira válida: uma janela que corta 1 px do
    topo transforma '2' em '7', e texturas do terreno às vezes viram dígitos,
    mas ambos com confiança bem menor que o relógio de verdade.
    A última posição boa é tentada primeiro e aceita direto se for confiável."""
    band_h = round(DIGIT_H_REF * scale * H_RANGE[1]) + 2
    key_scale = round(scale, 3)

    def at(y0: int) -> Reading | None:
        r = read(rgb[y0:y0 + band_h], scale, bank)
        if not (r.ok and clock_seconds(r.text) is not None):
            return None
        hs = [g.h for g in r.glyphs]
        if max(hs) - min(hs) > max(1, round(scale)):
            return None
        for g in r.glyphs:
            g.y += y0
        return r

    hint = _clock_y_hint.get(key_scale)
    if hint is not None:
        r = at(hint)
        if r is not None and r.conf >= CLOCK_HINT_CONF:
            return r

    candidates = []
    for y0 in range(0, max(1, rgb.shape[0] - band_h + 1)):
        r = at(y0)
        if r is not None:
            candidates.append((r.conf, y0, r))
    if not candidates:
        return Reading("")
    _, y0, best = max(candidates, key=lambda c: (c[0], -c[1]))
    _clock_y_hint[key_scale] = y0
    return best


def read_frame(rgb: np.ndarray, match: AnchorMatch | None = None, bank: GlyphBank | None = None) -> Frame:
    """`rgb`: área inteira do jogo. Com `match` conhecido, pula a detecção."""
    gray = None
    if match is None:
        gray = to_gray(rgb)
        match = detect(gray)
    rois = project_rois(match, rgb.shape[1])
    f = Frame(match, rois)
    px, py, pw, ph = production_region(match, rgb.shape)
    sub = to_gray(rgb[py:py + ph, px:px + pw]) if gray is None else gray[py:py + ph, px:px + pw]
    f.production = detect_villager_in(sub, (px, py), match)
    f.values["producing_villager"] = f.production.villager
    for name, (x, y, w, h) in rois.items():
        crop = rgb[y:y + h, x:x + w]
        r = read_clock(crop, match.scale, bank) if name == "clock" else read(crop, match.scale, bank)
        f.readings[name] = r
        f.values[name] = parse(name, r.text) if r.ok else None
    return f
