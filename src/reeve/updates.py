"""Checks GitHub for a newer Reeve and installs it.

- `check()` asks the GitHub releases API for the latest release, at most once
  a day (the answer is kept in state.json), unless forced from the hub. It is
  the only network request Reeve makes, and it sends nothing about the user.
- `download()` fetches the installer to the temp folder and verifies its size
  and, when GitHub publishes it, its SHA-256 digest.
- `install()` hands the installer to a command shell that waits for Reeve to
  exit, then runs it silently; the installer closes nothing itself and
  reopens Reeve when done (its /RELAUNCH parameter). Only the packaged app
  installs updates; running from source, the hub links to the release.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from . import __version__
from .checks import load_state, save_state
from .paths import FROZEN

REPO = "KndHvH/reeve"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
CHECK_EVERY_S = 24 * 3600
TIMEOUT_S = 10


@dataclass
class Release:
    version: str
    page: str                 # release page with the notes
    installer: str | None     # download URL of Reeve-<version>-setup.exe
    size: int = 0
    sha256: str | None = None


def parse_version(text: str) -> tuple[int, ...]:
    """'v0.2.1' -> (0, 2, 1); anything unreadable sorts lowest."""
    try:
        return tuple(int(p) for p in text.strip().lstrip("v").split("."))
    except ValueError:
        return (0,)


def newer(release: Release | None, current: str | None = None) -> bool:
    """Is `release` newer than this copy (its build number, see version.number)?"""
    from .version import number

    return release is not None and parse_version(release.version) > parse_version(current or number())


def _from_api(data: dict) -> Release:
    asset = next((a for a in data.get("assets", []) if a["name"].lower().endswith("-setup.exe")), None)
    digest = (asset or {}).get("digest") or ""
    return Release(
        version=data["tag_name"].lstrip("v"),
        page=data["html_url"],
        installer=asset["browser_download_url"] if asset else None,
        size=asset["size"] if asset else 0,
        sha256=digest.split(":", 1)[1] if digest.startswith("sha256:") else None,
    )


def _fetch_latest() -> Release:
    req = urllib.request.Request(LATEST_URL, headers={
        "Accept": "application/vnd.github+json", "User-Agent": f"Reeve/{__version__}"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        return _from_api(json.load(r))


def check(force: bool = False, fetch=_fetch_latest, now: float | None = None) -> Release | None:
    """The latest release, from GitHub or from the last check if it was less
    than a day ago. None when unknown (offline, rate limited...)."""
    now = time.time() if now is None else now
    state = load_state()
    cached = state.get("update") or {}
    if not force and "checked" in cached and now - cached["checked"] < CHECK_EVERY_S:
        return Release(**cached["latest"]) if cached.get("latest") else None
    try:
        latest = fetch()
    except Exception:          # offline or GitHub unavailable: try again next time
        return Release(**cached["latest"]) if cached.get("latest") else None
    state["update"] = {"checked": now, "latest": asdict(latest)}
    try:
        save_state(state)
    except OSError:
        pass
    return latest


def can_install() -> bool:
    """Only the installed app updates itself; from source there is nothing to replace."""
    return FROZEN


def download(release: Release, progress=None) -> Path:
    """The installer in the temp folder, verified; raises ValueError when it
    does not match what GitHub announced."""
    if not release.installer:
        raise ValueError("this release has no installer")
    dst = Path(tempfile.gettempdir()) / f"Reeve-{release.version}-setup.exe"
    req = urllib.request.Request(release.installer, headers={"User-Agent": f"Reeve/{__version__}"})
    h = hashlib.sha256()
    done = 0
    with urllib.request.urlopen(req, timeout=60) as r, open(dst, "wb") as f:
        while chunk := r.read(1 << 16):
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, release.size)
    if release.size and done != release.size:
        dst.unlink(missing_ok=True)
        raise ValueError("download incomplete")
    if release.sha256 and h.hexdigest() != release.sha256:
        dst.unlink(missing_ok=True)
        raise ValueError("download does not match the published checksum")
    return dst


def install(installer: Path) -> None:
    """Runs the installer once Reeve has exited: a command shell waits a few
    seconds (Reeve quits right after calling this), then starts it silently.
    The installer also waits for Reeve's mutex before replacing files."""
    subprocess.Popen(install_command(installer), creationflags=subprocess.CREATE_NO_WINDOW,
                     close_fds=True, cwd=os.environ.get("TEMP", tempfile.gettempdir()))


def install_command(installer: Path) -> str:
    """The command line as one string: given a list, Popen would escape the
    inner quotes as \\" (C runtime rules), which cmd.exe does not understand,
    and `start` would get a broken path. /s makes cmd strip exactly the outer
    pair of quotes and run the rest as written."""
    args = "/SILENT /SUPPRESSMSGBOXES /NORESTART /RELAUNCH=1"
    return f'cmd.exe /s /c "ping -n 4 127.0.0.1 >nul & start "" "{installer}" {args}"'
