"""Color themes shared by the hub, the match report and the alert cards.

assets/themes.json defines each theme with the same tokens (backgrounds,
rules, accent, text, severities). The chosen theme is a setting
(`appearance.theme`); the hub applies it at once, reports are written with
it (and rewritten when it changes), and the overlay recolors its cards when
the settings change.
"""

from __future__ import annotations

import json
from functools import lru_cache

from .paths import ROOT, load_config

DEFAULT = "age"
# Corner radius (px) of panels and cards, and of small elements (chips, swatches).
CORNERS = {"square": (3, 2), "rounded": (10, 6)}
# The game's resource colors, used by every theme unless it overrides one.
SERIES = {"series-food": "#e5484d", "series-wood": "#93582a", "series-stone": "#9fa3a8",
          "series-gold": "#efc12e", "series-idle": "#4f86d9"}


@lru_cache(maxsize=1)
def themes() -> dict[str, dict]:
    data = json.loads((ROOT / "assets" / "themes.json").read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def current(config: dict | None = None) -> tuple[str, dict]:
    """(name, theme) of the chosen theme; an unknown name falls back to the default."""
    name = ((config or load_config()).get("appearance") or {}).get("theme", DEFAULT)
    if name not in themes():
        name = DEFAULT
    return name, themes()[name]


def colors(theme: dict) -> dict[str, str]:
    """Every color token of a theme, resource colors included."""
    return SERIES | theme["colors"]


def corners(config: dict | None = None) -> str:
    c = ((config or load_config()).get("appearance") or {}).get("corners", "rounded")
    return c if c in CORNERS else "rounded"


def css(theme: dict, corner: str = "square") -> str:
    """The theme and corner style as CSS custom properties, for a page's :root."""
    big, small = CORNERS.get(corner, CORNERS["square"])
    props = "; ".join(f"--{k}: {v}" for k, v in colors(theme).items())
    return f"color-scheme: {theme['scheme']}; {props}; --radius: {big}px; --radius-sm: {small}px;"
