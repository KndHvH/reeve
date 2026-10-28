"""Alert sounds: one per severity, repeated while the alert is unresolved.

- info alerts are silent; warn and critical play their theme's sound.
- A sound plays when an alert appears, when it escalates (warn → critical)
  and again every `repeat_s` while it stays active.
- At most one sound per reading: the most severe one due. Alerts of the same
  or lower severity that were also due count as played, so several alerts
  never stack into a burst.
- Playback uses winsound (stdlib) asynchronously: the overlay loop never
  waits for a sound to finish.

Themes are folders in assets/sounds/<theme>/ with warn.wav and critical.wav.
"""

from __future__ import annotations

import winsound
from pathlib import Path
from typing import Callable

from .anchor import ASSETS
from .rules import Alert

SOUNDS = ASSETS / "sounds"
AUDIBLE = ("warn", "critical")
_RANK = {"warn": 0, "critical": 1}


def play_file(path: Path) -> None:
    winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)


class AlertSounds:
    def __init__(self, cfg: dict, play: Callable[[Path], None] = play_file):
        self.enabled = cfg.get("enabled", True)
        self.repeat_s = cfg.get("repeat_s", 5)
        theme = SOUNDS / cfg.get("theme", "default")
        self.files = {s: theme / f"{s}.wav" for s in AUDIBLE}
        self.play = play
        self._last: dict[str, tuple[str, float]] = {}  # alert id -> (severity, time played)

    def update(self, alerts: list[Alert], now: float) -> str | None:
        """Plays what is due for the active alerts; returns the severity played, if any."""
        audible = {a.id: a.severity for a in alerts if a.severity in AUDIBLE}
        self._last = {k: v for k, v in self._last.items() if k in audible}
        due = []
        for aid, sev in audible.items():
            prev = self._last.get(aid)
            if prev is None or _RANK[sev] > _RANK[prev[0]] or now - prev[1] >= self.repeat_s:
                due.append((aid, sev))
        if not due:
            return None
        top = max(_RANK[sev] for _, sev in due)
        for aid, sev in due:
            self._last[aid] = (sev, now)
        severity = AUDIBLE[top]
        if self.enabled:
            self.play(self.files[severity])
        return severity
