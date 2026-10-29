"""Current age (I–IV) and age-up progress, read above the clock.

- Numeral: the roman numeral is part of the UI, always bright gold, while the
  terrain behind it varies (green grass, dry yellow grass, buildings, cattle).
  A mask of very bright gold pixels keeps the numeral and drops the terrain;
  it is matched (NCC) against four equal-width templates. Equal width matters:
  a narrow "I" template fits any single stroke of "II" or "III", so every
  template carries empty space where the other numerals have strokes.
- Age-up: while a landmark is being built a bar appears under the numeral.
  Its band is made of dark track and bright striped fill only; progress is the
  share of fill from the left. Two checks tell it from terrain: the empty
  track is truly black (mean brightness 2–17 vs ≥ 24 for terrain) and the
  fill is regularly striped (mean step ≤ 12 vs ≥ 15). The number right of
  the bar is the count of villagers building the landmark; some
  civilizations age up without builders, so it is optional.

Measured on two full matches with different civilizations (168 frames):
numeral right in all but a few isolated frames, which the state layer
rejects; bars found in every age-up frame with or without builders, no false
positives.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from PIL import Image

from .anchor import ASSETS, AnchorMatch, _Matcher, load_layout
from .digits import read

BAR_SHARE = 0.88    # columns that must be dark track or bright fill (0.91-1.0 on real bars)
DARK, BRIGHT = 55, 120
TRACK_MAX = 20      # mean brightness of the empty track: black on real bars (2-17), terrain >= 24
STRIPE_MAX = 14     # mean brightness step inside the fill: regular stripes (<= 12), terrain >= 15


@dataclass(frozen=True)
class AgeReading:
    age: int | None
    score: float
    progress: float | None      # 0–1 while aging up, else None
    builders: int | None        # villagers building the landmark


def _cfg() -> dict:
    return load_layout()["age_region"]


def _gold_mask(rgb: np.ndarray) -> np.ndarray:
    f = rgb[..., :3].astype(np.float32)
    r, g, b = f[..., 0], f[..., 1], f[..., 2]
    return ((r > 185) & (g > 135) & (r - b > 60)).astype(np.float32)


@lru_cache(maxsize=4)
def _templates(scale: float) -> dict[int, np.ndarray]:
    k = scale / _cfg()["templates_scale"]
    out = {}
    for age in (1, 2, 3, 4):
        im = Image.open(ASSETS / "age" / f"age_{age}.png").convert("L")
        size = (max(3, round(im.width * k)), max(3, round(im.height * k)))
        out[age] = np.asarray(im.resize(size, Image.BILINEAR), np.float32) / 255
    return out


def _rect(spec, match: AnchorMatch, width: int) -> tuple[int, int, int, int]:
    x, y, w, h = spec
    s = match.scale
    return round(width / 2 + x * s), round(y * s), round(w * s), round(h * s)


def read_age(rgb: np.ndarray, match: AnchorMatch, width: int) -> AgeReading:
    cfg = _cfg()
    x, y, w, h = _rect(cfg["numeral_window"], match, width)
    region = _gold_mask(rgb[y:y + h, x:x + w])
    tpls = _templates(round(match.scale, 3))
    th, tw = next(iter(tpls.values())).shape
    age, score = None, 0.0
    if region.shape[0] > th and region.shape[1] > tw and region.any():
        m = _Matcher(region, (th, tw))
        scores = {a: float(m.ncc(t).max()) for a, t in tpls.items()}
        best = max(scores, key=scores.get)
        if scores[best] >= cfg["min_score"]:
            age, score = best, scores[best]

    progress, builders = None, None
    x, y, w, h = _rect(cfg["bar"], match, width)
    band = rgb[y:y + max(1, h), x:x + w, :3].astype(np.float32)
    if band.size:
        col = band.max(axis=2).mean(axis=0)
        dark, bright = col < DARK, col > BRIGHT
        track_ok = not dark.any() or col[dark].mean() < TRACK_MAX
        stripes_ok = bright.sum() <= 4 or np.abs(np.diff(col[bright])).mean() < STRIPE_MAX
        has_bar_shape = dark.any() or bright.mean() > 0.9   # an empty track, or a (nearly) full bar
        if (dark | bright).mean() >= BAR_SHARE and has_bar_shape and track_ok and stripes_ok:
            fill = int(np.argmin(bright)) if not bright.all() else len(bright)
            progress = fill / len(bright)
            bx, by, bw, bh = _rect(cfg["builders"], match, width)
            r = read(rgb[by:by + bh, bx:bx + bw], match.scale)
            builders = int(r.text) if r.ok and r.text.isdigit() else None
    return AgeReading(age, score, progress, builders)
