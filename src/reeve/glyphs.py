"""Builds the glyph bank from the labeled fixtures (tests/fixtures/*.json).

Every panel glyph whose label matches in character count becomes a sample.
Samples are saved as PNG in assets/glyphs/<char>/ so you can open the folder
and see exactly what the reader uses as reference.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

from .anchor import detect, project_rois, to_gray
from .digits import CHAR_DIRS, GLYPHS_DIR, GlyphBank, normalize, segment
from .reader import read_clock

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
# Panel fields; the clock is handled separately in extract().
TRAIN_FIELDS = ["pop", "idle", "food", "wood", "gold", "stone", "vil_food", "vil_wood", "vil_gold", "vil_stone"]


def labeled_fixtures(folder: Path = FIXTURES) -> list[tuple[Path, dict]]:
    out = []
    for js in sorted(folder.glob("*.json")):
        png = js.with_suffix(".png")
        if png.exists():
            out.append((png, json.loads(js.read_text(encoding="utf-8"))))
    return out


def extract(png: Path, label: dict) -> list[tuple[str, np.ndarray, str]]:
    """(char, grayscale crop, id) for each labeled glyph in the image."""
    rgb = np.asarray(Image.open(png).convert("RGB"))
    m = detect(to_gray(rgb))
    rois = project_rois(m, rgb.shape[1])
    out = []
    for name in TRAIN_FIELDS:
        x, y, w, h = rois[name]
        crop = rgb[y:y + h, x:x + w]
        glyphs, _ = segment(crop, m.scale)
        want = label[name]
        if len(glyphs) != len(want):
            continue
        for i, (g, ch) in enumerate(zip(glyphs, want)):
            out.append((ch, g.crop.copy(), f"{png.stem}_{name}_{i}"))

    # Clock: this image's panel glyphs are enough to find the clock band;
    # the correct characters come from the label.
    if "clock" in label and out:
        x, y, w, h = rois["clock"]
        panel_bank = GlyphBank.from_samples([(ch, normalize(c)) for ch, c, _ in out])
        r = read_clock(rgb[y:y + h, x:x + w], m.scale, panel_bank)
        want = label["clock"].replace(":", "")
        if len(r.glyphs) == len(want):
            for i, (g, ch) in enumerate(zip(r.glyphs, want)):
                out.append((ch, g.crop.copy(), f"{png.stem}_clock_{i}"))
    return out


def bank_from(fixtures: list[tuple[Path, dict]]) -> GlyphBank:
    samples = [(ch, normalize(crop)) for png, lab in fixtures for ch, crop, _ in extract(png, lab)]
    return GlyphBank.from_samples(samples)


def build(folder: Path = FIXTURES) -> dict[str, int]:
    """Rewrites assets/glyphs/ from the fixtures. Identical samples are deduplicated."""
    if GLYPHS_DIR.exists():
        shutil.rmtree(GLYPHS_DIR)
    seen: set[str] = set()
    counts: dict[str, int] = {}
    for png, lab in labeled_fixtures(folder):
        for ch, crop, sid in extract(png, lab):
            img = Image.fromarray(np.clip(crop, 0, 255).astype(np.uint8))
            key = ch + hashlib.md5(img.tobytes() + bytes(img.size)).hexdigest()
            if key in seen:
                continue
            seen.add(key)
            d = GLYPHS_DIR / CHAR_DIRS.get(ch, ch)
            d.mkdir(parents=True, exist_ok=True)
            img.save(d / f"{sid}.png")
            counts[ch] = counts.get(ch, 0) + 1
    return dict(sorted(counts.items()))
