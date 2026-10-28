"""Alert sounds: each severity plays a sound chosen from a library.

- The library is assets/sounds/library/<name>.wav (import new ones with
  scripts/import_sound.py). config/rules.json ("sound") picks the sound of
  each severity by name; an empty name keeps that severity silent.
- A sound plays when an alert appears and when it escalates. Severities
  listed in `repeat` (warn and critical by default) play again every
  `repeat_s` while the alert stays active; info plays only once, so a
  floating-resources notice does not keep chiming.
- At most one sound per reading: the most severe one due. Alerts of the same
  or lower severity that were also due count as played, so several alerts
  never stack into a burst.
- Playback uses winsound (stdlib) asynchronously: the overlay loop never
  waits for a sound to finish. `volume` (0–1) scales the files; winsound has
  no volume control, so scaled copies are written once to the temp folder.
"""

from __future__ import annotations

import tempfile
import wave
import winsound
from pathlib import Path
from typing import Callable

import numpy as np

from .anchor import ASSETS
from .rules import SEVERITIES, Alert

LIBRARY = ASSETS / "sounds" / "library"
_RANK = {s: i for i, s in enumerate(SEVERITIES)}


def library() -> list[str]:
    """Names of the sounds available in the library."""
    return sorted(p.stem for p in LIBRARY.glob("*.wav"))


def _scaled_copy(src: Path, volume: float) -> Path:
    """16-bit WAV scaled by `volume`, cached in the temp folder."""
    stamp = int(src.stat().st_mtime)  # a re-imported sound gets a fresh copy
    dst = Path(tempfile.gettempdir()) / "aoe4ov_sounds" / f"{src.stem}_{stamp}_{volume:.2f}.wav"
    if not dst.exists():
        with wave.open(str(src), "rb") as r:
            params, frames = r.getparams(), r.readframes(r.getnframes())
        pcm = (np.frombuffer(frames, "<i2").astype(np.float32) * volume).astype("<i2")
        dst.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(dst), "wb") as w:
            w.setparams(params)
            w.writeframes(pcm.tobytes())
    return dst


def play_file(path: Path, wait: bool = False) -> None:
    flags = winsound.SND_FILENAME | winsound.SND_NODEFAULT | (0 if wait else winsound.SND_ASYNC)
    winsound.PlaySound(str(path), flags)


class AlertSounds:
    def __init__(self, cfg: dict, play: Callable[[Path], None] = play_file):
        self.enabled = cfg.get("enabled", True)
        self.repeat_s = cfg.get("repeat_s", 5)
        self.repeat = set(cfg.get("repeat", ["warn", "critical"]))
        volume = min(1.0, max(0.0, float(cfg.get("volume", 1.0))))
        self.files: dict[str, Path] = {}
        for sev in SEVERITIES:
            name = cfg.get(sev)
            path = LIBRARY / f"{name}.wav" if name else None
            if path is not None and path.exists():
                self.files[sev] = _scaled_copy(path, volume) if volume < 1.0 else path
        self.play = play
        self._last: dict[str, tuple[str, float]] = {}  # alert id -> (severity, time played)

    def update(self, alerts: list[Alert], now: float) -> str | None:
        """Plays what is due for the active alerts; returns the severity played, if any."""
        audible = {a.id: a.severity for a in alerts if a.severity in self.files}
        self._last = {k: v for k, v in self._last.items() if k in audible}
        due = []
        for aid, sev in audible.items():
            prev = self._last.get(aid)
            new_or_escalated = prev is None or _RANK[sev] > _RANK[prev[0]]
            if new_or_escalated or (sev in self.repeat and now - prev[1] >= self.repeat_s):
                due.append((aid, sev))
        if not due:
            return None
        severity = max((sev for _, sev in due), key=_RANK.get)
        for aid, sev in due:
            self._last[aid] = (sev, now)
        if self.enabled:
            self.play(self.files[severity])
        return severity
