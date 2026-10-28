"""Replays a recorded session through the state tracker and the alert rules.

Rules can be validated and tuned without playing: edit config/rules.json and
replay any sessions/<start>/log.jsonl to see which alerts would fire, when,
and why.
"""

from __future__ import annotations

import json
from pathlib import Path

from .rules import RuleEngine, _fmt_clock, load_config
from .state import StateTracker


def _wall_seconds(row: dict) -> float:
    if "t" in row:
        return float(row["t"])
    h, m, s = (int(x) for x in row["wall"].split(":"))
    return h * 3600 + m * 60 + s


def replay(log_path: Path, config: dict | None = None) -> list[str]:
    """Returns one line per alert transition, plus a summary."""
    tracker, engine = StateTracker(), RuleEngine(config=config or load_config())
    lines, reads, on_count = [], 0, {}
    for raw in log_path.read_text(encoding="utf-8").splitlines():
        row = json.loads(raw)
        if "values" not in row:
            continue
        values = dict(row["values"])
        if isinstance(values.get("pop"), list):
            values["pop"] = tuple(values["pop"])
        wall = _wall_seconds(row)
        state = tracker.update(values, wall)
        reads += 1
        for tr in engine.evaluate(state, wall):
            a = tr.alert
            if tr.kind == "on":
                on_count[a.id] = on_count.get(a.id, 0) + 1
                reason = ", ".join(f"{k}={v}" for k, v in a.reason.items() if k != "clock")
                lines.append(f"{_fmt_clock(state.clock)}  ON   {a.id:14s} {a.text}  ({reason})")
            else:
                lines.append(f"{_fmt_clock(state.clock)}  off  {a.id}")
    summary = ", ".join(f"{k} x{v}" for k, v in sorted(on_count.items())) or "no alerts"
    lines.append(f"{reads} readings replayed; alerts fired: {summary}")
    return lines
