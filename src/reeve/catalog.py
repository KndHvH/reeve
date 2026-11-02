"""The game catalog: civilizations, and each one's units, buildings and technologies.

The civilizations ship with Reeve (assets/catalog/civilizations.json and
assets/flags/, written by scripts/catalog.py from AoE4World's open data):
their names, aoe4guides' name for them, the villager training time and a
flag. A civilization's units, buildings, technologies and upgrades, with
costs, times and icons, are AoE4World's data too, but only downloaded for
the civilization of the build in use, the first time it is used (into the
user's data folder, catalog/<slug>/; icons shared by several civilizations
are stored once, in catalog/icons/). A match never uses the network: the
download runs when a build is picked, imported or Reeve starts.
"""

from __future__ import annotations

import json
import threading
from functools import cache
from pathlib import Path

from .paths import ROOT, data_dir

CIVS_FILE = ROOT / "assets" / "catalog" / "civilizations.json"
FLAGS = ROOT / "assets" / "flags"
DATA = "https://data.aoe4world.com/{kind}/{slug}-optimized.json"
KINDS = ("units", "buildings", "technologies", "upgrades")
COMPLETE = "complete.json"   # written last: a civilization interrupted midway is downloaded again
FORMAT = 2                   # 2: icons keep their folder (units/malians/villager-1.png was lost to units/villager-1.png)
IMAGES = "https://data.aoe4world.com/images/"


@cache
def civs() -> tuple[dict, ...]:
    return tuple(json.loads(CIVS_FILE.read_text(encoding="utf-8"))["civs"])


def find(name: str | None) -> dict | None:
    """A civilization by any of its names: aoe4guides' ("Malians", code
    "MAL") or AoE4World's (name, id, abbreviation). None for "Any
    Civilization", empty or unknown names."""
    key = str(name or "").strip().casefold()
    if not key:
        return None
    for c in civs():
        if key in {str(c[k]).casefold() for k in ("guides_name", "guides", "name", "id", "abbr", "slug")}:
            return c
    return None


def flag_file(name: str | None) -> Path | None:
    c = find(name)
    f = FLAGS / f"{c['abbr']}.png" if c else None
    return f if f is not None and f.exists() else None


def villager_s(name: str | None, default: int) -> int:
    """Villager training time at the town center; `default` when unknown."""
    c = find(name)
    return (c or {}).get("villager_s") or default


# --- per-civilization data, downloaded on demand -------------------------------------

def catalog_dir() -> Path:
    d = data_dir() / "catalog"
    d.mkdir(exist_ok=True)
    return d


def civ_dir(civ: dict) -> Path:
    return catalog_dir() / civ["slug"]


def icon_file(url: str) -> Path:
    """Where an AoE4World icon (https://data.aoe4world.com/images/<kind>/[<civ>/]x.png)
    is stored. The folders are kept: civilizations with their own art reuse
    the file name (units/villager-1.png and units/malians/villager-1.png)."""
    rel = url[len(IMAGES):] if url.startswith(IMAGES) else url.rsplit("/", 1)[-1]
    return catalog_dir() / "icons" / Path(*[p for p in rel.split("/") if p not in ("", ".", "..")])


def has(civ: dict) -> bool:
    try:
        done = json.loads((civ_dir(civ) / COMPLETE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return done.get("format") == FORMAT


def villager_icons(civ_name: str | None) -> list[Path]:
    """The stored icons of the civilization's villagers (the Gilded Villager of
    the Order of the Dragon, the Jin's villager and Mounted Villager...); []
    when the civilization is unknown or not downloaded."""
    civ = find(civ_name)
    if civ is None:
        return []
    out = []
    for it in items(civ, "units"):
        if "villager" not in (it.get("classes") or []):
            continue
        for v in [it] + list(it.get("variations") or []):
            url = str(v.get("icon") or "") if isinstance(v, dict) else ""
            f = icon_file(url) if url.startswith("https://") else None
            if f is not None and f.exists() and f not in out:
                out.append(f)
    return out


def items(civ: dict, kind: str) -> list[dict]:
    """A downloaded civilization's units/buildings/technologies/upgrades
    (AoE4World's optimized format); [] when not downloaded."""
    try:
        return json.loads((civ_dir(civ) / f"{kind}.json").read_text(encoding="utf-8"))["data"]
    except (OSError, ValueError, KeyError):
        return []


def _icons(data: dict) -> set[str]:
    out = set()
    for it in data.get("data") or []:
        for v in [it] + list(it.get("variations") or []):
            if isinstance(v, dict) and str(v.get("icon") or "").startswith("https://"):
                out.add(v["icon"])
    return out


def download(civ: dict, get=None) -> bool:
    """Downloads the civilization's data and icons not stored yet; True when
    it is complete. An icon that fails is retried the next time."""
    from .builds import _get

    get = get or _get
    if has(civ):
        return True
    d = civ_dir(civ)
    d.mkdir(parents=True, exist_ok=True)
    complete, version = True, None
    for kind in KINDS:
        try:
            raw = get(DATA.format(kind=kind, slug=civ["slug"]))
            data = json.loads(raw)
        except Exception:
            return False
        version = data.get("__version__", version)
        (d / f"{kind}.json").write_bytes(raw)
        for url in sorted(_icons(data)):
            out = icon_file(url)
            if out.exists():
                continue
            try:
                png = get(url)
            except Exception:
                complete = False
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(png)
    if complete:
        (d / COMPLETE).write_text(json.dumps({"version": version, "source": "data.aoe4world.com", "format": FORMAT}),
                                  encoding="utf-8")
    return complete


_lock = threading.Lock()


def ensure(civ_name: str | None, get=None) -> bool:
    """Downloads the catalog of a build's civilization if it is missing.
    Never raises: no network leaves it for the next time."""
    civ = find(civ_name)
    if civ is None:
        return False
    with _lock:   # the picker and Reeve's start may ask at once
        try:
            return download(civ, get)
        except Exception:
            return False


def ensure_in_background(civ_name: str | None) -> None:
    civ = find(civ_name)
    if civ is not None and not has(civ):
        threading.Thread(target=ensure, args=(civ_name,), name="catalog", daemon=True).start()


def ensure_active() -> None:
    """The catalog of the build in use (background, at Reeve's start and when
    another build is picked)."""
    from . import builds
    from .paths import load_config

    try:
        b = builds.load((load_config().get("build_order") or {}).get("active"))
    except Exception:
        return
    if b is not None:
        ensure_in_background(b.civ)
