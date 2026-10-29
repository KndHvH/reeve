"""Macro alerts evaluated on the confirmed game state.

Each rule turns the state into a condition, a severity and the values that
explain it. Severities: info (blue, silent), warn (yellow) and critical
(red). An alert becomes active once its condition has held for `persist_s`,
may escalate while it stays active (e.g. a town center idle for longer), and
clears as soon as the condition stops. Every activation and severity change
carries its reason, so the log and the report can show why it fired.

Thresholds: config/rules.json (defaults) merged with the user's overrides
in the user's data folder (see paths.py).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .state import RESOURCES, GameState

SEVERITIES = ("info", "warn", "critical")
_RANK = {s: i for i, s in enumerate(SEVERITIES)}


@dataclass(frozen=True)
class Alert:
    id: str
    severity: str          # "info" | "warn" | "critical"
    text: str
    reason: dict


@dataclass
class Transition:
    kind: str              # "on" | "change" | "off"
    alert: Alert


def load_config() -> dict:
    """Shipped defaults merged with the user's overrides (see paths.py)."""
    from .paths import load_config as _load

    return _load()


def _fmt_clock(s: int | None) -> str:
    if s is None:
        return "--:--"
    h, rem = divmod(s, 3600)
    return f"{h}:{rem // 60:02d}:{rem % 60:02d}" if h else f"{rem // 60:02d}:{rem % 60:02d}"


# --- conditions -------------------------------------------------------------
# Each receives the state, its config and how long (s) the condition has
# already held, and returns None (condition false) or (severity, text, reason).

def _idle_villager(s: GameState, cfg: dict, held: float):
    if s.idle is None or s.idle < cfg["warn_at"]:
        return None
    n = s.idle
    severity = "critical" if n >= cfg["critical_at"] else "warn"
    return severity, f"{n} idle villager{'s' if n != 1 else ''}", {"idle": n}


def _housed(s: GameState, cfg: dict, held: float):
    if s.pop is None or not s.pop_cap or s.pop_cap >= cfg["max_pop"]:
        return None
    ratio = s.pop / s.pop_cap
    if ratio < cfg["warn_ratio"]:
        return None
    reason = {"pop": s.pop, "pop_cap": s.pop_cap, "ratio": round(ratio, 2)}
    if s.pop >= s.pop_cap:
        return "critical", f"Housed ({s.pop}/{s.pop_cap}): build a house", reason
    severity = "critical" if ratio >= cfg["critical_ratio"] else "warn"
    return severity, f"Population {s.pop}/{s.pop_cap}: build a house", reason


def _tc_idle(s: GameState, cfg: dict, held: float):
    if s.producing_villager is not False or s.pop is None or s.pop_cap is None:
        return None
    if s.pop >= s.pop_cap:
        return None  # housed: the housed alert explains it
    on_resources = sum(v or 0 for v in s.villagers.values())
    if on_resources >= cfg.get("max_villagers", 100):
        return None  # enough villagers: no longer making them is a choice
    severity = "critical" if held >= cfg["critical_after_s"] else "warn"
    return severity, "Town center idle: queue a villager", {"pop": s.pop, "pop_cap": s.pop_cap, "idle_s": round(held)}


def _floating(s: GameState, cfg: dict, held: float):
    """One limit per age, I to IV; null (or missing, in a config from before
    Age IV had one) = no limit. Above the current age's limit = info; above
    the next age's = warn; two ages ahead = critical. Until the age is read,
    Age I is assumed."""
    caps = (list(cfg["age_limits"]) + [None] * 4)[:4]
    i = min(s.age or 1, 4) - 1
    limits = [lim for lim in caps[i:i + len(SEVERITIES)] if lim is not None]
    over, level = {}, -1
    for r in RESOURCES:
        v = s.resources.get(r)
        if v is None:
            continue
        exceeded = sum(v > lim for lim in limits)
        if exceeded:
            over[r] = v
            level = max(level, exceeded - 1)
    if not over:
        return None
    text = "Floating " + ", ".join(f"{r} {v}" for r, v in over.items())
    return SEVERITIES[level], text, {"over": over, "limits": limits}


def _build(s: GameState, cfg: dict, held: float, tracker=None):
    """Villagers not where the build's current step puts them: move them from
    a resource with more than the step to one with less, or put more on a
    resource. Checked grace_s game seconds after the step is reached (moving
    villagers takes a moment); at most two instructions, in one card."""
    from .builds import describe, instructions

    if tracker is None or s.clock is None or tracker.reached_at is None or tracker.finished:
        return None
    if s.clock - tracker.reached_at < cfg.get("grace_s", 6):
        return None
    _, step, nxt = tracker.window()
    todo = instructions(step.targets, s.villagers)
    if not todo:
        return None
    if nxt is not None and not instructions(nxt.targets, s.villagers):
        return None     # already placed for the next step, which is just not counted yet
    text = "; ".join(describe(i) for i in todo[:2])
    return "warn", text, {"step": tracker.index + 1, "to": todo[0][-1],
                          "todo": [list(i) for i in todo], "villagers": dict(s.villagers)}


RULES = {
    "housed": _housed,
    "tc_idle": _tc_idle,
    "idle_villager": _idle_villager,
    "floating": _floating,
    "build": _build,
}


@dataclass
class RuleEngine:
    config: dict = field(default_factory=load_config)
    _since: dict[str, float] = field(default_factory=dict)
    active: dict[str, Alert] = field(default_factory=dict)
    build: object = None              # BuildTracker of the active build order, if any
    _build_id: str | None = None

    def _sync_build(self) -> None:
        """Follows the build chosen in the hub; a new choice starts from its first step."""
        from .builds import BuildTracker, load

        bo = self.config.get("build_order") or {}
        want = bo.get("active") if bo.get("show", True) else None
        if want != self._build_id:
            self._build_id = want
            b = load(want)
            self.build = BuildTracker(b) if b else None
        if self.build is not None:
            self.build.end_after_s = bo.get("end_after_s", 30)

    def evaluate(self, s: GameState, wall: float) -> list[Transition]:
        """Updates active alerts; returns what turned on, changed severity or turned off."""
        transitions: list[Transition] = []
        self._sync_build()
        if self.build is not None:
            self.build.update(s)
        for rid, cond in RULES.items():
            cfg = self.config.get(rid, {})
            since = self._since.get(rid)
            held = wall - since if since is not None else 0.0
            if not cfg.get("enabled", True):
                hit = None
            elif rid == "build":
                hit = cond(s, cfg, held, self.build)
            else:
                hit = cond(s, cfg, held)
            if hit is None:
                self._since.pop(rid, None)
                if rid in self.active:
                    transitions.append(Transition("off", self.active.pop(rid)))
                continue
            severity, text, reason = hit
            self._since.setdefault(rid, wall)
            if held < cfg.get("persist_s", 0):
                continue
            alert = Alert(rid, severity, text, reason | {"clock": _fmt_clock(s.clock)})
            prev = self.active.get(rid)
            if prev is None:
                transitions.append(Transition("on", alert))
            elif prev.severity != severity:
                transitions.append(Transition("change", alert))
            self.active[rid] = alert  # text may update (e.g. idle count)
        return transitions

    def alerts(self) -> list[Alert]:
        """Active alerts, most severe first."""
        return sorted(self.active.values(), key=lambda a: -_RANK[a.severity])
