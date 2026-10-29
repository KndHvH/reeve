"""Detects the UI position and scale by locating the anchor (the panel's icon column).

It works like the finder markers of a QR code: the house/food/wood/gold/stone
icon column is always in the bottom-left panel and has a unique shape. A
multi-scale template match (FFT-based normalized cross-correlation, numpy only)
returns where it is and at what scale. It runs once and only repeats if the
confidence drops.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from .paths import ROOT

ASSETS = ROOT / "assets"

# UI scale range relative to the scale expected from the window height.
UI_SCALE_RANGE = (0.6, 1.6)
COARSE_STEP = 0.05
FINE_STEP = 0.01
MIN_SCORE = 0.7


@dataclass(frozen=True)
class AnchorMatch:
    x: int          # top-left corner of the anchor, in image pixels
    y: int
    scale: float    # scale relative to the reference (720p, 100% UI)
    score: float    # NCC in [-1, 1]; >= MIN_SCORE is reliable

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
    """Template offset relative to the anchor origin, in pixels."""
    ox, oy = load_layout()["anchor"].get("template_offset", [0, 0])
    return round(ox * scale), round(oy * scale)


def template_box(match: "AnchorMatch") -> tuple[int, int, int, int]:
    """Where the anchor template sits in the image (x, y, w, h)."""
    tpl = _template()
    ox, oy = _offset(match.scale)
    return match.x + ox, match.y + oy, round(tpl.width * match.scale), round(tpl.height * match.scale)


def to_gray(rgb: np.ndarray) -> np.ndarray:
    return rgb[..., :3].astype(np.float32).mean(axis=2)


def _fast_len(n: int) -> int:
    """Smallest size >= n with no prime factor above 5. FFT time depends on
    the size's factors: a prime size such as 211 runs ~6x slower than 216."""
    best = 2 * n
    p5 = 1
    while p5 < best:
        p35 = p5
        while p35 < best:
            p = p35
            while p < n:
                p *= 2
            best = min(best, p)
            p35 *= 3
        p5 *= 5
    return best


class _Matcher:
    """NCC ('valid' mode) of several templates against the same image.

    The image FFT and the integral images are computed only once; each scale
    costs just the template FFT and one inverse FFT. The FFT size is padded to
    a fast length (any size >= image + template gives the same correlation).
    """

    def __init__(self, image: np.ndarray, max_tmpl: tuple[int, int]):
        self.image = image
        ih, iw = image.shape
        self.shape = (_fast_len(ih + max_tmpl[0]), _fast_len(iw + max_tmpl[1]))
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


# Height (in px) at which the coarse sweep runs, regardless of the actual resolution.
COARSE_HEIGHT = 360


def detect(gray: np.ndarray) -> AnchorMatch:
    """Searches for the anchor in `gray` (the whole game area, grayscale).

    1. Coarse scale sweep on a downscaled (360p) version of the search region:
       constant cost, whether the screen is 720p or 4K.
    2. Position and scale refinement at the original resolution, in a small window.
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

    q = min(1.0, COARSE_HEIGHT / H)  # downscale factor
    rh, rw = region.shape
    small = np.asarray(
        Image.fromarray(region).resize((max(1, round(rw * q)), max(1, round(rh * q))), Image.BOX),
        np.float32,
    )
    max_t = (round(tpl.height * base * q * hi) + 1, round(tpl.width * base * q * hi) + 1)
    m = _Matcher(small, max_t)
    _, sx, sy, s_small = _best(m, base * q * np.arange(lo, hi + 1e-9, COARSE_STEP))
    scale = s_small / q

    # Refinement at the original resolution around the guess.
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
    """(shape, contrast) of the anchor at its known position (cheap: only ±`slack` px).

    Menus, pause and the end screen hide the panel or lay a dark or bluish
    veil over it. The shape (NCC) does not notice a uniform veil, and the mean
    brightness can even rise with the bluish veil; what always drops is the
    contrast. Contrast is given relative to the template's own (a fixed
    reference): in normal play it sits at ~0.88, with a menu/veil between 0.03
    and 0.38.
    """
    t = _resized_template(match.scale)
    th, tw = t.shape
    tx, ty, _, _ = template_box(match)
    y0, x0 = max(0, ty - slack), max(0, tx - slack)
    win = to_gray(rgb[y0:ty + th + slack, x0:tx + tw + slack])
    if win.shape[0] < th or win.shape[1] < tw:
        return 0.0, 0.0
    patch = to_gray(rgb[ty:ty + th, tx:tx + tw])
    return float(_Matcher(win, (th, tw)).ncc(t).max()), float(patch.std()) / _template_std()


@lru_cache(maxsize=1)
def _template_std() -> float:
    return float(np.asarray(_template(), np.float32).std())


def panel_visible(rgb: np.ndarray, match: AnchorMatch, slack: int = 2) -> float:
    return panel_state(rgb, match, slack)[0]


def project_rois(match: AnchorMatch, width: int) -> dict[str, tuple[int, int, int, int]]:
    """Converts the layout's reference regions into actual pixels (x, y, w, h)."""
    lay = load_layout()
    s = match.scale
    out: dict[str, tuple[int, int, int, int]] = {}
    for name, (x, y, w, h) in lay["panel"].items():
        out[name] = (round(match.x + x * s), round(match.y + y * s), round(w * s), round(h * s))
    cx = width / 2
    for name, (x, y, w, h) in lay["top_center"].items():
        out[name] = (round(cx + x * s), round(y * s), round(w * s), round(h * s))
    return out
