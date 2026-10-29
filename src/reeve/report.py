"""Post-match report: sessions/<start>/report.html.

The report replays the session log through the same state tracker, alert
rules and income tracker the overlay uses, so its numbers always match what
was shown live. It is a single self-contained HTML file (inline SVG + a
little JavaScript, no network): a summary ledger (overview, time with
problems, average income), charts over game time for villagers per resource,
income per minute, stockpiles and population, and the alert timeline.
Hovering a chart moves a shared cursor; clicking pins it and shows the values
read at that moment next to the audit frame (the panel crop saved every 10 s
of game time).

Visual language follows the game's UI: night-blue panels, gold rules and
frames, a classic serif for headings, the game's own resource icons.
"""

from __future__ import annotations

import base64
import html
import json
from pathlib import Path

from . import themes
from .income import IncomeTracker
from .paths import ROOT
from .replay import _wall_seconds
from .rules import SEVERITIES, RuleEngine, _fmt_clock, load_config
from .state import RESOURCES, StateTracker

# Resource colors follow the game: food red, wood brown, gold yellow, stone
# gray; idle villagers blue. Chosen by the user over a fully colorblind-safe
# set: normal vision separates every pair (worst ΔE 16), but red and brown are
# close for protan vision (ΔE 5.6), so identity never relies on color alone:
# the game's icons mark every legend and line end, and stacked bands are
# separated by gaps.
SERIES_ORDER = ["food", "wood", "stone", "gold", "idle"]
ICONS = ROOT / "assets" / "report_icons"
PROBLEMS = [("tc_idle", "Town center idle"), ("housed", "Housed"),
            ("idle_villager", "Idle villagers"), ("floating", "Floating resources")]
BUILD_PROBLEM = ("build", "Off the build")   # only for matches that followed a build order


def _icons() -> dict[str, str]:
    return {p.stem: "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()
            for p in sorted(ICONS.glob("*.png"))}


def _ages_from_frames(session: Path, scale: float) -> dict[int, object]:
    """Age readings from the saved top-center frames (game second -> AgeReading),
    for sessions logged before age detection existed."""
    import numpy as np
    from PIL import Image

    from .age import read_age
    from .anchor import AnchorMatch

    out = {}
    match = AnchorMatch(0, 0, scale, 1.0)
    for f in sorted((session / "frames").glob("top_*.jpg")):
        crop = np.asarray(Image.open(f).convert("RGB"))
        width = 2 * crop.shape[1]  # any width works: the crop is placed where the capture took it
        x0, y0 = round(width / 2 - 75 * scale), round(12 * scale)
        canvas = np.zeros((y0 + crop.shape[0], width, 3), np.uint8)
        canvas[y0:y0 + crop.shape[0], x0:x0 + crop.shape[1]] = crop
        out[int(f.stem[4:])] = read_age(canvas, match, width)
    return out


def build_timeline(log_path: Path, config: dict | None = None) -> dict:
    """One row per reading (game time), plus alert intervals and frames.

    Logs written before age detection have no age values; if the session kept
    top-center frames, the age is read from them and applied to the readings
    within a few seconds of each frame."""
    import bisect

    lines = [json.loads(raw) for raw in log_path.read_text(encoding="utf-8").splitlines()]
    # The build order the match followed (logged as it advanced), not the one in use now.
    step = next((r for r in lines if r.get("event") == "build_step"), None)
    build = {"id": step["build"], "name": step.get("name", ""), "civ": step.get("civ")} if step else None
    if build and build["civ"] is None:   # logged before the civilization was: the stored build's
        from .builds import load

        stored = load(build["id"])
        build["civ"] = stored.civ if stored else ""
    config = dict(config or load_config())
    config["build_order"] = dict(config.get("build_order") or {}, active=build and build["id"], show=True)
    tracker, engine, income = StateTracker(), RuleEngine(config=config), IncomeTracker()
    rows, intervals, open_alerts = [], [], {}
    readings = [r for r in lines if "values" in r]
    backfill, keys = {}, []
    if readings and not any("age" in r["values"] for r in readings):
        scale = next((r["anchor"][2] for r in readings if r.get("anchor")), None)
        if scale:
            backfill = _ages_from_frames(log_path.parent, scale)
            keys = sorted(backfill)
    for row in readings:
        values = dict(row["values"])
        if isinstance(values.get("pop"), list):
            values["pop"] = tuple(values["pop"])
        if keys and values.get("clock") is not None:
            i = bisect.bisect_right(keys, values["clock"]) - 1
            if i >= 0 and values["clock"] - keys[i] <= 3:
                a = backfill[keys[i]]
                values.update(age=a.age, ageup_progress=a.progress, ageup_builders=a.builders)
        wall = _wall_seconds(row)
        s = tracker.update(values, wall)
        if s.clock is None:
            continue
        for tr in engine.evaluate(s, wall):
            a = tr.alert
            if tr.kind in ("on", "change"):
                if a.id in open_alerts:
                    intervals.append(open_alerts.pop(a.id) | {"end": s.clock})
                open_alerts[a.id] = {"id": a.id, "severity": a.severity, "text": a.text, "start": s.clock}
            elif a.id in open_alerts:
                intervals.append(open_alerts.pop(a.id) | {"end": s.clock})
        inc = income.update(s)
        rows.append({
            "t": s.clock,
            "pop": s.pop, "cap": s.pop_cap, "idle": s.idle,
            "producing": s.producing_villager,
            "age": s.age, "up": None if s.ageup_progress is None else round(s.ageup_progress, 2), "upb": s.ageup_builders,
            "res": dict(s.resources), "vil": dict(s.villagers),
            "inc": {k: None if v is None else round(v) for k, v in inc.per_min.items()},
            "incv": {k: None if v is None else round(v, 1) for k, v in inc.per_villager.items()},
        })
    end = rows[-1]["t"] if rows else 0
    intervals += [a | {"end": end} for a in open_alerts.values()]
    frames = sorted(int(p.stem) for p in (log_path.parent / "frames").glob("[0-9]*.jpg"))
    return {"rows": rows, "alerts": intervals, "frames": frames, "ages": age_events(rows), "build": build}


def age_events(rows: list[dict]) -> list[dict]:
    """When each age was reached, when its landmark started, and how many
    villagers built it (the most common reading during the age-up, so one
    misread digit does not inflate it)."""
    from collections import Counter

    events, prev, start, builders = [], None, None, Counter()
    for r in rows:
        if r.get("up") is not None:
            start = r["t"] if start is None else start
            if r.get("upb"):
                builders[r["upb"]] += 1
        a = r.get("age")
        if a is not None and a != prev:
            if prev is not None:
                events.append({"age": a, "reached": r["t"], "started": start,
                               "builders": builders.most_common(1)[0][0] if builders else None})
            prev, start, builders = a, None, Counter()
    return events


def summarize(tl: dict) -> dict:
    """Summary ledger: overview, time with each problem (and its worst
    severity), average income per resource."""
    rows, alerts = tl["rows"], tl["alerts"]
    if not rows:
        return {}

    def villagers_at(minute):
        r = next((r for r in rows if r["t"] >= minute * 60), None)
        if r is None:
            return None
        return sum(v for v in r["vil"].values() if v is not None) + (r["idle"] or 0)

    problems = []
    for aid, label in PROBLEMS + ([BUILD_PROBLEM] if tl.get("build") else []):
        spans = [a for a in alerts if a["id"] == aid]
        worst = max((a["severity"] for a in spans), key=SEVERITIES.index, default=None)
        problems.append({"id": aid, "label": label, "seconds": sum(a["end"] - a["start"] for a in spans),
                         "severity": worst})

    income = {}
    for r in RESOURCES:
        vals = [row["inc"][r] for row in rows if row["inc"][r] is not None]
        income[r] = round(sum(vals) / len(vals)) if vals else None

    return {
        "duration": rows[-1]["t"] - rows[0]["t"],
        "span": (rows[0]["t"], rows[-1]["t"]),
        "villagers_at": {m: villagers_at(m) for m in (5, 10, 15)},
        "peak_idle": max((r["idle"] or 0) for r in rows),
        "final_pop": next(((r["pop"], r["cap"]) for r in reversed(rows) if r["cap"]), (None, None)),
        "ages": tl.get("ages", []),
        "problems": problems,
        "income": income,
    }


def _ledger(s: dict, icons: dict[str, str]) -> str:
    if not s:
        return "<p class='empty'>No readings were recorded in this session.</p>"
    e = html.escape
    vil = "".join(
        f"<div class='mini'><b>{'–' if n is None else n}</b><span>{m} min</span></div>"
        for m, n in s["villagers_at"].items())
    pop, cap = s["final_pop"]
    overview = f"""
      <section class='col'>
        <h2>Overview</h2>
        <div class='hero'><b>{_fmt_clock(s['duration'])}</b><span>played, from {_fmt_clock(s['span'][0])} to {_fmt_clock(s['span'][1])}</span></div>
        <div class='minis'><img src='{icons.get("villager", "")}' alt='villagers' title='Villagers at 5, 10 and 15 minutes'>{vil}</div>
        <div class='pair'><span>Peak idle villagers</span><b>{s['peak_idle']}</b></div>
        <div class='pair'><span>Final population</span><b>{'–' if pop is None else f'{pop}/{cap}'}</b></div>
        {_ages_html(s['ages'])}
      </section>"""
    rows = "".join(
        f"<div class='problem {p['severity'] or 'none'}'><i></i><span>{e(p['label'])}</span>"
        f"<b>{_fmt_clock(p['seconds']) if p['seconds'] else 'none'}</b></div>"
        for p in s["problems"])
    problems = f"""
      <section class='col'>
        <h2>Total time with alerts</h2>
        {rows}
        <p class='note'>Bar color is the worst level the alert reached.</p>
      </section>"""
    inc = "".join(
        f"<div class='income'><img src='{icons.get(r, '')}' alt='{r}' title='{r}'>"
        f"<b>{'–' if v is None else v}</b><span>/min</span></div>"
        for r, v in s["income"].items())
    income = f"""
      <section class='col'>
        <h2>Average income</h2>
        {inc}
      </section>"""
    return overview + problems + income


ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV"}


def _ages_html(ages: list[dict]) -> str:
    if not ages:
        return ""
    items = ""
    for e in ages:
        detail = [f"started {_fmt_clock(e['started'])}"] if e["started"] is not None else []
        if e["builders"]:
            detail.append(f"{e['builders']} builders")
        items += (f"<div class='age'><span class='roman'>{ROMAN[e['age']]}</span><b>{_fmt_clock(e['reached'])}</b>"
                  f"<span>{', '.join(detail)}</span></div>")
    return f"<div class='ages' title='Age reached, when its landmark started and how many villagers built it'>{items}</div>"


def write_report(session: Path) -> Path:
    """Writes report.html and summary.json (the small digest the hub lists)."""
    tl = build_timeline(session / "log.jsonl")
    out = session / "report.html"
    out.write_text(render(tl, session.name), encoding="utf-8")
    write_summary(session, tl)
    return out


def write_summary(session: Path, tl: dict | None = None) -> dict:
    tl = tl or build_timeline(session / "log.jsonl")
    s = summarize(tl)
    digest = {
        "session": session.name,
        "started": _session_label(session.name),
        "duration": s.get("duration"),
        "villagers_at": s.get("villagers_at", {}),
        "final_pop": list(s.get("final_pop", (None, None))),
        "ages": s.get("ages", []),
        "civ": (tl.get("build") or {}).get("civ") or None,   # the followed build's; None without one
        "build": (tl.get("build") or {}).get("name") or None,
        "problems": {p["id"]: {"seconds": p["seconds"], "severity": p["severity"]} for p in s.get("problems", [])},
        "income": s.get("income", {}),
    }
    (session / "summary.json").write_text(json.dumps(digest, ensure_ascii=False), encoding="utf-8")
    return digest


def _session_label(name: str) -> str:
    """'20261028-180649' -> '28 Oct 2026, 18:06'."""
    try:
        from datetime import datetime

        return datetime.strptime(name, "%Y%m%d-%H%M%S").strftime("%d %b %Y, %H:%M")
    except ValueError:
        return name


def look(config: dict | None = None) -> str:
    """Theme and corner style the report is drawn with, e.g. "age/square"."""
    return f"{themes.current(config)[0]}/{themes.corners(config)}"


def _civ_html(build: dict | None) -> str:
    """The civilization played (the followed build's) with its flag; empty without a build."""
    from .catalog import find, flag_file

    civ = find((build or {}).get("civ"))
    if civ is None:
        return ""
    f = flag_file(civ["abbr"])
    flag = f"<img src='data:image/png;base64,{base64.b64encode(f.read_bytes()).decode()}' alt=''>" if f else ""
    return (f"<p class='civ'>{flag}<b>{html.escape(civ['name'])}</b>"
            f"<span>following {html.escape(build.get('name') or 'a build order')}</span></p>")


def render(tl: dict, title: str) -> str:
    icons = _icons()
    name, theme = themes.current()
    corner = themes.corners()
    return (TEMPLATE
            .replace("__LOOK__", f"{name}/{corner}")
            .replace("__THEME__", themes.css(theme, corner))
            .replace("__TITLE__", html.escape(_session_label(title)))
            .replace("__CIV__", _civ_html(tl.get("build")))
            .replace("__LEDGER__", _ledger(summarize(tl), icons))
            .replace("__SERIES__", json.dumps(SERIES_ORDER))
            .replace("__ICONS__", json.dumps(icons))
            .replace("__DATA__", json.dumps(tl, separators=(",", ":"))))


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Match report</title>
<meta name="reeve-look" content="__LOOK__">
<style>
:root {
  color-scheme: dark;
  --night: #0e1319; --panel: #151c25; --panel-2: #1a2330; --rule: #263140;
  --accent: #c9a45c; --accent-dim: #6b5734; --accent-light: #ead39a;
  --ink: #ece4d0; --ink-2: #c4bfb2; --mist: #98a0a8;
  --series-food: #e5484d; --series-wood: #93582a; --series-stone: #9fa3a8; --series-gold: #efc12e; --series-idle: #4f86d9;
  --info: #7fb2c9; --warn: #f0b429; --critical: #e5484d;
  --serif: "Palatino Linotype", "Book Antiqua", Palatino, Georgia, serif;
  --sans: "Segoe UI", system-ui, sans-serif;
  --radius: 3px; --radius-sm: 2px;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--night); color: var(--ink); font: 14px/1.5 var(--sans); }
.page { max-width: 1200px; margin: 0 auto; padding: 28px 16px 56px; }
header { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 8px;
  border-bottom: 1px solid var(--accent-dim); padding-bottom: 10px; margin-bottom: 20px; }
h1 { font: 600 30px/1.1 var(--serif); color: var(--accent-light); margin: 0; letter-spacing: .3px; }
header p { margin: 0; color: var(--mist); }
header .title { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 16px; }
.civ { display: flex; align-items: center; gap: 8px; }
.civ img { height: 20px; border-radius: var(--radius-sm); box-shadow: 0 0 0 1px var(--accent-dim); }
.civ b { color: var(--ink); font: 600 16px var(--serif); }
.civ span { font-size: 13px; }
h2 { font: 600 17px/1.2 var(--serif); color: var(--accent); margin: 0 0 12px; }

/* Summary ledger: the one framed element, like the game's gold panels. */
.ledger { display: grid; grid-template-columns: 1.15fr 1fr 0.9fr; background: var(--panel);
  border: 1px solid var(--accent); outline: 1px solid var(--accent-dim); outline-offset: 3px; border-radius: var(--radius); margin: 4px 4px 28px; }
.col { padding: 18px 20px; }
.col + .col { border-left: 1px solid var(--accent-dim); }
.hero b { font: 600 34px/1 var(--serif); color: var(--ink); font-variant-numeric: tabular-nums; }
.hero span { display: block; color: var(--mist); margin-top: 4px; }
.minis { display: flex; align-items: center; gap: 18px; margin-top: 16px; }
.minis img { width: 16px; height: 28px; object-fit: contain; }
.mini b { font: 600 22px/1 var(--serif); font-variant-numeric: tabular-nums; }
.mini span { display: block; color: var(--mist); font-size: 12px; }
.pair { display: flex; justify-content: space-between; padding-top: 8px; margin-top: 8px; border-top: 1px solid var(--rule); }
.pair span { color: var(--ink-2); } .pair b { font-variant-numeric: tabular-nums; }
.problem { display: grid; grid-template-columns: 4px 1fr auto; align-items: center; gap: 10px; padding: 7px 0; border-bottom: 1px solid var(--rule); }
.problem i { height: 20px; border-radius: var(--radius-sm); background: var(--rule); }
.problem.info i { background: var(--info); } .problem.warn i { background: var(--warn); } .problem.critical i { background: var(--critical); }
.problem b { font-variant-numeric: tabular-nums; } .problem.none b { color: var(--mist); font-weight: 400; }
.note { color: var(--mist); font-size: 12px; margin: 10px 0 0; }
.ages { display: flex; flex-wrap: wrap; gap: 6px 18px; margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--rule); }
.age { display: grid; grid-template-columns: auto auto; column-gap: 8px; align-items: baseline; }
.age .roman { font: 600 18px/1 var(--serif); color: var(--accent); grid-row: span 2; min-width: 1.3em; }
.age b { font-variant-numeric: tabular-nums; } .age span:last-child { color: var(--mist); font-size: 12px; grid-column: 2; }
.m-age { font: 600 18px/1 var(--serif); color: var(--accent); margin-left: 12px; letter-spacing: .5px; }
.income { display: grid; grid-template-columns: 26px auto 1fr; align-items: center; gap: 10px; padding: 6px 0; }
.income img { width: 24px; height: 24px; object-fit: contain; }
.income b { font: 600 20px/1 var(--serif); font-variant-numeric: tabular-nums; } .income span { color: var(--mist); font-size: 12px; }
.empty { color: var(--mist); padding: 18px 20px; margin: 0; }
@media (max-width: 900px) { .ledger { grid-template-columns: 1fr; } .col + .col { border-left: 0; border-top: 1px solid var(--accent-dim); } }

.layout { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 18px; align-items: start; }
@media (max-width: 900px) { .layout { grid-template-columns: 1fr; } }
.chart { background: var(--panel); border: 1px solid var(--rule); border-radius: var(--radius); padding: 14px 14px 8px; margin-bottom: 14px; }
.chart header { border: 0; padding: 0; margin: 0 0 6px; }
.legend { display: flex; gap: 12px; }
.legend span { display: inline-flex; align-items: center; gap: 4px; }
.legend button { display: inline-flex; align-items: center; gap: 4px; background: none; border: 1px solid transparent;
  border-radius: var(--radius); padding: 2px 5px; cursor: pointer; }
.legend button:hover { border-color: var(--accent-dim); }
.legend button:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
.legend button.off { filter: grayscale(1); opacity: .35; }
.legend i { width: 10px; height: 10px; border-radius: var(--radius-sm); } .legend img { width: 18px; height: 18px; object-fit: contain; }
svg { display: block; width: 100%; height: auto; overflow: visible; }
svg text { fill: var(--mist); font: 11px var(--sans); }

/* Moment card */
.side { position: sticky; top: 12px; background: var(--panel); border: 1px solid var(--accent); border-radius: var(--radius); padding: 14px; }
.m-head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 12px; }
.m-clock { font: 600 30px/1 var(--serif); color: var(--accent-light); font-variant-numeric: tabular-nums; }
.m-pin { font-size: 12px; color: var(--accent); }
.m-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
.chip { display: inline-flex; align-items: center; gap: 6px; background: var(--panel-2); border: 1px solid var(--rule);
  border-radius: var(--radius); padding: 4px 8px; font-size: 13px; font-variant-numeric: tabular-nums; }
.chip img { width: 18px; height: 18px; object-fit: contain; }
.chip.warn { border-color: var(--warn); box-shadow: inset 0 0 0 1px var(--warn); }
.chip.critical { border-color: var(--critical); box-shadow: inset 0 0 0 1px var(--critical); }
.chip.quiet { color: var(--mist); }
.chip sup { font-size: 9px; color: var(--mist); margin-left: -5px; }
.res { display: grid; grid-template-columns: 22px 1fr auto auto; align-items: center; gap: 8px; padding: 8px 0;
  border-top: 1px solid var(--rule); font-variant-numeric: tabular-nums; }
.res img { width: 20px; height: 20px; object-fit: contain; }
.res b { font: 600 18px/1 var(--serif); }
.res .vil { display: inline-flex; align-items: center; gap: 2px; color: var(--ink-2); font-size: 13px; }
.res .vil img { width: 12px; height: 16px; }
.res .inc { color: var(--mist); font-size: 12px; min-width: 64px; text-align: right; }
.m-alerts { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
.pill { font-size: 12px; border-radius: var(--radius); padding: 2px 8px; font-weight: 600; color: #121212; }
.pill.info { background: var(--info); } .pill.warn { background: var(--warn); } .pill.critical { background: var(--critical); color: #fff; }
.calm { color: var(--mist); font-size: 13px; }
.frame { width: 100%; border-radius: var(--radius); margin-top: 12px; border: 1px solid var(--rule); display: block; }
.frame[hidden] { display: none; }
.hint { color: var(--mist); font-size: 12px; margin-top: 8px; }
</style>
<style>:root { __THEME__ }</style>
</head>
<body>
<div class="page">
<header>
  <div class="title"><h1>Match report</h1>__CIV__</div>
  <p>__TITLE__, game time shown throughout</p>
</header>
<div class="ledger">__LEDGER__</div>
<div class="layout">
  <div id="charts"></div>
  <aside class="side">
    <div id="moment"></div>
    <img id="sel-frame" class="frame" alt="Panel as read at this moment" hidden>
    <div class="hint" id="sel-frame-note"></div>
    <div class="hint" id="sel-hint">Hover a chart to inspect a moment; click to pin it.</div>
  </aside>
</div>
</div>
<script>
const D = __DATA__;
const ORDER = __SERIES__;
const ICON = __ICONS__;
const RES = ["food", "wood", "stone", "gold"];
const color = k => `var(--series-${k})`;
const iconOf = k => k === "idle" ? "villager" : k;
const img = name => ICON[name] ? `<img src="${ICON[name]}" alt="${name}">` : "";
const fmt = s => s == null ? "–" : `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
const rows = D.rows;
const t0 = rows.length ? rows[0].t : 0, t1 = rows.length ? rows[rows.length - 1].t : 1;
const W = 820, PAD = { l: 92, r: 40, t: 8, b: 22 };
const x = t => PAD.l + (t - t0) / Math.max(1, t1 - t0) * (W - PAD.l - PAD.r);
const NS = "http://www.w3.org/2000/svg";
const el = (tag, attrs, parent) => { const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; };
const charts = [];
let pinned = null, lastT = null;
const cursors = () => charts.map(c => c.cursor).filter(Boolean);

// Axis maximum = 4 ticks of a round step (1, 1.5, 2, 2.5, 3, 4, 5, 6 or 8 × 10^k), so the
// labels read 300 / 600 / 900 / 1200 instead of 18 / 35 / 53 / 70.
function niceMax(v) {
  if (v <= 0) return 4;
  const raw = v / 4, p = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].map(m => m * p).find(s => s >= raw);
  return Math.max(4, step * 4);
}

// A chart owns its card, legend toggles and a draw function; toggling a
// series in the legend redraws the chart without it (and rescales the axis).
function chart(title, keys, H, draw, ages = true) {
  const card = document.createElement("div"); card.className = "chart";
  const head = document.createElement("header");
  head.innerHTML = `<h2>${title}</h2>`;
  const c = { H, keys, hidden: new Set(), draw, cursor: null, ages };
  if (keys.length > 1) {
    const legend = document.createElement("div"); legend.className = "legend";
    keys.forEach(k => {
      const b = document.createElement("button");
      const name = k === "idle" ? "idle villagers" : k;
      b.type = "button"; b.title = `Show or hide ${name}`; b.setAttribute("aria-label", name); b.setAttribute("aria-pressed", "true");
      b.innerHTML = `<i style="background:${color(k)}"></i>${img(iconOf(k))}`;
      b.addEventListener("click", () => {
        c.hidden.has(k) ? c.hidden.delete(k) : c.hidden.add(k);
        b.classList.toggle("off", c.hidden.has(k)); b.setAttribute("aria-pressed", String(!c.hidden.has(k)));
        render(c);
      });
      legend.appendChild(b);
    });
    head.appendChild(legend);
  }
  card.appendChild(head);
  c.svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": title }, card);
  document.getElementById("charts").appendChild(card);
  charts.push(c);
  render(c);
  return c;
}

const ROMAN = { 1: "I", 2: "II", 3: "III", 4: "IV" };
function ageMarks(c) {
  (D.ages || []).forEach(e => {
    if (e.started != null)
      el("rect", { x: x(e.started), y: PAD.t, width: Math.max(1, x(e.reached) - x(e.started)), height: c.H - PAD.t - PAD.b,
                   fill: "var(--accent)", opacity: 0.08 }, c.svg);
    el("line", { x1: x(e.reached), x2: x(e.reached), y1: PAD.t, y2: c.H - PAD.b, stroke: "var(--accent-dim)", "stroke-width": 1 }, c.svg);
    el("text", { x: x(e.reached) + 3, y: PAD.t + 10, style: "fill:var(--accent);font-family:var(--serif)" }, c.svg).textContent = ROMAN[e.age];
  });
}

function render(c) {
  c.svg.innerHTML = "";
  if (c.ages) ageMarks(c);
  c.draw(c, c.keys.filter(k => !c.hidden.has(k)));
  hover(c);
  if (lastT != null) placeCursors(lastT);
}

function axes(c, ymax, unit) {
  const { svg, H } = c;
  const y = v => H - PAD.b - v / ymax * (H - PAD.t - PAD.b);
  for (let i = 0; i <= 4; i++) {
    const v = ymax * i / 4, yy = y(v);
    el("line", { x1: PAD.l, x2: W - PAD.r, y1: yy, y2: yy, stroke: "var(--rule)", "stroke-width": 1 }, svg);
    el("text", { x: PAD.l - 8, y: yy + 4, "text-anchor": "end" }, svg).textContent = Math.round(v) + (i === 4 && unit ? unit : "");
  }
  const step = [60, 120, 300, 600, 900].find(s => (t1 - t0) / s <= 10) || 1200;
  for (let t = Math.ceil(t0 / step) * step; t <= t1; t += step)
    el("text", { x: x(t), y: H - 6, "text-anchor": "middle" }, svg).textContent = fmt(t);
  return y;
}

function hover(c) {
  const { svg, H } = c;
  c.cursor = el("line", { y1: PAD.t, y2: H - PAD.b, stroke: "var(--accent)", "stroke-width": 1, "stroke-dasharray": "3 3", visibility: "hidden" }, svg);
  const hit = el("rect", { x: PAD.l, y: 0, width: W - PAD.l - PAD.r, height: H, fill: "transparent" }, svg);
  const toT = ev => { const p = svg.createSVGPoint(); p.x = ev.clientX; p.y = ev.clientY;
    const q = p.matrixTransform(svg.getScreenCTM().inverse()); return t0 + (q.x - PAD.l) / (W - PAD.l - PAD.r) * (t1 - t0); };
  hit.addEventListener("mousemove", ev => { if (pinned == null) select(toT(ev)); });
  hit.addEventListener("click", ev => { const t = toT(ev); pinned = pinned == null ? t : null; select(t); });
  hit.addEventListener("mouseleave", () => { if (pinned == null) cursors().forEach(cur => cur.setAttribute("visibility", "hidden")); });
}

function drawLines(get, unit) {
  return (c, keys) => {
    let max = 0; rows.forEach(r => keys.forEach(k => { const v = get(r, k); if (v != null) max = Math.max(max, v); }));
    const y = axes(c, niceMax(max), unit);
    const ends = [];
    keys.forEach(k => {
      let d = "", pen = false;
      rows.forEach(r => { const v = get(r, k); if (v == null) { pen = false; return; }
        d += (pen ? "L" : "M") + x(r.t).toFixed(1) + "," + y(v).toFixed(1); pen = true; });
      el("path", { d, fill: "none", stroke: color(k), "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, c.svg);
      const last = [...rows].reverse().find(r => get(r, k) != null);
      if (last) ends.push({ k, y: y(get(last, k)) });
    });
    // Line ends carry the game icon, so identity never relies on color alone.
    ends.sort((a, b) => a.y - b.y).forEach((e, i, a) => { if (i && e.y - a[i - 1].y < 16) e.y = a[i - 1].y + 16; });
    ends.forEach(e => { if (ICON[iconOf(e.k)]) el("image", { href: ICON[iconOf(e.k)], x: W - PAD.r + 6, y: e.y - 8, width: 16, height: 16 }, c.svg); });
  };
}

// Monotone cubic (Fritsch–Carlson) through the points: smooth, passes through
// every value and never overshoots, so a count never shows a peak or dip that
// did not happen. Returns the "C" segments after the first point.
function monotone(pts) {
  const n = pts.length;
  if (n < 3) return pts.slice(1).map(p => `L${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("");
  const dx = [], s = [], m = new Array(n);
  for (let i = 0; i < n - 1; i++) { dx[i] = pts[i + 1][0] - pts[i][0]; s[i] = (pts[i + 1][1] - pts[i][1]) / (dx[i] || 1); }
  m[0] = s[0]; m[n - 1] = s[n - 2];
  for (let i = 1; i < n - 1; i++) m[i] = s[i - 1] * s[i] <= 0 ? 0 : (s[i - 1] + s[i]) / 2;
  for (let i = 0; i < n - 1; i++) {
    if (s[i] === 0) { m[i] = 0; m[i + 1] = 0; continue; }
    const a = m[i] / s[i], b = m[i + 1] / s[i], h = a * a + b * b;
    if (h > 9) { const k = 3 / Math.sqrt(h); m[i] = k * a * s[i]; m[i + 1] = k * b * s[i]; }
  }
  let d = "";
  for (let i = 0; i < n - 1; i++) {
    const [x0, y0] = pts[i], [x1, y1] = pts[i + 1], h = dx[i] / 3;
    d += `C${(x0 + h).toFixed(1)},${(y0 + m[i] * h).toFixed(1)} ${(x1 - h).toFixed(1)},${(y1 - m[i + 1] * h).toFixed(1)} ${x1.toFixed(1)},${y1.toFixed(1)}`;
  }
  return d;
}

// Villager counts move in steps of one every few seconds; drawn per reading
// they look like stairs. The bands are drawn from one sample every
// SMOOTH_S seconds of game time joined by monotone curves; the cursor and the
// moment card still use every reading.
const SMOOTH_S = 12;
function drawStacked(c, keys) {
  const val = (r, k) => (k === "idle" ? r.idle : r.vil[k]) || 0;
  const tot = r => keys.reduce((s, k) => s + val(r, k), 0);
  const y = axes(c, niceMax(Math.max(1, ...rows.map(tot))), "");
  const sample = rows.filter((r, i) => i === 0 || i === rows.length - 1 || Math.floor(r.t / SMOOTH_S) !== Math.floor(rows[i - 1].t / SMOOTH_S));
  let base = sample.map(() => 0);
  keys.forEach(k => {
    const top = sample.map((r, i) => base[i] + val(r, k));
    const upper = sample.map((r, i) => [x(r.t), y(top[i])]);
    const lower = sample.map((r, i) => [x(r.t), y(base[i])]).reverse();
    const d = `M${upper[0][0].toFixed(1)},${upper[0][1].toFixed(1)}` + monotone(upper)
            + `L${lower[0][0].toFixed(1)},${lower[0][1].toFixed(1)}` + monotone(lower) + "Z";
    el("path", { d, fill: color(k), stroke: "var(--panel)", "stroke-width": 2, "stroke-linejoin": "round" }, c.svg);
    base = top;
  });
}

function drawPopulation(c) {
  const y = axes(c, niceMax(Math.max(10, ...rows.map(r => r.cap || 0))), "");
  const path = key => rows.filter(r => r[key] != null).map((r, i) => (i ? "L" : "M") + x(r.t).toFixed(1) + "," + y(r[key]).toFixed(1)).join("");
  el("path", { d: path("cap"), fill: "none", stroke: "var(--accent-dim)", "stroke-width": 2, "stroke-dasharray": "5 4" }, c.svg);
  el("path", { d: path("pop"), fill: "none", stroke: "var(--ink)", "stroke-width": 2 }, c.svg);
  const last = [...rows].reverse().find(r => r.pop != null);
  if (last) { el("text", { x: W - PAD.r + 6, y: y(last.pop) + 12, style: "fill:var(--ink-2)" }, c.svg).textContent = "pop";
              el("text", { x: W - PAD.r + 6, y: y(last.cap) - 4, style: "fill:var(--accent)" }, c.svg).textContent = "cap"; }
}

const LANES = { housed: "Housed", tc_idle: "TC idle", idle_villager: "Idle villagers", floating: "Floating" };
if (D.build) LANES.build = "Off the build";
function drawLanes(c) {
  const lane = 18;
  Object.keys(LANES).forEach((id, i) => {
    const yy = PAD.t + i * (lane + 6);
    el("text", { x: PAD.l - 8, y: yy + 13, "text-anchor": "end" }, c.svg).textContent = LANES[id];
    el("rect", { x: PAD.l, y: yy, width: W - PAD.l - PAD.r, height: lane, fill: "var(--panel-2)", rx: 2 }, c.svg);
    D.alerts.filter(a => a.id === id).forEach(a => {
      const r = el("rect", { x: x(a.start), y: yy, width: Math.max(2, x(a.end) - x(a.start) - 2), height: lane, rx: 2,
        fill: `var(--${a.severity})` }, c.svg);
      el("title", {}, r).textContent = `${a.text} (${fmt(a.start)}–${fmt(a.end)})`;
    });
  });
}

function placeCursors(t) {
  cursors().forEach(cur => { cur.setAttribute("x1", x(t)); cur.setAttribute("x2", x(t)); cur.setAttribute("visibility", "visible"); });
}

function select(t) {
  if (!rows.length) return;
  const r = rows.reduce((b, q) => Math.abs(q.t - t) < Math.abs(b.t - t) ? q : b);
  lastT = r.t;
  placeCursors(r.t);
  document.getElementById("sel-hint").textContent = pinned != null ? "Click a chart again to unpin." : "Click to pin this moment.";
  const v = n => n == null ? "–" : n;
  // An alert still open when the log ends has end == t1: include that last moment.
  const active = D.alerts.filter(a => a.start <= r.t && (r.t < a.end || (a.end === t1 && r.t === t1)));
  const sev = id => (active.find(a => a.id === id) || {}).severity || "";
  const tc = r.producing == null ? "" : r.producing
    ? `<span class="chip quiet">TC producing</span>` : `<span class="chip ${sev("tc_idle")}">TC idle</span>`;
  const up = (D.ages || []).find(e => e.started != null && e.started <= r.t && r.t < e.reached);
  const age = up ? `${ROMAN[up.age - 1]} → ${ROMAN[up.age]}` : (r.age ? ROMAN[r.age] : "");
  let h = `<div class="m-head"><span class="m-clock">${fmt(r.t)}${age ? `<span class="m-age" title="${up ? "aging up" : "age"}">${age}</span>` : ""}</span>${pinned != null ? `<span class="m-pin">pinned</span>` : ""}</div>
    <div class="m-chips">
      <span class="chip ${sev("housed")}" title="population">${img("pop")}${r.pop == null ? "–" : `${r.pop}/${r.cap}`}</span>
      <span class="chip ${sev("idle_villager")}" title="idle villagers">${img("villager")}<sup>zz</sup>${v(r.idle)}</span>${tc}
    </div>`;
  RES.forEach(k => {
    h += `<div class="res"><span title="${k}">${img(k)}</span><b>${v(r.res[k])}</b>
      <span class="vil" title="villagers on ${k}">${img("villager")}${v(r.vil[k])}</span>
      <span class="inc" title="income per minute">${r.inc[k] == null ? "–" : r.inc[k] + "/min"}</span></div>`;
  });
  h += `<div class="m-alerts">${active.length ? active.map(a => `<span class="pill ${a.severity}">${a.text}</span>`).join("")
                                               : `<span class="calm">No alerts at this moment</span>`}</div>`;
  document.getElementById("moment").innerHTML = h;
  const frameImg = document.getElementById("sel-frame"), note = document.getElementById("sel-frame-note");
  const f = D.frames.length ? D.frames.reduce((b, q) => Math.abs(q - r.t) < Math.abs(b - r.t) ? q : b) : null;
  if (f != null && Math.abs(f - r.t) <= 15) {
    frameImg.src = `frames/${String(f).padStart(5, "0")}.jpg`; frameImg.hidden = false;
    note.textContent = `Panel as captured at ${fmt(f)}`;
  } else { frameImg.hidden = true; note.textContent = ""; }
}

if (rows.length) {
  chart("Villagers per resource", ORDER, 228, drawStacked);
  chart("Income per minute", RES, 204, drawLines((r, k) => r.inc[k], "/min"));
  chart("Stockpile", RES, 204, drawLines((r, k) => r.res[k], ""));
  chart("Population and cap", [], 180, drawPopulation);
  chart("Alerts", [], PAD.t + Object.keys(LANES).length * 24 + PAD.b, drawLanes, false);
  select(t1);
}
</script>
</body>
</html>
"""
