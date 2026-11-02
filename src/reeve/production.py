"""Detects villager production via the production queue above the panel.

The queue is visible without selecting the town center. It is enough
to know whether any villager icon is in it: NCC of the icon template in the
region above the anchor. On real captures: idle TC ≤ 0.43; producing ≥ 0.70.

Shape alone is not enough: military units (brown background), technologies
(teal) and production blocked by housing (red, with "!") have human figures
that scored 0.57–0.63 against the villager template. A villager icon has a
dark navy background, so the border of the best match must also be dark and
bluish (villager: R 19–47, B−R +3.6…+14.6; the others: R ≥ 97 or B−R ≤ −13).

Civilizations have their own villager art (the Order of the Dragon's Gilded
Villager, the Jin's Mounted Villager...). The icons cropped from the game
are always searched; when the civilization is known (the build being
followed), its villager icons from the catalog are searched too, drawn on
the queue's navy at the size of an icon in the queue.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from . import catalog
from .anchor import ASSETS, AnchorMatch, _Matcher, load_layout, to_gray


@dataclass(frozen=True)
class Production:
    villager: bool
    score: float
    box: tuple[int, int, int, int] | None    # best icon (x, y, w, h) in the image
    region: tuple[int, int, int, int]         # where it searched
    border: tuple[float, float, float] | None = None  # mean RGB of the best icon's border
    template: str = ""                        # file of the best icon


LOOK_AGAIN_S = 30   # a civilization whose catalog is still downloading is looked up again after this
_civ_found: dict[str, tuple[Path, ...]] = {}
_civ_looked: dict[str, float] = {}


def civ_icons(civ: str | None) -> tuple[Path, ...]:
    """The civilization's villager icons from the catalog; () when unknown or
    not downloaded yet. Kept once found: the catalog is not read every cycle."""
    if not civ:
        return ()
    if civ in _civ_found:
        return _civ_found[civ]
    now = time.monotonic()
    if civ in _civ_looked and now - _civ_looked[civ] < LOOK_AGAIN_S:
        return ()
    _civ_looked[civ] = now
    icons = tuple(catalog.villager_icons(civ))
    if icons:
        _civ_found[civ] = icons
    return icons


def _civ_template(file: Path, scale: float) -> np.ndarray:
    """A catalog icon as the queue shows it: on the navy background, at the
    size of a queue icon (measured: the whole icon fills the 23 px box at 720p)."""
    cfg = load_layout()["production"]["civ_icon"]
    icon = Image.open(file).convert("RGBA")
    out = Image.new("RGBA", icon.size, (*cfg["background"], 255))
    out.alpha_composite(icon)
    size = max(3, round(cfg["size"] * scale))
    return to_gray(np.asarray(out.convert("RGB").resize((size, size), Image.LANCZOS)))


@lru_cache(maxsize=8)
def _templates(scale: float, icons: tuple[Path, ...] = ()) -> list[tuple[str, np.ndarray]]:
    """All villager icons from the layout, and the civilization's `icons`,
    brought to the current scale.

    Each template stores the scale it was cropped at: an icon taken at 1080p
    matches better at 1080p than an upscaled 720p one.
    """
    out = []
    for file, tpl_scale in load_layout()["production"]["templates"]:
        tpl = Image.open(ASSETS / file).convert("L")
        k = scale / tpl_scale
        size = (max(3, round(tpl.width * k)), max(3, round(tpl.height * k)))
        out.append((Path(file).name, np.asarray(tpl.resize(size, Image.BILINEAR), np.float32)))
    for file in icons:
        try:
            out.append((file.name, _civ_template(file, scale)))
        except OSError:   # a damaged download: the icons from the game remain
            continue
    return out


def region(match: AnchorMatch, shape: tuple[int, int]) -> tuple[int, int, int, int]:
    x, y, w, h = load_layout()["production"]["region"]
    s = match.scale
    x0 = max(0, round(match.x + x * s))
    y0 = max(0, round(match.y + y * s))
    x1 = min(shape[1], round(match.x + (x + w) * s))
    y1 = min(shape[0], round(match.y + (y + h) * s))
    return x0, y0, x1 - x0, y1 - y0


def _border_rgb(rgb: np.ndarray, box: tuple[int, int, int, int], scale: float) -> tuple[float, float, float]:
    """Mean color of a thin ring just inside `box` (local coordinates)."""
    x, y, w, h = box
    b = rgb[y:y + h, x:x + w, :3].astype(np.float32)
    t = max(1, round(2 * scale))
    ring = np.concatenate([b[:t].reshape(-1, 3), b[-t:].reshape(-1, 3), b[:, :t].reshape(-1, 3), b[:, -t:].reshape(-1, 3)])
    r, g, bl = ring.mean(axis=0)
    return float(r), float(g), float(bl)


def detect_villager_in(rgb_sub: np.ndarray, origin: tuple[int, int], match: AnchorMatch,
                       civ: str | None = None) -> Production:
    """`rgb_sub`: color crop of `region(...)`, whose corner is at `origin`.
    `civ`: the civilization being played, when known (adds its villager icons).

    On screens larger than the reference, the region is downscaled to the
    reference scale before searching: ~2.3× cheaper at 1.49×,
    and all templates are compared at that same scale.
    """
    x0, y0 = origin
    sub = to_gray(rgb_sub)
    reg = (x0, y0, sub.shape[1], sub.shape[0])
    k = 1.0
    if match.scale > 1.05:
        k = match.scale
        size = (max(1, round(sub.shape[1] / k)), max(1, round(sub.shape[0] / k)))
        sub = np.asarray(Image.fromarray(sub).resize(size, Image.BOX), np.float32)
    tpls = [(n, t) for n, t in _templates(round(match.scale / k, 3), civ_icons(civ))
            if t.shape[0] < sub.shape[0] and t.shape[1] < sub.shape[1]]
    if not tpls:
        return Production(False, 0.0, None, reg)
    matcher = _Matcher(sub, tuple(max(t.shape[i] for _, t in tpls) for i in (0, 1)))
    score, box, name = -1.0, None, ""
    for n, tpl in tpls:
        r = matcher.ncc(tpl)
        iy, ix = np.unravel_index(int(r.argmax()), r.shape)
        if r[iy, ix] > score:
            score, name = float(r[iy, ix]), n
            box = (x0 + round(ix * k), y0 + round(iy * k), round(tpl.shape[1] * k), round(tpl.shape[0] * k))
    cfg = load_layout()["production"]

    def is_navy(c):
        return max(c) <= cfg["border_max_brightness"] and c[2] - c[0] >= cfg["border_min_blue_minus_red"]

    bx, by, bw, bh = box
    border = _border_rgb(rgb_sub, (bx - x0, by - y0, bw, bh), match.scale)
    if score >= cfg["min_score"] and not is_navy(border):
        # Searched at the reference scale, the box can land 1-2 px off the icon;
        # over the map its ring then takes in terrain (half the villagers in
        # recorded matches were refused so). The darkest ring nearby is the icon's.
        reach = round(cfg["border_search"] * match.scale)
        for dy in range(-reach, reach + 1):
            for dx in range(-reach, reach + 1):
                x, y = bx - x0 + dx, by - y0 + dy
                if (dx or dy) and x >= 0 and y >= 0 and x + bw <= rgb_sub.shape[1] and y + bh <= rgb_sub.shape[0]:
                    c = _border_rgb(rgb_sub, (x, y, bw, bh), match.scale)
                    if max(c) < max(border):
                        border, box = c, (x0 + x, y0 + y, bw, bh)
    return Production(score >= cfg["min_score"] and is_navy(border), score, box, reg, border, name)
