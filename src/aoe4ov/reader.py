"""Reads the game state from an image: anchor → regions → numbers.

`read_frame` is used both live (with the mss capture) and offline
(screenshots, tests, inspect), so the code you validate is the code that runs.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from .anchor import AnchorMatch, detect, project_rois, to_gray
from .digits import DIGIT_H_REF, H_RANGE, GlyphBank, Reading, read, text_mask, text_mask_local
from .production import Production, detect_villager_in
from .production import region as production_region

COLORED_FIELDS = {"pop"}  # yellow near the cap, red at the cap
PANEL_FIELDS = ["pop", "idle", "food", "wood", "gold", "stone", "vil_food", "vil_wood", "vil_gold", "vil_stone"]


@dataclass
class Frame:
    match: AnchorMatch
    rois: dict[str, tuple[int, int, int, int]]
    readings: dict[str, Reading] = field(default_factory=dict)
    values: dict[str, object] = field(default_factory=dict)
    production: Production | None = None


def clock_seconds(digits: str) -> int | None:
    """'0036' → 36, '10217' → 3737 (1:02:17). Colons have already been discarded."""
    if not digits.isdigit() or not 4 <= len(digits) <= 6:
        return None
    h = int(digits[:-4] or 0)
    mm, ss = int(digits[-4:-2]), int(digits[-2:])
    if mm >= 60 or ss >= 60:
        return None
    return h * 3600 + mm * 60 + ss


def parse(name: str, text: str):
    """Read text → value. None if the format does not match."""
    if name == "pop":
        m = re.fullmatch(r"(\d+)/(\d+)", text)
        return (int(m[1]), int(m[2])) if m else None
    if name == "clock":
        return clock_seconds(text)
    return int(text) if text.isdigit() else None


_clock_y_hint: dict[float, tuple[int, int]] = {}  # scale -> (band y, digit height)


def read_clock(rgb: np.ndarray, scale: float, bank: GlyphBank | None = None) -> Reading:
    """The clock changes height (e.g. on age-up) and its background is
    semi-transparent. A digit-high window slides down the region; at each
    position only the glyphs aligned with the majority (same top and height)
    are kept: box edges against a bright background turn into '1'-like
    strokes, but misaligned. Among the positions read as a valid clock, the
    one with the highest confidence wins and, on a tie, the one capturing the
    tallest (whole) digits: a window that cuts 1 px off the top turns '2' into '7'.
    The last good position is tried first and accepted directly if reliable."""
    band_h = round(DIGIT_H_REF * scale * H_RANGE[1]) + 2
    key_scale = round(scale, 3)
    tol = max(1, round(scale))
    gray, mask = text_mask_local(rgb, scale)

    def at(y0: int) -> Reading | None:
        sl = slice(y0, y0 + band_h)
        r = read(rgb[sl], scale, bank, pre=(gray[sl], mask[sl]), trim_edges=True)
        if not r.glyphs:
            return None
        tops = Counter(g.y for g in r.glyphs).most_common(1)[0][0]
        hs = Counter(g.h for g in r.glyphs).most_common(1)[0][0]
        r.glyphs = [g for g in r.glyphs if abs(g.y - tops) <= tol and abs(g.h - hs) <= tol]
        r.text = "".join(g.char for g in r.glyphs)
        if not (r.ok and clock_seconds(r.text) is not None):
            return None
        for g in r.glyphs:
            g.y += y0
        return r

    def best_of(offsets) -> tuple | None:
        cands = []
        for y0 in offsets:
            r = at(y0)
            if r is not None:
                cands.append((round(r.conf, 2), min(g.h for g in r.glyphs), -y0, r))
        return max(cands, key=lambda c: c[:3]) if cands else None

    # Cache: previous position ±1 px. Valid if the digits have the same height
    # as the last good reading (a window cutting the top gives a smaller
    # height), so it does not depend on high confidence, which sits at ~0.7 at
    # resolutions without samples.
    hint = _clock_y_hint.get(key_scale)
    if hint is not None:
        y_h, h_h = hint
        c = best_of(range(max(0, y_h - 1), y_h + 2))
        if c is not None and c[1] >= h_h:
            _clock_y_hint[key_scale] = (-c[2], c[1])
            return c[3]

    c = best_of(range(0, max(1, rgb.shape[0] - band_h + 1)))
    if c is None:
        return Reading("")
    _clock_y_hint[key_scale] = (-c[2], c[1])
    return c[3]


def read_frame(rgb: np.ndarray, match: AnchorMatch | None = None, bank: GlyphBank | None = None) -> Frame:
    """`rgb`: the whole game area. With a known `match`, detection is skipped."""
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
        if name == "clock":
            r = read_clock(crop, match.scale, bank)
        elif name in COLORED_FIELDS:
            r = read(crop, match.scale, bank, pre=text_mask(crop, colored=True))
        else:
            r = read(crop, match.scale, bank)
        f.readings[name] = r
        f.values[name] = parse(name, r.text) if r.ok else None
    return f
