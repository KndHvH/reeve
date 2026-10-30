"""Where the user's data lives, separate from the program.

    %APPDATA%\\reeve\\
        config\\rules.json   only the settings the user changed
        sessions\\           recorded matches (log, frames, report)
        sounds\\             the user's own alert sounds

The program ships its defaults (config/rules.json, assets/); the user's
config file holds overrides only and is merged on top, so options added in a
new version appear with their defaults without touching the user's choices.
`REEVE_HOME` points everything somewhere else (tests, development).

The project was called aoe4-overlay; its data folder %APPDATA%\\aoe4ov is
renamed to %APPDATA%\\reeve the first time Reeve runs.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Program files (assets/, config/): the repository, or the bundle folder of the
# packaged app, where PyInstaller unpacks its data files.
FROZEN = getattr(sys, "frozen", False)
ROOT = Path(sys._MEIPASS) if FROZEN else Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "rules.json"


LEGACY_NAME = "aoe4ov"


def data_dir() -> Path:
    home = os.environ.get("REEVE_HOME")
    if home:
        base = Path(home)
    else:
        appdata = Path(os.environ.get("APPDATA", Path.home()))
        base = appdata / "reeve"
        legacy = appdata / LEGACY_NAME
        if legacy.is_dir() and not base.exists():
            try:
                legacy.rename(base)
            except OSError:   # in use by an old copy still running: keep using it for now
                return legacy
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


def diff(defaults: dict, values: dict) -> dict:
    """Only what differs from the defaults (nested dicts compared key by key)."""
    out = {}
    for k, v in values.items():
        d = defaults.get(k)
        if isinstance(v, dict) and isinstance(d, dict):
            sub = diff(d, v)
            if sub:
                out[k] = sub
        elif v != d:
            out[k] = v
    return out


def set_setting(section: str, key: str, value) -> None:
    """Saves one setting at once (the hub's switches, the overlay's build picker)."""
    values = load_config()
    values[section] = dict(values.get(section) or {}, **{key: value})
    save_overrides(diff(json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8")), values))


def save_overrides(overrides: dict) -> None:
    """Writes the user's overrides (only what differs from the defaults)."""
    path = user_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(overrides, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
