"""Alert sounds: each severity plays a sound chosen from a library.

- The library is assets/sounds/library/<name>.wav (import new ones with
  scripts/import_sound.py) plus the user's own sounds, added in the hub
  (reeve.sound_import). config/rules.json ("sound") picks the sound of
  each severity by name; an empty name keeps that severity silent.
- A sound plays when an alert appears and when it escalates. Severities
  listed in `repeat` (warn and critical by default) play again every
  `repeat_s` while the alert stays active; info plays only once, so a
  floating-resources notice does not keep chiming.
- At most one sound per reading: the most severe one due. Alerts of the same
  or lower severity that were also due count as played, so several alerts
  never stack into a burst.
- Playback uses winsound (stdlib) asynchronously: the overlay loop never
  waits for a sound to finish. `volume` (0–1) sets the level on a squared
  curve, closer to how loudness is heard: 0 is silent (nothing plays), 0.5
  plays the files at a quarter of their amplitude (the comfortable default)
  and 1 at full level, 12 dB louder. winsound has no volume control, so
  scaled copies are written once to the temp folder.
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


def _sound_dirs() -> list[Path]:
    from .paths import user_sounds_dir

    return [user_sounds_dir(), LIBRARY]  # the user's own sounds win over built-ins with the same name


def sound_path(name: str) -> Path | None:
    for d in _sound_dirs():
        p = d / f"{name}.wav"
        if p.exists():
            return p
    return None


def library() -> list[str]:
    """Names of the sounds available: built-in library plus the user's own."""
    return sorted({p.stem for d in _sound_dirs() for p in d.glob("*.wav")})


def gain(volume) -> float:
    """Amplitude factor of a volume setting (0–1, squared curve)."""
    return min(1.0, max(0.0, float(volume))) ** 2


def _scaled_copy(src: Path, factor: float) -> Path:
    """16-bit WAV with its amplitude multiplied by `factor`, cached in the temp folder."""
    stamp = int(src.stat().st_mtime)  # a re-imported sound gets a fresh copy
    dst = Path(tempfile.gettempdir()) / "reeve_sounds" / f"{src.stem}_{stamp}_g{factor:.4f}.wav"
    if not dst.exists():
        with wave.open(str(src), "rb") as r:
            params, frames = r.getparams(), r.readframes(r.getnframes())
        pcm = (np.frombuffer(frames, "<i2").astype(np.float32) * factor).astype("<i2")
        dst.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(dst), "wb") as w:
            w.setparams(params)
            w.writeframes(pcm.tobytes())
    return dst


def play_at(path: Path, volume: float, wait: bool = False) -> None:
    """Plays `path` at a volume setting (0–1), like the overlay would; 0 plays nothing."""
    g = gain(volume)
    if g > 0:
        play_file(_scaled_copy(path, g) if g < 1.0 else path, wait)


def play_file(path: Path, wait: bool = False) -> None:
    flags = winsound.SND_FILENAME | winsound.SND_NODEFAULT | (0 if wait else winsound.SND_ASYNC)
    winsound.PlaySound(str(path), flags)


class AlertSounds:
    def __init__(self, cfg: dict, play: Callable[[Path], None] = play_file):
        self.enabled = cfg.get("enabled", True)
        self.repeat_s = cfg.get("repeat_s", 5)
        self.repeat = set(cfg.get("repeat", ["warn", "critical"]))
        g = gain(cfg.get("volume", 0.5))
        self.files: dict[str, Path] = {}   # volume 0: no files, nothing ever plays
        for sev in SEVERITIES:
            name = cfg.get(sev)
            path = sound_path(name) if name else None
            if path is not None and g > 0:
                self.files[sev] = _scaled_copy(path, g) if g < 1.0 else path
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
