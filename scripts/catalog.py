"""Writes assets/catalog/civilizations.json and assets/flags/ (development tool).

Run again when a game update adds a civilization:

    uv run python scripts/catalog.py

- Civilizations and villager training time: AoE4World's open data
  (https://data.aoe4world.com, https://github.com/aoe4world/data).
- Flags: aoe4guides.com's flags (https://github.com/jensbuehl/aoe4-guides,
  public/assets/flags/<code>-large.webp), saved as PNG.

Both are game content used under Microsoft's Game Content Usage Rules (see
assets/report_icons/SOURCE.md). Each civilization's units, buildings,
technologies and their icons are not bundled: Reeve downloads them for the
civilization of the build in use (reeve.catalog).
"""

from __future__ import annotations

import io
import json
import sys
import urllib.request
from datetime import date
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from reeve import __version__  # noqa: E402

DATA = "https://data.aoe4world.com"
FLAGS = "https://raw.githubusercontent.com/jensbuehl/aoe4-guides/main/public/assets/flags/{code}-large.webp"
FLAG_H = 32   # stored height in pixels; the hub and the report show them at 16-20

# aoe4guides' civilization codes (its overlay format writes the names next to
# them, src/composables/converter/useExportOverlayFormat.js) -> AoE4World's.
GUIDES = {
    "ENG": ("en", "English"), "FRE": ("fr", "French"), "RUS": ("ru", "Rus"), "MAL": ("ma", "Malians"),
    "DEL": ("de", "Delhi Sultanate"), "HRE": ("hr", "Holy Roman Empire"), "ABB": ("ab", "Abbasid Dynasty"),
    "OTT": ("ot", "Ottomans"), "CHI": ("ch", "Chinese"), "MON": ("mo", "Mongols"), "BYZ": ("by", "Byzantines"),
    "JAP": ("ja", "Japanese"), "AYY": ("ay", "Ayyubids"), "JDA": ("je", "Jeanne d'Arc"),
    "ZXL": ("zx", "Zhu Xi's Legacy"), "DRA": ("od", "Order of the Dragon"), "HOL": ("hl", "House of Lancaster"),
    "KTE": ("kt", "Knights Templar"), "GOH": ("gol", "Golden Horde"), "MAC": ("mac", "Macedonian Dynasty"),
    "SEN": ("sen", "Sengoku Daimyo"), "TUG": ("tug", "Tughlaq Dynasty"), "JIN": ("jin", "Jin Dynasty"),
    "VIK": ("vik", "Vikings"), "SCO": ("sco", "Scots"),
}


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"Reeve/{__version__} (+https://github.com/KndHvH/reeve)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def villager_times(units: dict) -> dict[str, int]:
    """Civilization abbreviation -> villager training time (s) at the town center."""
    out = {}
    for u in units["data"]:
        if u.get("baseId") != "villager" and u["id"] != "villager":
            continue
        base = (u.get("costs") or {}).get("time")
        for v in u.get("variations") or []:
            t = (v.get("costs") or {}).get("time") or base
            for civ in v.get("civs") or []:
                if t:
                    out.setdefault(civ, t)
    return out


def main() -> None:
    index = json.loads(get(f"{DATA}/civilizations/civs-index.json"))
    units = json.loads(get(f"{DATA}/units/all-optimized.json"))
    times = villager_times(units)
    by_abbr = {c["abbr"]: c for c in index.values()}
    flags = ROOT / "assets" / "flags"
    flags.mkdir(exist_ok=True)

    civs = []
    for code, (abbr, guides_name) in GUIDES.items():
        c = by_abbr.get(abbr)
        if c is None:
            print(f"! {code}: AoE4World has no civilization {abbr!r}, skipped")
            continue
        try:
            im = Image.open(io.BytesIO(get(FLAGS.format(code=code.lower())))).convert("RGBA")
            im = im.resize((max(1, round(im.width * FLAG_H / im.height)), FLAG_H), Image.LANCZOS)
            im.save(flags / f"{abbr}.png", optimize=True)
        except Exception as e:
            print(f"! {code}: no flag ({e})")
        civs.append({"abbr": abbr, "id": c["id"], "name": c["name"], "slug": c["slug"],
                     "guides": code, "guides_name": guides_name, "villager_s": times.get(abbr)})
    missing = sorted(set(by_abbr) - {c["abbr"] for c in civs})
    if missing:
        print("! AoE4World civilizations aoe4guides does not list:", ", ".join(missing))

    out = ROOT / "assets" / "catalog" / "civilizations.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({
        "_source": "AoE4World open data (data.aoe4world.com, github.com/aoe4world/data); flags from aoe4guides.com",
        "_version": units.get("__version__"),
        "_fetched": date.today().isoformat(),
        "civs": civs,
    }, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(civs)} civilizations -> {out.relative_to(ROOT)}; flags -> {flags.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
