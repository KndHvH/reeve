"""Session retention: keeps the data folder from growing without limit.

A recorded match is mostly images: audit frames every 10 s of game time and
the doubt/fail crops the reader saves for diagnosis. Policy (config section
`retention`):

- younger than `full_days`: kept whole;
- up to `keep_days`: made light, keeping only log.jsonl, report.html and
  summary.json (the report is rewritten so it no longer points at deleted
  frames). Top-center frames stay when the log has no age readings, since the
  report recovers the ages from them (matches recorded before age detection);
- older than `keep_days`: deleted;
- above `max_mb` in total: the oldest matches are made light first, then
  deleted, until the folder fits.

Runs once in the background when the app starts. A session whose log was
written in the last few minutes is left alone: it may be the match being
recorded. `reeve clean --dry-run` shows the plan.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .paths import load_config, sessions_dir

KEEP = {"log.jsonl", "report.html", "summary.json"}
DAY = 86400
RECORDING_S = 600   # a log written this recently may be a match being recorded: never touched


@dataclass
class Plan:
    light: list[Path] = field(default_factory=list)
    delete: list[Path] = field(default_factory=list)
    freed: int = 0          # bytes
    before: int = 0
    after: int = 0


def started(session: Path) -> float:
    """Start time from the folder name (YYYYmmdd-HHMMSS), else its mtime."""
    try:
        return datetime.strptime(session.name, "%Y%m%d-%H%M%S").timestamp()
    except ValueError:
        return session.stat().st_mtime


def _size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _recording(session: Path) -> bool:
    log = session / "log.jsonl"
    return log.exists() and time.time() - log.stat().st_mtime < RECORDING_S


def _has_ages(session: Path) -> bool:
    log = session / "log.jsonl"
    return log.exists() and '"age"' in log.read_text(encoding="utf-8", errors="ignore")


def heavy_files(session: Path) -> list[Path]:
    """What making a session light removes."""
    keep_top = not _has_ages(session)
    out = []
    for f in session.rglob("*"):
        if not f.is_file() or f.parent == session and f.name in KEEP:
            continue
        if keep_top and f.parent.name == "frames" and f.name.startswith("top_"):
            continue
        out.append(f)
    return out


def plan(cfg: dict | None = None, now: float | None = None) -> Plan:
    cfg = (cfg or load_config()).get("retention", {})
    p = Plan()
    if not cfg.get("enabled", True):
        return p
    now = time.time() if now is None else now
    sessions = sorted((s for s in sessions_dir().iterdir() if s.is_dir() and not _recording(s)), key=started)  # oldest first
    sizes = {s: _size(s) for s in sessions}
    heavy = {s: sum(f.stat().st_size for f in heavy_files(s)) for s in sessions}
    p.before = total = sum(sizes.values())

    for s in sessions:
        age_days = (now - started(s)) / DAY
        if age_days > cfg.get("keep_days", 90):
            p.delete.append(s)
            total -= sizes[s]
        elif age_days > cfg.get("full_days", 7) and heavy[s]:
            p.light.append(s)
            total -= heavy[s]

    cap = cfg.get("max_mb", 500) * 1024 * 1024
    for s in sessions:                       # over the cap: lighten the oldest first
        if total <= cap:
            break
        if s not in p.delete and s not in p.light and heavy[s]:
            p.light.append(s)
            total -= heavy[s]
    for s in sessions[:-1]:                  # still over: delete the oldest, never the newest
        if total <= cap:
            break
        if s not in p.delete:
            if s in p.light:
                p.light.remove(s)
                total -= sizes[s] - heavy[s]
            else:
                total -= sizes[s]
            p.delete.append(s)

    p.after = total
    p.freed = p.before - total
    return p


def apply(cfg: dict | None = None, now: float | None = None) -> Plan:
    """Carries out the plan. A failure on one session never stops the rest."""
    from .report import write_report

    p = plan(cfg, now)
    for s in p.delete:
        shutil.rmtree(s, ignore_errors=True)
    for s in p.light:
        for f in heavy_files(s):
            f.unlink(missing_ok=True)
        for d in sorted((d for d in s.rglob("*") if d.is_dir()), reverse=True):
            if not any(d.iterdir()):
                d.rmdir()
        if (s / "report.html").exists():
            try:
                write_report(s)       # drop the links to the deleted frames
            except Exception:
                pass
    return p


def describe(p: Plan) -> str:
    mb = lambda b: f"{b / 1024 / 1024:.1f} MB"
    lines = [f"{len(p.light)} match(es) made light, {len(p.delete)} deleted: "
             f"{mb(p.before)} -> {mb(p.after)} ({mb(p.freed)} freed)"]
    lines += [f"  light   {s.name}" for s in p.light]
    lines += [f"  delete  {s.name}" for s in p.delete]
    return "\n".join(lines)
