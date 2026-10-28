"""Game state built from raw readings, robust to one-off misreads.

A single frame can be wrong while the panel is perfectly visible (a tooltip
sliding over "10/10" produced "10/1"; one clock read came out as 12:31 at
1:23). The tracker therefore:

- confirms slow-changing fields (population, idle, villagers per resource,
  villager production) only after the same value is read twice in a row;
- accepts resources immediately, since they change on almost every read;
  rules add their own persistence on top;
- accepts the clock only when it moves forward by roughly the wall time that
  passed (the game may keep running behind a menu, so larger forward jumps
  are fine if a second read confirms them).
"""

from __future__ import annotations

from dataclasses import dataclass, field

RESOURCES = ("food", "wood", "gold", "stone")
SLOW_FIELDS = ("pop", "idle", "vil_food", "vil_wood", "vil_gold", "vil_stone", "producing_villager")
CONFIRM = 2         # identical consecutive reads needed to accept a slow field
CLOCK_SLACK_S = 3   # tolerance between game-time and wall-time progress


@dataclass
class _Debounced:
    value: object = None
    pending: object = None
    count: int = 0

    def push(self, v) -> None:
        if v is None:
            return
        if v == self.value:
            self.pending, self.count = None, 0
        elif v == self.pending:
            self.count += 1
            if self.count >= CONFIRM:
                self.value, self.pending, self.count = v, None, 0
        else:
            self.pending, self.count = v, 1


@dataclass
class GameState:
    clock: int | None = None            # game seconds
    pop: int | None = None
    pop_cap: int | None = None
    idle: int | None = None
    producing_villager: bool | None = None
    resources: dict[str, int | None] = field(default_factory=lambda: {r: None for r in RESOURCES})
    villagers: dict[str, int | None] = field(default_factory=lambda: {r: None for r in RESOURCES})

    def to_dict(self) -> dict:
        return {
            "clock": self.clock, "pop": self.pop, "pop_cap": self.pop_cap, "idle": self.idle,
            "producing_villager": self.producing_villager,
            "resources": dict(self.resources), "villagers": dict(self.villagers),
        }


class StateTracker:
    def __init__(self):
        self.slow = {f: _Debounced() for f in SLOW_FIELDS}
        self.resources: dict[str, int | None] = {r: None for r in RESOURCES}
        self.clock: int | None = None
        self._clock_wall: float | None = None
        self._clock_pending: tuple[int, float] | None = None

    def update(self, values: dict, wall: float) -> GameState:
        """`values`: Frame.values from the reader; `wall`: monotonic seconds."""
        pop = values.get("pop")
        if pop is not None and pop[0] > pop[1]:
            pop = None  # population can never exceed the cap: misread
        for f in SLOW_FIELDS:
            self.slow[f].push(pop if f == "pop" else values.get(f))
        for r in RESOURCES:
            if values.get(r) is not None:
                self.resources[r] = values[r]
        self._update_clock(values.get("clock"), wall)
        return self.state()

    def _update_clock(self, c: int | None, wall: float) -> None:
        if c is None:
            return
        if self.clock is None:
            self.clock, self._clock_wall = c, wall
            return
        dt_wall = wall - self._clock_wall
        dt_game = c - self.clock
        if 0 <= dt_game <= dt_wall + CLOCK_SLACK_S:
            self.clock, self._clock_wall, self._clock_pending = c, wall, None
            return
        # Implausible jump (misread, or a new match): accept only if the next
        # read continues consistently from it.
        p = self._clock_pending
        if p is not None and 0 <= c - p[0] <= (wall - p[1]) + CLOCK_SLACK_S:
            self.clock, self._clock_wall, self._clock_pending = c, wall, None
        else:
            self._clock_pending = (c, wall)

    def state(self) -> GameState:
        pop = self.slow["pop"].value
        return GameState(
            clock=self.clock,
            pop=pop[0] if pop else None,
            pop_cap=pop[1] if pop else None,
            idle=self.slow["idle"].value,
            producing_villager=self.slow["producing_villager"].value,
            resources=dict(self.resources),
            villagers={r: self.slow[f"vil_{r}"].value for r in RESOURCES},
        )
