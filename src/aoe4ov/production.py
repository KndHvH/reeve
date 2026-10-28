"""Detects villager production via the production queue above the panel.

The queue is visible without selecting the town center. It is enough
to know whether any villager icon is in it: NCC of the icon template in the
region above the anchor. On real captures: idle TC ≤ 0.43; producing ≥ 0.70.
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
    box: tuple[int, int, int, int] | None    # best icon (x, y, w, h) in the image
    region: tuple[int, int, int, int]         # where it searched


@lru_cache(maxsize=4)
def _templates(scale: float) -> list[np.ndarray]:
    """All villager icons from the layout, brought to the current scale.

    Each template stores the scale it was cropped at: an icon taken at 1080p
    matches better at 1080p than an upscaled 720p one.
    """
    out = []
    for file, tpl_scale in load_layout()["production"]["templates"]:
        tpl = Image.open(ASSETS / file).convert("L")
        k = scale / tpl_scale
        size = (max(3, round(tpl.width * k)), max(3, round(tpl.height * k)))
        out.append(np.asarray(tpl.resize(size, Image.BILINEAR), np.float32))
    return out


def region(match: AnchorMatch, shape: tuple[int, int]) -> tuple[int, int, int, int]:
    x, y, w, h = load_layout()["production"]["region"]
    s = match.scale
    x0 = max(0, round(match.x + x * s))
    y0 = max(0, round(match.y + y * s))
    x1 = min(shape[1], round(match.x + (x + w) * s))
    y1 = min(shape[0], round(match.y + (y + h) * s))
    return x0, y0, x1 - x0, y1 - y0


def detect_villager_in(sub: np.ndarray, origin: tuple[int, int], match: AnchorMatch) -> Production:
    """`sub`: grayscale crop of `region(...)`, whose corner is at `origin`.

    On screens larger than the reference, the region is downscaled to the
    reference scale before searching: ~2.3× cheaper at 1.49×,
    and all templates are compared at that same scale.
    """
    x0, y0 = origin
    reg = (x0, y0, sub.shape[1], sub.shape[0])
    k = 1.0
    if match.scale > 1.05:
        k = match.scale
        size = (max(1, round(sub.shape[1] / k)), max(1, round(sub.shape[0] / k)))
        sub = np.asarray(Image.fromarray(sub).resize(size, Image.BOX), np.float32)
    tpls = [t for t in _templates(round(match.scale / k, 3)) if t.shape[0] < sub.shape[0] and t.shape[1] < sub.shape[1]]
    if not tpls:
        return Production(False, 0.0, None, reg)
    matcher = _Matcher(sub, tuple(max(t.shape[i] for t in tpls) for i in (0, 1)))
    score, box = -1.0, None
    for tpl in tpls:
        r = matcher.ncc(tpl)
        iy, ix = np.unravel_index(int(r.argmax()), r.shape)
        if r[iy, ix] > score:
            score = float(r[iy, ix])
            box = (x0 + round(ix * k), y0 + round(iy * k), round(tpl.shape[1] * k), round(tpl.shape[0] * k))
    return Production(score >= load_layout()["production"]["min_score"], score, box, reg)
