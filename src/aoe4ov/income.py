"""Resource income estimated from the stockpile.

The game shows stockpiles, not income. A stockpile rises when villagers drop
resources off and falls when the player spends, so income is estimated as
the sum of the *increases* over a window of game time (default 60 s), scaled
to per minute:

- spending is ignored; a drop-off and a purchase within the same reading
  partly cancel, so the estimate leans slightly low;
- market sales, relics and tributes count as income, which they are;
- each resource series goes through a median-of-3 filter first, so a single
  misread (e.g. 1050 read as 105 for one frame) cannot add a fake +945;
- per-villager income divides by the mean villagers on that resource in the
  window: it drops when drop-off points are far, which can drive alerts later.

Cost: a few additions per reading.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .state import RESOURCES, GameState

WINDOW_S = 60


@dataclass(frozen=True)
class Income:
    per_min: dict[str, float | None]          # resource -> income per minute
    per_villager: dict[str, float | None]     # resource -> income per villager per minute

    def to_dict(self) -> dict:
        r = lambda v: None if v is None else round(v, 1)
        return {"per_min": {k: r(v) for k, v in self.per_min.items()},
                "per_villager": {k: r(v) for k, v in self.per_villager.items()}}


class IncomeTracker:
    def __init__(self, window_s: float = WINDOW_S):
        self.window_s = window_s
        self._raw = {r: deque(maxlen=3) for r in RESOURCES}
        self._last = {r: None for r in RESOURCES}
        # (game second, gained amount, villagers on it) per resource
        self._events = {r: deque() for r in RESOURCES}
        self._start: int | None = None

    def update(self, s: GameState) -> Income:
        if s.clock is None:
            return self.current(None)
        if self._start is None:
            self._start = s.clock
        for r in RESOURCES:
            v = s.resources.get(r)
            if v is None:
                continue
            self._raw[r].append(v)
            filtered = sorted(self._raw[r])[len(self._raw[r]) // 2]
            prev = self._last[r]
            self._last[r] = filtered
            gain = max(0, filtered - prev) if prev is not None else 0
            self._events[r].append((s.clock, gain, s.villagers.get(r)))
        return self.current(s.clock)

    def current(self, clock: int | None) -> Income:
        per_min, per_vil = {}, {}
        for r in RESOURCES:
            ev = self._events[r]
            if clock is not None:
                while ev and ev[0][0] <= clock - self.window_s:
                    ev.popleft()
            span = min(self.window_s, clock - self._start) if clock is not None and self._start is not None else 0
            if span < 10 or not ev:  # too little time for a meaningful rate
                per_min[r] = per_vil[r] = None
                continue
            rate = sum(g for _, g, _ in ev) / span * 60
            vils = [v for _, _, v in ev if v is not None]
            mean_v = sum(vils) / len(vils) if vils else 0
            per_min[r] = rate
            per_vil[r] = rate / mean_v if mean_v >= 1 else None
        return Income(per_min, per_vil)
