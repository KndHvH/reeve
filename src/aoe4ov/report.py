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

from . import __version__
from .income import IncomeTracker
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
ICONS = Path(__file__).resolve().parents[2] / "assets" / "report_icons"
PROBLEMS = [("tc_idle", "Town center idle"), ("housed", "Housed"),
            ("idle_villager", "Idle villagers"), ("floating", "Floating resources")]


def _icons() -> dict[str, str]:
    return {p.stem: "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()
            for p in sorted(ICONS.glob("*.png"))}


def build_timeline(log_path: Path, config: dict | None = None) -> dict:
    """One row per reading (game time), plus alert intervals and frames."""
    tracker, engine, income = StateTracker(), RuleEngine(config=config or load_config()), IncomeTracker()
    rows, intervals, open_alerts = [], [], {}
    for raw in log_path.read_text(encoding="utf-8").splitlines():
        row = json.loads(raw)
        if "values" not in row:
            continue
        values = dict(row["values"])
        if isinstance(values.get("pop"), list):
            values["pop"] = tuple(values["pop"])
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
            "res": dict(s.resources), "vil": dict(s.villagers),
            "inc": {k: None if v is None else round(v) for k, v in inc.per_min.items()},
            "incv": {k: None if v is None else round(v, 1) for k, v in inc.per_villager.items()},
        })
    end = rows[-1]["t"] if rows else 0
    intervals += [a | {"end": end} for a in open_alerts.values()]
    frames = sorted(int(p.stem) for p in (log_path.parent / "frames").glob("[0-9]*.jpg"))
    return {"rows": rows, "alerts": intervals, "frames": frames}


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
    for aid, label in PROBLEMS:
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
        "final_pop": (rows[-1]["pop"], rows[-1]["cap"]),
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
        <div class='minis'>{vil}</div>
        <div class='line'><span>Villagers by minute</span></div>
        <div class='pair'><span>Peak idle villagers</span><b>{s['peak_idle']}</b></div>
        <div class='pair'><span>Final population</span><b>{'–' if pop is None else f'{pop}/{cap}'}</b></div>
      </section>"""
    rows = "".join(
        f"<div class='problem {p['severity'] or 'none'}'><i></i><span>{e(p['label'])}</span>"
        f"<b>{_fmt_clock(p['seconds']) if p['seconds'] else 'none'}</b></div>"
        for p in s["problems"])
    problems = f"""
      <section class='col'>
        <h2>Time with problems</h2>
        {rows}
        <p class='note'>Bar color is the worst level the alert reached.</p>
      </section>"""
    inc = "".join(
        f"<div class='income'><img src='{icons.get(r, '')}' alt='{r}' title='{r}'>"
        f"<b>{'–' if v is None else v}</b><span>per minute</span></div>"
        for r, v in s["income"].items())
    income = f"""
      <section class='col'>
        <h2>Average income</h2>
        {inc}
      </section>"""
    return overview + problems + income


def write_report(session: Path) -> Path:
    tl = build_timeline(session / "log.jsonl")
    out = session / "report.html"
    out.write_text(render(tl, session.name), encoding="utf-8")
    return out


def _session_label(name: str) -> str:
    """'20261028-180649' -> '28 Oct 2026, 18:06'."""
    try:
        from datetime import datetime

        return datetime.strptime(name, "%Y%m%d-%H%M%S").strftime("%d %b %Y, %H:%M")
    except ValueError:
        return name


def render(tl: dict, title: str) -> str:
    icons = _icons()
    return (TEMPLATE
            .replace("__TITLE__", html.escape(_session_label(title)))
            .replace("__VERSION__", __version__)
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
<style>
:root {
  color-scheme: dark;
  --night: #0e1319; --panel: #151c25; --panel-2: #1a2330; --rule: #263140;
  --gold: #c9a45c; --gold-dim: #6b5734; --gold-light: #ead39a;
  --ink: #ece4d0; --ink-2: #c4bfb2; --mist: #98a0a8;
  --series-food: #e5484d; --series-wood: #93582a; --series-stone: #9fa3a8; --series-gold: #efc12e; --series-idle: #4f86d9;
  --status-info: #7fb2c9; --status-warn: #f0b429; --status-critical: #e5484d;
  --serif: "Palatino Linotype", "Book Antiqua", Palatino, Georgia, serif;
  --sans: "Segoe UI", system-ui, sans-serif;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--night); color: var(--ink); font: 14px/1.5 var(--sans); }
.page { max-width: 1200px; margin: 0 auto; padding: 28px 16px 56px; }
header { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 8px;
  border-bottom: 1px solid var(--gold-dim); padding-bottom: 10px; margin-bottom: 20px; }
h1 { font: 600 30px/1.1 var(--serif); color: var(--gold-light); margin: 0; letter-spacing: .3px; }
header p { margin: 0; color: var(--mist); }
h2 { font: 600 17px/1.2 var(--serif); color: var(--gold); margin: 0 0 12px; }

/* Summary ledger: the one framed element, like the game's gold panels. */
.ledger { display: grid; grid-template-columns: 1.15fr 1fr 0.9fr; background: var(--panel);
  border: 1px solid var(--gold); outline: 1px solid var(--gold-dim); outline-offset: 3px; border-radius: 3px; margin: 4px 4px 28px; }
.col { padding: 18px 20px; }
.col + .col { border-left: 1px solid var(--gold-dim); }
.hero b { font: 600 34px/1 var(--serif); color: var(--ink); font-variant-numeric: tabular-nums; }
.hero span { display: block; color: var(--mist); margin-top: 4px; }
.minis { display: flex; gap: 18px; margin-top: 16px; }
.mini b { font: 600 22px/1 var(--serif); font-variant-numeric: tabular-nums; }
.mini span { display: block; color: var(--mist); font-size: 12px; }
.line span { color: var(--mist); font-size: 12px; }
.pair { display: flex; justify-content: space-between; padding-top: 8px; margin-top: 8px; border-top: 1px solid var(--rule); }
.pair span { color: var(--ink-2); } .pair b { font-variant-numeric: tabular-nums; }
.problem { display: grid; grid-template-columns: 4px 1fr auto; align-items: center; gap: 10px; padding: 7px 0; border-bottom: 1px solid var(--rule); }
.problem i { height: 20px; border-radius: 2px; background: var(--rule); }
.problem.info i { background: var(--status-info); } .problem.warn i { background: var(--status-warn); } .problem.critical i { background: var(--status-critical); }
.problem b { font-variant-numeric: tabular-nums; } .problem.none b { color: var(--mist); font-weight: 400; }
.note { color: var(--mist); font-size: 12px; margin: 10px 0 0; }
.income { display: grid; grid-template-columns: 26px auto 1fr; align-items: center; gap: 10px; padding: 6px 0; }
.income img { width: 24px; height: 24px; object-fit: contain; }
.income b { font: 600 20px/1 var(--serif); font-variant-numeric: tabular-nums; } .income span { color: var(--mist); font-size: 12px; }
.empty { color: var(--mist); padding: 18px 20px; margin: 0; }
@media (max-width: 900px) { .ledger { grid-template-columns: 1fr; } .col + .col { border-left: 0; border-top: 1px solid var(--gold-dim); } }

.layout { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 18px; align-items: start; }
@media (max-width: 900px) { .layout { grid-template-columns: 1fr; } }
.chart { background: var(--panel); border: 1px solid var(--rule); border-radius: 3px; padding: 14px 14px 8px; margin-bottom: 14px; }
.chart header { border: 0; padding: 0; margin: 0 0 6px; }
.legend { display: flex; gap: 12px; }
.legend span { display: inline-flex; align-items: center; gap: 4px; }
.legend i { width: 10px; height: 10px; border-radius: 2px; } .legend img { width: 18px; height: 18px; object-fit: contain; }
svg { display: block; width: 100%; height: auto; overflow: visible; }
svg text { fill: var(--mist); font: 11px var(--sans); }

/* Moment card */
.side { position: sticky; top: 12px; background: var(--panel); border: 1px solid var(--gold); border-radius: 3px; padding: 14px; }
.m-head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 12px; }
.m-clock { font: 600 30px/1 var(--serif); color: var(--gold-light); font-variant-numeric: tabular-nums; }
.m-pin { font-size: 12px; color: var(--gold); }
.m-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
.chip { display: inline-flex; align-items: center; gap: 6px; background: var(--panel-2); border: 1px solid var(--rule);
  border-radius: 3px; padding: 4px 8px; font-size: 13px; font-variant-numeric: tabular-nums; }
.chip img { width: 18px; height: 18px; object-fit: contain; }
.chip.warn { border-color: var(--status-warn); box-shadow: inset 0 0 0 1px var(--status-warn); }
.chip.critical { border-color: var(--status-critical); box-shadow: inset 0 0 0 1px var(--status-critical); }
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
.pill { font-size: 12px; border-radius: 3px; padding: 2px 8px; font-weight: 600; color: #121212; }
.pill.info { background: var(--status-info); } .pill.warn { background: var(--status-warn); } .pill.critical { background: var(--status-critical); color: #fff; }
.calm { color: var(--mist); font-size: 13px; }
.frame { width: 100%; border-radius: 3px; margin-top: 12px; border: 1px solid var(--rule); display: block; }
.frame[hidden] { display: none; }
.hint { color: var(--mist); font-size: 12px; margin-top: 8px; }
footer { color: var(--mist); font-size: 12px; margin-top: 24px; }
</style>
</head>
<body>
<div class="page">
<header>
  <h1>Match report</h1>
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
<footer>aoe4-overlay __VERSION__</footer>
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
const cursors = [];
let pinned = null;

function niceMax(v) { if (v <= 0) return 1; const p = 10 ** Math.floor(Math.log10(v)); return Math.ceil(v / p) * p; }

function frame(title, keys, H) {
  const card = document.createElement("div"); card.className = "chart";
  const legend = keys.length > 1 ? `<div class="legend">${keys.map(k =>
    `<span title="${k === "idle" ? "idle villagers" : k}" aria-label="${k}"><i style="background:${color(k)}"></i>${img(iconOf(k))}</span>`).join("")}</div>` : "";
  card.innerHTML = `<header><h2>${title}</h2>${legend}</header>`;
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": title }, card);
  document.getElementById("charts").appendChild(card);
  return svg;
}

function axes(svg, H, ymax, unit) {
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

function hover(svg, H) {
  const cur = el("line", { y1: PAD.t, y2: H - PAD.b, stroke: "var(--gold)", "stroke-width": 1, "stroke-dasharray": "3 3", visibility: "hidden" }, svg);
  cursors.push(cur);
  const hit = el("rect", { x: PAD.l, y: 0, width: W - PAD.l - PAD.r, height: H, fill: "transparent" }, svg);
  const toT = ev => { const p = svg.createSVGPoint(); p.x = ev.clientX; p.y = ev.clientY;
    const q = p.matrixTransform(svg.getScreenCTM().inverse()); return t0 + (q.x - PAD.l) / (W - PAD.l - PAD.r) * (t1 - t0); };
  hit.addEventListener("mousemove", ev => { if (pinned == null) select(toT(ev)); });
  hit.addEventListener("click", ev => { const t = toT(ev); pinned = pinned == null ? t : null; select(t); });
  hit.addEventListener("mouseleave", () => { if (pinned == null) cursors.forEach(c => c.setAttribute("visibility", "hidden")); });
}

function lines(title, get, keys, unit, H = 170) {
  const svg = frame(title, keys, H);
  let max = 0; rows.forEach(r => keys.forEach(k => { const v = get(r, k); if (v != null) max = Math.max(max, v); }));
  const y = axes(svg, H, niceMax(max * 1.05), unit);
  const ends = [];
  keys.forEach(k => {
    let d = "", pen = false;
    rows.forEach(r => { const v = get(r, k); if (v == null) { pen = false; return; }
      d += (pen ? "L" : "M") + x(r.t).toFixed(1) + "," + y(v).toFixed(1); pen = true; });
    el("path", { d, fill: "none", stroke: color(k), "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
    const last = [...rows].reverse().find(r => get(r, k) != null);
    if (last) ends.push({ k, y: y(get(last, k)) });
  });
  // Line ends carry the game icon, so identity never relies on color alone.
  ends.sort((a, b) => a.y - b.y).forEach((e, i, a) => { if (i && e.y - a[i - 1].y < 16) e.y = a[i - 1].y + 16; });
  ends.forEach(e => { if (ICON[iconOf(e.k)]) el("image", { href: ICON[iconOf(e.k)], x: W - PAD.r + 6, y: e.y - 8, width: 16, height: 16 }, svg); });
  hover(svg, H);
}

function stacked(title, keys, H = 190) {
  const svg = frame(title, keys, H);
  const val = (r, k) => (k === "idle" ? r.idle : r.vil[k]) || 0;
  const tot = r => keys.reduce((s, k) => s + val(r, k), 0);
  const y = axes(svg, H, niceMax(Math.max(1, ...rows.map(tot)) * 1.05), "");
  let base = rows.map(() => 0);
  keys.forEach(k => {
    const top = rows.map((r, i) => base[i] + val(r, k));
    let d = rows.map((r, i) => (i ? "L" : "M") + x(r.t).toFixed(1) + "," + y(top[i]).toFixed(1)).join("");
    d += rows.slice().reverse().map((r, j) => "L" + x(r.t).toFixed(1) + "," + y(base[rows.length - 1 - j]).toFixed(1)).join("") + "Z";
    el("path", { d, fill: color(k), stroke: "var(--panel)", "stroke-width": 2, "stroke-linejoin": "round" }, svg);
    base = top;
  });
  hover(svg, H);
}

function population(H = 150) {
  const svg = frame("Population and cap", [], H);
  const y = axes(svg, H, niceMax(Math.max(10, ...rows.map(r => r.cap || 0)) * 1.05), "");
  const path = key => rows.filter(r => r[key] != null).map((r, i) => (i ? "L" : "M") + x(r.t).toFixed(1) + "," + y(r[key]).toFixed(1)).join("");
  el("path", { d: path("cap"), fill: "none", stroke: "var(--gold-dim)", "stroke-width": 2, "stroke-dasharray": "5 4" }, svg);
  el("path", { d: path("pop"), fill: "none", stroke: "var(--ink)", "stroke-width": 2 }, svg);
  const last = [...rows].reverse().find(r => r.pop != null);
  if (last) { el("text", { x: W - PAD.r + 6, y: y(last.pop) + 12, style: "fill:var(--ink-2)" }, svg).textContent = "pop";
              el("text", { x: W - PAD.r + 6, y: y(last.cap) - 4, style: "fill:var(--gold)" }, svg).textContent = "cap"; }
  hover(svg, H);
}

function alertLanes() {
  const names = { housed: "Housed", tc_idle: "TC idle", idle_villager: "Idle villagers", floating: "Floating" };
  const ids = Object.keys(names), lane = 18, H = PAD.t + ids.length * (lane + 6) + PAD.b;
  const card = document.createElement("div"); card.className = "chart";
  card.innerHTML = `<header><h2>Alerts</h2><div class="legend">
    <span title="info"><i style="background:var(--status-info)"></i></span>
    <span title="warn"><i style="background:var(--status-warn)"></i></span>
    <span title="critical"><i style="background:var(--status-critical)"></i></span></div></header>`;
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Alert timeline" }, card);
  document.getElementById("charts").appendChild(card);
  ids.forEach((id, i) => {
    const yy = PAD.t + i * (lane + 6);
    el("text", { x: PAD.l - 8, y: yy + 13, "text-anchor": "end" }, svg).textContent = names[id];
    el("rect", { x: PAD.l, y: yy, width: W - PAD.l - PAD.r, height: lane, fill: "var(--panel-2)", rx: 2 }, svg);
    D.alerts.filter(a => a.id === id).forEach(a => {
      const r = el("rect", { x: x(a.start), y: yy, width: Math.max(2, x(a.end) - x(a.start) - 2), height: lane, rx: 2,
        fill: `var(--status-${a.severity})` }, svg);
      el("title", {}, r).textContent = `${a.text} (${fmt(a.start)}–${fmt(a.end)})`;
    });
  });
  hover(svg, H);
}

function select(t) {
  if (!rows.length) return;
  const r = rows.reduce((b, q) => Math.abs(q.t - t) < Math.abs(b.t - t) ? q : b);
  cursors.forEach(c => { c.setAttribute("x1", x(r.t)); c.setAttribute("x2", x(r.t)); c.setAttribute("visibility", "visible"); });
  document.getElementById("sel-hint").textContent = pinned != null ? "Click a chart again to unpin." : "Click to pin this moment.";
  const v = n => n == null ? "–" : n;
  const active = D.alerts.filter(a => a.start <= r.t && r.t < a.end);
  const sev = id => (active.find(a => a.id === id) || {}).severity || "";
  const tc = r.producing == null ? "" : r.producing
    ? `<span class="chip quiet">TC producing</span>` : `<span class="chip ${sev("tc_idle")}">TC idle</span>`;
  let h = `<div class="m-head"><span class="m-clock">${fmt(r.t)}</span>${pinned != null ? `<span class="m-pin">pinned</span>` : ""}</div>
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
  stacked("Villagers per resource", ORDER);
  lines("Income per minute", (r, k) => r.inc[k], RES, "/min");
  lines("Stockpile", (r, k) => r.res[k], RES, "");
  population();
  alertLanes();
  select(t1);
}
</script>
</body>
</html>
"""
