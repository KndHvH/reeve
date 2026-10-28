"""Detecta a posição e a escala da UI procurando a âncora (coluna de ícones do painel).

Funciona como os marcadores de um QR code: a coluna de ícones casa/comida/madeira/
ouro/pedra está sempre no painel inferior esquerdo e tem forma única. Um template
matching multi-escala (correlação cruzada normalizada via FFT, só numpy) devolve
onde ela está e em que escala. Roda uma vez e só repete se a confiança cair.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

ASSETS = Path(__file__).resolve().parents[2] / "assets"

# Faixa de escala da UI relativa à escala esperada pela altura da janela.
UI_SCALE_RANGE = (0.6, 1.6)
COARSE_STEP = 0.05
FINE_STEP = 0.01
MIN_SCORE = 0.7


@dataclass(frozen=True)
class AnchorMatch:
    x: int          # canto superior esquerdo da âncora, em pixels da imagem
    y: int
    scale: float    # escala em relação à referência (720p, UI 100%)
    score: float    # NCC em [-1, 1]; ≥ MIN_SCORE é confiável

    @property
    def ok(self) -> bool:
        return self.score >= MIN_SCORE


@lru_cache(maxsize=1)
def load_layout() -> dict:
    return json.loads((ASSETS / "layout.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _template() -> Image.Image:
    return Image.open(ASSETS / load_layout()["anchor"]["template"]).convert("L")


def _offset(scale: float) -> tuple[int, int]:
    """Deslocamento do template em relação à origem da âncora, em pixels."""
    ox, oy = load_layout()["anchor"].get("template_offset", [0, 0])
    return round(ox * scale), round(oy * scale)


def template_box(match: "AnchorMatch") -> tuple[int, int, int, int]:
    """Onde o template da âncora está na imagem (x, y, w, h)."""
    tpl = _template()
    ox, oy = _offset(match.scale)
    return match.x + ox, match.y + oy, round(tpl.width * match.scale), round(tpl.height * match.scale)


def to_gray(rgb: np.ndarray) -> np.ndarray:
    return rgb[..., :3].astype(np.float32).mean(axis=2)


class _Matcher:
    """NCC (modo 'valid') de vários templates contra a mesma imagem.

    A FFT da imagem e as imagens integrais são calculadas uma vez só; cada escala
    custa apenas a FFT do template e uma FFT inversa.
    """

    def __init__(self, image: np.ndarray, max_tmpl: tuple[int, int]):
        self.image = image
        ih, iw = image.shape
        self.shape = (ih + max_tmpl[0], iw + max_tmpl[1])
        self.F = np.fft.rfft2(image, self.shape)
        self.S1 = np.pad(image.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
        self.S2 = np.pad((image * image).cumsum(0).cumsum(1), ((1, 0), (1, 0)))

    def ncc(self, tmpl: np.ndarray) -> np.ndarray:
        th, tw = tmpl.shape
        ih, iw = self.image.shape
        t = tmpl - tmpl.mean()
        t_norm = np.sqrt((t * t).sum())
        corr = np.fft.irfft2(self.F * np.fft.rfft2(t[::-1, ::-1], self.shape), self.shape)
        corr = corr[th - 1:ih, tw - 1:iw]

        def window_sum(s):
            return s[th:, tw:] - s[:-th, tw:] - s[th:, :-tw] + s[:-th, :-tw]

        wsum = window_sum(self.S1)
        wvar = window_sum(self.S2) - wsum * wsum / (th * tw)
        return corr / (np.sqrt(np.maximum(wvar, 1e-6)) * max(t_norm, 1e-6))


def _resized_template(scale: float) -> np.ndarray:
    tpl = _template()
    w = max(3, round(tpl.width * scale))
    h = max(3, round(tpl.height * scale))
    return np.asarray(tpl.resize((w, h), Image.BILINEAR), np.float32)


def _best(matcher: _Matcher, scales) -> tuple[float, int, int, float]:
    best = (-2.0, 0, 0, 1.0)
    ih, iw = matcher.image.shape
    for s in scales:
        t = _resized_template(s)
        if t.shape[0] >= ih or t.shape[1] >= iw:
            continue
        r = matcher.ncc(t)
        iy, ix = np.unravel_index(int(r.argmax()), r.shape)
        if r[iy, ix] > best[0]:
            best = (float(r[iy, ix]), int(ix), int(iy), float(s))
    return best


# Altura (em px) em que a varredura grossa roda, independente da resolução real.
COARSE_HEIGHT = 360


def detect(gray: np.ndarray) -> AnchorMatch:
    """Procura a âncora em `gray` (imagem inteira da área do jogo, tons de cinza).

    1. Varredura grossa de escalas numa versão reduzida (360p) da região de busca:
       custo constante, seja a tela 720p ou 4K.
    2. Refino de posição e escala na resolução original, numa janela pequena.
    """
    H, W = gray.shape
    lay = load_layout()
    search = lay["anchor"]["search"]
    x1 = int(W * search["right_frac"])
    y0 = int(H * search["top_frac"])
    region = gray[y0:, :x1]

    base = H / lay["ref_height"]
    lo, hi = UI_SCALE_RANGE
    tpl = _template()

    q = min(1.0, COARSE_HEIGHT / H)  # fator de redução
    rh, rw = region.shape
    small = np.asarray(
        Image.fromarray(region).resize((max(1, round(rw * q)), max(1, round(rh * q))), Image.BOX),
        np.float32,
    )
    max_t = (round(tpl.height * base * q * hi) + 1, round(tpl.width * base * q * hi) + 1)
    m = _Matcher(small, max_t)
    _, sx, sy, s_small = _best(m, base * q * np.arange(lo, hi + 1e-9, COARSE_STEP))
    scale = s_small / q

    # Refino na resolução original em torno do palpite.
    err = COARSE_STEP / 2
    pad = round(2 / q) + 2
    th = round(tpl.height * scale * (1 + err)) + 1
    tw = round(tpl.width * scale * (1 + err)) + 1
    gx, gy = round(sx / q), round(sy / q)
    cx0, cy0 = max(0, gx - pad), max(0, gy - pad)
    win = region[cy0:gy + th + pad, cx0:gx + tw + pad]
    fm = _Matcher(win, (th, tw))
    score, ix, iy, s = _best(fm, scale * (1 + np.arange(-err, err + 1e-9, FINE_STEP / 2)))
    ox, oy = _offset(s)
    return AnchorMatch(x=cx0 + ix - ox, y=y0 + cy0 + iy - oy, scale=s, score=score)


def panel_state(rgb: np.ndarray, match: AnchorMatch, slack: int = 2) -> tuple[float, float]:
    """(forma, brilho) da âncora na posição conhecida (barato: só ±`slack` px).

    Menu, pausa e tela de fim escondem ou escurecem o painel. A forma (NCC)
    não muda quando a tela inteira escurece por igual, por isso o brilho médio
    também é devolvido: quem chama compara com o brilho do início da partida.
    """
    t = _resized_template(match.scale)
    th, tw = t.shape
    tx, ty, _, _ = template_box(match)
    y0, x0 = max(0, ty - slack), max(0, tx - slack)
    win = to_gray(rgb[y0:ty + th + slack, x0:tx + tw + slack])
    if win.shape[0] < th or win.shape[1] < tw:
        return 0.0, 0.0
    return float(_Matcher(win, (th, tw)).ncc(t).max()), float(win.mean())


def panel_visible(rgb: np.ndarray, match: AnchorMatch, slack: int = 2) -> float:
    return panel_state(rgb, match, slack)[0]


def project_rois(match: AnchorMatch, width: int) -> dict[str, tuple[int, int, int, int]]:
    """Converte as regiões de referência do layout em pixels reais (x, y, w, h)."""
    lay = load_layout()
    s = match.scale
    out: dict[str, tuple[int, int, int, int]] = {}
    for name, (x, y, w, h) in lay["panel"].items():
        out[name] = (round(match.x + x * s), round(match.y + y * s), round(w * s), round(h * s))
    cx = width / 2
    for name, (x, y, w, h) in lay["top_center"].items():
        out[name] = (round(cx + x * s), round(y * s), round(w * s), round(h * s))
    return out
