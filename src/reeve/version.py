"""The version shown to the user, telling a release from a development copy.

A release shows its number (`0.2.2`). Anything else shows where it comes
from: `0.2.2-dev.7+b0c37b9` is 7 commits after the last release tag, at
commit b0c37b9, and `.dirty` is added when there are uncommitted changes.
Running from source, this comes from git; a packaged app reads
`build_info.json`, which scripts/build.py writes (plain only for --release).
Update checks compare `reeve.__version__`, the plain number.
"""

from __future__ import annotations

import json
import subprocess
from functools import lru_cache

from . import __version__
from .paths import FROZEN, ROOT


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=5,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()


def from_git() -> str:
    """Version of the working copy, from `git describe` against the last vX.Y.Z tag."""
    try:
        described = _git("describe", "--tags", "--long", "--dirty", "--match", "v[0-9]*")
    except (OSError, subprocess.SubprocessError):
        return f"{__version__}-dev"
    if not described:
        return f"{__version__}-dev"
    dirty = described.endswith("-dirty")
    tag, ahead, commit = described.removesuffix("-dirty").rsplit("-", 2)
    if tag == f"v{__version__}" and ahead == "0" and not dirty:
        return __version__
    return f"{__version__}-dev.{ahead}+{commit.removeprefix('g')}" + (".dirty" if dirty else "")


@lru_cache(maxsize=1)
def _build_info() -> dict:
    try:
        return json.loads((ROOT / "build_info.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@lru_cache(maxsize=1)
def shown() -> str:
    if FROZEN:
        return _build_info().get("version", __version__)
    return from_git()


def number() -> str:
    """The plain version update checks compare: __version__, unless a test
    build was numbered lower on purpose (build.py --as-version)."""
    return _build_info().get("number", __version__) if FROZEN else __version__
