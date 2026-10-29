"""Where the user's data lives, separate from the program.

    %APPDATA%\\aoe4ov\\
        config\\rules.json   only the settings the user changed
        sessions\\           recorded matches (log, frames, report)
        sounds\\             the user's own alert sounds

The program ships its defaults (config/rules.json, assets/); the user's
config file holds overrides only and is merged on top, so options added in a
new version appear with their defaults without touching the user's choices.
`AOE4OV_HOME` points everything somewhere else (tests, development).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "rules.json"


def data_dir() -> Path:
    home = os.environ.get("AOE4OV_HOME")
    base = Path(home) if home else Path(os.environ.get("APPDATA", Path.home())) / "aoe4ov"
    base.mkdir(parents=True, exist_ok=True)
    return base


def sessions_dir() -> Path:
    d = data_dir() / "sessions"
    d.mkdir(exist_ok=True)
    return d


def user_sounds_dir() -> Path:
    d = data_dir() / "sounds"
    d.mkdir(exist_ok=True)
    return d


def user_config_path() -> Path:
    return data_dir() / "config" / "rules.json"


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def load_config() -> dict:
    """Shipped defaults with the user's overrides merged on top."""
    cfg = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    user = user_config_path()
    if user.exists():
        cfg = _merge(cfg, json.loads(user.read_text(encoding="utf-8")))
    return cfg


def save_overrides(overrides: dict) -> None:
    """Writes the user's overrides (only what differs from the defaults)."""
    path = user_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(overrides, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
