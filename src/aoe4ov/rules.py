"""Macro alerts evaluated on the confirmed game state.

Each rule turns the state into a condition plus the values that explain it.
An alert becomes active once its condition has held for `persist_s` and
clears as soon as the condition stops. Every activation carries its reason,
so the log and the report can show why it fired.

Thresholds live in config/rules.json.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .state import RESOURCES, GameState

CONFIG = Path(__file__).resolve().parents[2] / "config" / "rules.json"


@dataclass(frozen=True)
class Alert:
    id: str
    severity: str          # "info" | "warn" | "danger"
    text: str
    reason: dict


@dataclass
class Transition:
    kind: str              # "on" | "off"
    alert: Alert


def load_config(path: Path = CONFIG) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _fmt_clock(s: int | None) -> str:
    if s is None:
        return "--:--"
    h, rem = divmod(s, 3600)
    return f"{h}:{rem // 60:02d}:{rem % 60:02d}" if h else f"{rem // 60:02d}:{rem % 60:02d}"


# --- conditions -------------------------------------------------------------
# Each returns None (condition false) or (severity, text, reason).

def _idle_villager(s: GameState, cfg: dict):
    if s.idle is not None and s.idle >= cfg["min_idle"]:
        n = s.idle
        return "warn", f"{n} idle villager{'s' if n != 1 else ''}", {"idle": n}
    return None


def _housed(s: GameState, cfg: dict):
    if s.pop is None or s.pop_cap is None or s.pop_cap >= cfg["max_pop"]:
        return None
    if s.pop >= s.pop_cap - cfg["margin"]:
        text = "Housed: build a house" if s.pop >= s.pop_cap else f"Almost housed ({s.pop}/{s.pop_cap})"
        return "danger", text, {"pop": s.pop, "pop_cap": s.pop_cap}
    return None


def _tc_idle(s: GameState, cfg: dict):
    if s.producing_villager is not False or s.pop is None or s.pop_cap is None:
        return None
    if s.pop >= s.pop_cap:
        return None  # housed: the housed alert explains it
    return "warn", "Town center idle: queue a villager", {"pop": s.pop, "pop_cap": s.pop_cap}


def _floating(s: GameState, cfg: dict):
    if s.clock is None:
        return None
    limit = next(b["max"] for b in cfg["bands"] if b["until_s"] is None or s.clock < b["until_s"])
    over = {r: v for r in RESOURCES if (v := s.resources.get(r)) is not None and v > limit}
    if not over:
        return None
    text = "Floating " + ", ".join(f"{r} {v}" for r, v in over.items())
    return "info", text, {"over": over, "limit": limit}


RULES = {
    "housed": _housed,
    "tc_idle": _tc_idle,
    "idle_villager": _idle_villager,
    "floating": _floating,
}


@dataclass
class RuleEngine:
    config: dict = field(default_factory=load_config)
    _since: dict[str, float] = field(default_factory=dict)
    active: dict[str, Alert] = field(default_factory=dict)

    def evaluate(self, s: GameState, wall: float) -> list[Transition]:
        """Updates active alerts; returns what turned on or off in this step."""
        transitions: list[Transition] = []
        for rid, cond in RULES.items():
            cfg = self.config.get(rid, {})
            hit = cond(s, cfg) if cfg.get("enabled", True) else None
            if hit is None:
                self._since.pop(rid, None)
                if rid in self.active:
                    transitions.append(Transition("off", self.active.pop(rid)))
                continue
            severity, text, reason = hit
            since = self._since.setdefault(rid, wall)
            if wall - since < cfg.get("persist_s", 0):
                continue
            alert = Alert(rid, severity, text, reason | {"clock": _fmt_clock(s.clock)})
            if rid not in self.active:
                transitions.append(Transition("on", alert))
            self.active[rid] = alert  # text may update (e.g. idle count)
        return transitions

    def alerts(self) -> list[Alert]:
        """Active alerts, most severe first."""
        order = {"danger": 0, "warn": 1, "info": 2}
        return sorted(self.active.values(), key=lambda a: order[a.severity])
