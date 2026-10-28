"""Reads UI numbers by glyph template matching (no OCR).

Pipeline for one region (ROI):
  1. text mask: bright, low-saturation pixels (white/gray text); yellow path
     dots and colored terrain are left out.
  2. column segmentation: each contiguous block of columns is one glyph.
  3. height filter: only glyphs with digit height are kept (drops ':' and noise).
  4. normalization: glyph centered in a box with a digit's aspect ratio,
     resized to GLYPH_W×GLYPH_H with mean 0 / std 1.
  5. comparison against labeled samples (assets/glyphs/<char>/*.png) by NCC.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from .anchor import ASSETS

GLYPH_W, GLYPH_H = 16, 24  # chosen by leave-one-out (docs/DECISIONS.md)
GLYPH_PAD = 1               # context margin around the glyph: reduces subpixel sensitivity
GLYPHS_DIR = ASSETS / "glyphs"

SAT_MAX = 70          # text is white/gray: low saturation
MIN_THR = 50          # minimum brightness threshold ("dimmed" zeros sit at ~90)
PEAK_FRAC = 0.55      # threshold = fraction of the ROI's peak brightness
DIGIT_H_REF = 8.5     # digit height in px at the reference (720p, 100% UI)
H_RANGE = (0.8, 1.45) # height tolerance (the '/' is a bit taller)
MAX_W_REF = 7.5       # wider than this means touching digits ("40" at 720p)
MIN_W_REF = 3         # minimum width of each piece when splitting a block
LOCAL_DELTA = 60      # clock: how much brighter the text must be than its surroundings
MIN_SCORE = 0.6       # below this the glyph is considered unreliable

CHAR_DIRS = {"/": "slash"}


@dataclass
class Glyph:
    x: int
    y: int
    w: int
    h: int
    vec: np.ndarray            # normalized, flattened glyph
    crop: np.ndarray           # grayscale crop (with margin) used for normalization
    char: str = "?"
    score: float = 0.0
    margin: float = 0.0        # gap to the best different character


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


def text_mask(rgb: np.ndarray, colored: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """`colored`: for text that changes color (population turns yellow near the
    cap, red at the cap). Uses the pixel's strongest channel, so white, yellow
    and red all yield the same shape, and neutral text is not required."""
    f = rgb[..., :3].astype(np.float32)
    if colored:
        gray = f.max(axis=2)
        neutral = np.ones(gray.shape, bool)
    else:
        gray = f.mean(axis=2)
        neutral = (f.max(axis=2) - f.min(axis=2)) < SAT_MAX
    peak = float(np.percentile(gray[neutral], 99)) if neutral.any() else 0.0
    thr = max(MIN_THR, peak * PEAK_FRAC)
    return gray, (gray > thr) & neutral


def _box_mean(a: np.ndarray, k: int) -> np.ndarray:
    """Mean over a k×k window (k odd), via an integral image."""
    r = k // 2
    p = np.pad(a, r, mode="edge")
    s = np.pad(p.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    return (s[k:, k:] - s[:-k, k:] - s[k:, :-k] + s[:-k, :-k]) / (k * k)


def text_mask_local(rgb: np.ndarray, scale: float) -> tuple[np.ndarray, np.ndarray]:
    """Local-contrast mask, for text over a semi-transparent background.

    The clock sits in a translucent box: with bright sand behind it, the
    sand's absolute brightness exceeds the threshold. The digit, however, is
    much brighter than its immediate surroundings; the sand is uniformly
    bright and cancels out in the subtraction.
    """
    f = rgb[..., :3].astype(np.float32)
    gray = f.mean(axis=2)
    sat = f.max(axis=2) - f.min(axis=2)
    k = 2 * round(DIGIT_H_REF * scale) + 1
    local = gray - _box_mean(gray, k)
    return gray, (local > LOCAL_DELTA) & (sat < SAT_MAX) & (gray > MIN_THR)


def normalize(gray_crop: np.ndarray) -> np.ndarray:
    """Centers the glyph in a box with a digit's aspect ratio and shrinks it to GLYPH_W×GLYPH_H."""
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
    """Splits a block that is too wide (touching digits) at the weakest column."""
    if x1 - x0 <= max_w or x1 - x0 < 2 * min_w:
        return [(x0, x1)]
    weight = (gray[:, x0:x1] * mask[:, x0:x1]).sum(axis=0)
    c = min_w + int(np.argmin(weight[min_w:x1 - x0 - min_w + 1]))
    return _split(gray, mask, x0, x0 + c, max_w, min_w) + _split(gray, mask, x0 + c, x1, max_w, min_w)


def segment(rgb: np.ndarray, scale: float, pre: tuple[np.ndarray, np.ndarray] | None = None) -> tuple[list[Glyph], np.ndarray]:
    """`pre`: precomputed (gray, mask), for callers that use another mask (the clock)."""
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
    """Labeled samples: an (N, GLYPH_W*GLYPH_H) matrix plus the character of each row."""

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
         pre: tuple[np.ndarray, np.ndarray] | None = None, trim_edges: bool = False) -> Reading:
    """`trim_edges`: only for the clock, where terrain/markers show up at the
    edges of the region. The panel has no noise at the edges: a weak glyph
    there must invalidate the reading, otherwise "7/10" becomes a valid-looking "7/1"."""
    bank = bank or default_bank()
    glyphs, mask = segment(rgb, scale, pre)
    for g in glyphs:
        bank.classify(g)
    if trim_edges:
        while glyphs and glyphs[0].score < MIN_SCORE:
            glyphs.pop(0)
        while glyphs and glyphs[-1].score < MIN_SCORE:
            glyphs.pop()
    return Reading("".join(g.char for g in glyphs), glyphs, mask)
