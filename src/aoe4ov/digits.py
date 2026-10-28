"""Leitura de números da UI por template matching de glifos (sem OCR).

Pipeline de uma região (ROI):
  1. máscara de texto: pixels claros e pouco saturados (texto branco/cinza);
     pontos amarelos de caminho e terreno colorido ficam de fora.
  2. segmentação por colunas: cada bloco contíguo de colunas é um glifo.
  3. filtro de altura: só ficam glifos com altura de dígito (tira ':' e ruído).
  4. normalização: glifo centrado numa caixa com a proporção de um dígito,
     redimensionado para GLYPH_W×GLYPH_H e com média 0 / desvio 1.
  5. comparação com amostras rotuladas (assets/glyphs/<char>/*.png) por NCC.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from .anchor import ASSETS

GLYPH_W, GLYPH_H = 16, 24  # escolhido por leave-one-out (docs/DECISIONS.md)
GLYPH_PAD = 1               # margem de contexto ao redor do glifo: reduz sensibilidade a subpixel
GLYPHS_DIR = ASSETS / "glyphs"

SAT_MAX = 70          # texto é branco/cinza: saturação baixa
MIN_THR = 50          # limiar mínimo de brilho (zeros "apagados" ficam ~90)
PEAK_FRAC = 0.55      # limiar = fração do pico de brilho da ROI
DIGIT_H_REF = 8.5     # altura de um dígito em px na referência (720p, UI 100%)
H_RANGE = (0.8, 1.45) # tolerância de altura (a '/' é um pouco mais alta)
MAX_W_REF = 7.5       # mais largo que isso são dígitos encostados ("40" em 720p)
MIN_W_REF = 3         # largura mínima de cada pedaço ao quebrar um bloco
LOCAL_DELTA = 60      # relógio: quanto o texto precisa ser mais claro que a vizinhança
MIN_SCORE = 0.6       # abaixo disso o glifo é considerado não confiável

CHAR_DIRS = {"/": "slash"}


@dataclass
class Glyph:
    x: int
    y: int
    w: int
    h: int
    vec: np.ndarray            # glifo normalizado, achatado
    crop: np.ndarray           # recorte em cinza (com margem) usado na normalização
    char: str = "?"
    score: float = 0.0
    margin: float = 0.0        # diferença para o melhor caractere diferente


@dataclass
class Reading:
    text: str
    glyphs: list[Glyph] = field(default_factory=list)
    mask: np.ndarray | None = None

    @property
    def conf(self) -> float:
        return min((g.score for g in self.glyphs), default=0.0)

    @property
    def ok(self) -> bool:
        return bool(self.glyphs) and self.conf >= MIN_SCORE


def text_mask(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    f = rgb[..., :3].astype(np.float32)
    gray = f.mean(axis=2)
    sat = f.max(axis=2) - f.min(axis=2)
    neutral = sat < SAT_MAX
    peak = float(np.percentile(gray[neutral], 99)) if neutral.any() else 0.0
    thr = max(MIN_THR, peak * PEAK_FRAC)
    return gray, (gray > thr) & neutral


def _box_mean(a: np.ndarray, k: int) -> np.ndarray:
    """Média numa janela k×k (k ímpar), via imagem integral."""
    r = k // 2
    p = np.pad(a, r, mode="edge")
    s = np.pad(p.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    return (s[k:, k:] - s[:-k, k:] - s[k:, :-k] + s[:-k, :-k]) / (k * k)


def text_mask_local(rgb: np.ndarray, scale: float) -> tuple[np.ndarray, np.ndarray]:
    """Máscara por contraste local, para texto sobre fundo semitransparente.

    O relógio fica numa caixa translúcida: com areia clara atrás, o brilho
    absoluto da areia passa do limiar. O dígito, porém, é bem mais claro que
    a vizinhança imediata; a areia é clara por igual e some na subtração.
    """
    f = rgb[..., :3].astype(np.float32)
    gray = f.mean(axis=2)
    sat = f.max(axis=2) - f.min(axis=2)
    k = 2 * round(DIGIT_H_REF * scale) + 1
    local = gray - _box_mean(gray, k)
    return gray, (local > LOCAL_DELTA) & (sat < SAT_MAX) & (gray > MIN_THR)


def normalize(gray_crop: np.ndarray) -> np.ndarray:
    """Centraliza o glifo numa caixa com proporção de dígito e reduz a GLYPH_W×GLYPH_H."""
    h, w = gray_crop.shape
    box_w = max(w, round(h * GLYPH_W / GLYPH_H))
    canvas = np.full((h, box_w), gray_crop.min(), np.float32)
    x0 = (box_w - w) // 2
    canvas[:, x0:x0 + w] = gray_crop
    small = np.asarray(Image.fromarray(canvas).resize((GLYPH_W, GLYPH_H), Image.BILINEAR), np.float32)
    v = small.ravel() - small.mean()
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def _split(gray: np.ndarray, mask: np.ndarray, x0: int, x1: int, max_w: float, min_w: int) -> list[tuple[int, int]]:
    """Quebra um bloco largo demais (dígitos encostados) na coluna mais fraca."""
    if x1 - x0 <= max_w or x1 - x0 < 2 * min_w:
        return [(x0, x1)]
    weight = (gray[:, x0:x1] * mask[:, x0:x1]).sum(axis=0)
    c = min_w + int(np.argmin(weight[min_w:x1 - x0 - min_w + 1]))
    return _split(gray, mask, x0, x0 + c, max_w, min_w) + _split(gray, mask, x0 + c, x1, max_w, min_w)


def segment(rgb: np.ndarray, scale: float, pre: tuple[np.ndarray, np.ndarray] | None = None) -> tuple[list[Glyph], np.ndarray]:
    """`pre`: (cinza, máscara) já calculados, para quem usa outra máscara (relógio)."""
    gray, mask = pre if pre is not None else text_mask(rgb)
    cols = mask.any(axis=0)
    exp_h = DIGIT_H_REF * scale
    max_w = MAX_W_REF * scale
    min_w = max(2, round(MIN_W_REF * scale))

    blocks: list[tuple[int, int]] = []
    x, W = 0, mask.shape[1]
    while x < W:
        if not cols[x]:
            x += 1
            continue
        x0 = x
        while x < W and cols[x]:
            x += 1
        blocks += _split(gray, mask, x0, x, max_w, min_w)

    glyphs: list[Glyph] = []
    for x0, x1 in blocks:
        rows = np.where(mask[:, x0:x1].any(axis=1))[0]
        if rows.size == 0:
            continue
        y0, y1 = int(rows[0]), int(rows[-1]) + 1
        h = y1 - y0
        if H_RANGE[0] * exp_h <= h <= H_RANGE[1] * exp_h:
            cs = np.where(mask[y0:y1, x0:x1].any(axis=0))[0]
            gx0, gx1 = x0 + int(cs[0]), x0 + int(cs[-1]) + 1
            p = GLYPH_PAD
            crop = gray[max(0, y0 - p):y1 + p, max(0, gx0 - p):gx1 + p]
            glyphs.append(Glyph(gx0, y0, gx1 - gx0, h, normalize(crop), crop))
    return glyphs, mask


@dataclass
class GlyphBank:
    """Amostras rotuladas: matriz (N, GLYPH_W*GLYPH_H) + o caractere de cada linha."""

    chars: list[str]
    mat: np.ndarray

    @classmethod
    def from_samples(cls, samples: list[tuple[str, np.ndarray]]) -> "GlyphBank":
        return cls([c for c, _ in samples], np.stack([v for _, v in samples]))

    def classify(self, g: Glyph) -> None:
        scores = self.mat @ g.vec
        order = np.argsort(scores)[::-1]
        best = order[0]
        g.char, g.score = self.chars[best], float(scores[best])
        other = next((scores[i] for i in order if self.chars[i] != g.char), -1.0)
        g.margin = g.score - float(other)


def _char_from_dir(name: str) -> str:
    return {v: k for k, v in CHAR_DIRS.items()}.get(name, name)


@lru_cache(maxsize=1)
def default_bank() -> GlyphBank:
    samples = []
    for d in sorted(GLYPHS_DIR.iterdir()):
        for p in sorted(d.glob("*.png")):
            samples.append((_char_from_dir(d.name), normalize(np.asarray(Image.open(p).convert("L"), np.float32))))
    return GlyphBank.from_samples(samples)


def read(rgb: np.ndarray, scale: float, bank: GlyphBank | None = None,
         pre: tuple[np.ndarray, np.ndarray] | None = None) -> Reading:
    bank = bank or default_bank()
    glyphs, mask = segment(rgb, scale, pre)
    for g in glyphs:
        bank.classify(g)
    # Ruído (terreno claro, marcadores) aparece nas pontas da ROI: descarta
    # glifos de borda que não se parecem com nenhum caractere.
    while glyphs and glyphs[0].score < MIN_SCORE:
        glyphs.pop(0)
    while glyphs and glyphs[-1].score < MIN_SCORE:
        glyphs.pop()
    return Reading("".join(g.char for g in glyphs), glyphs, mask)
