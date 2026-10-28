"""Post-match report: sessions/<start>/report.html.

The report replays the session log through the same state tracker, alert
rules and income tracker the overlay uses, so its numbers always match what
was shown live. It is a single self-contained HTML file (inline SVG + a
little JavaScript, no network): charts over game time for villagers per
resource, stockpiles, income per minute and population, plus the alert
timeline and a summary. Hovering a chart moves a shared cursor; clicking
pins it and shows the values read at that moment next to the audit frame
(the panel crop saved every 10 s of game time).
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from . import __version__
from .income import IncomeTracker
from .replay import _wall_seconds
from .rules import RuleEngine, _fmt_clock, load_config
from .state import RESOURCES, StateTracker

# Resource colors follow the game (meat, log, gold, stone) and were tuned to
# pass the colorblind separation checks on the dark surface: food #e4608c,
# wood #9c5a24, gold #f0bd1a, stone #6f97d4 (worst pair CVD dE 12.1, normal
# vision 19.1). Idle villagers are neutral gray. The game's own icons (cropped
# from captures, assets/report_icons) carry identity next to every color.
SERIES_ORDER = ["food", "wood", "stone", "gold", "idle"]
ICONS = Path(__file__).resolve().parents[2] / "assets" / "report_icons"


def _icons() -> dict[str, str]:
    import base64

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
    frames = sorted(int(p.stem) for p in (log_path.parent / "frames").glob("*.jpg"))
    return {"rows": rows, "alerts": intervals, "frames": frames}


def summarize(tl: dict) -> list[tuple[str, str]]:
    rows, alerts = tl["rows"], tl["alerts"]
    if not rows:
        return []

    def total(aid, severity=None):
        return sum(a["end"] - a["start"] for a in alerts
                   if a["id"] == aid and (severity is None or a["severity"] == severity))

    def villagers_at(minute):
        r = next((r for r in rows if r["t"] >= minute * 60), None)
        if r is None:
            return "–"
        n = sum(v for v in r["vil"].values() if v is not None) + (r["idle"] or 0)
        return str(n)

    def avg_income(res):
        vals = [r["inc"][res] for r in rows if r["inc"][res] is not None]
        return f"{sum(vals) / len(vals):.0f}/min" if vals else "–"

    out = [
        ("Duration", _fmt_clock(rows[-1]["t"] - rows[0]["t"]) + f"  ({_fmt_clock(rows[0]['t'])}–{_fmt_clock(rows[-1]['t'])})"),
        ("Villagers at 5 / 10 / 15 min", " / ".join(villagers_at(m) for m in (5, 10, 15))),
        ("Town center idle", _fmt_clock(total("tc_idle"))),
        ("Housed (at the cap)", _fmt_clock(total("housed", "critical"))),
        ("Idle villagers alert", _fmt_clock(total("idle_villager"))),
        ("Peak idle villagers", str(max((r["idle"] or 0) for r in rows))),
        ("Floating resources", _fmt_clock(total("floating"))),
    ]
    out += [(f"Average income, {r}", avg_income(r)) for r in RESOURCES]
    return out


def write_report(session: Path) -> Path:
    tl = build_timeline(session / "log.jsonl")
    out = session / "report.html"
    out.write_text(render(tl, session.name), encoding="utf-8")
    return out


def render(tl: dict, title: str) -> str:
    summary = "".join(f"<div class='stat'><span>{html.escape(k)}</span><b>{html.escape(v)}</b></div>"
                      for k, v in summarize(tl))
    data = json.dumps(tl, separators=(",", ":"))
    return (TEMPLATE
            .replace("__TITLE__", html.escape(title))
            .replace("__VERSION__", __version__)
            .replace("__SUMMARY__", summary or "<p class='muted'>No readings in this session.</p>")
            .replace("__SERIES__", json.dumps(SERIES_ORDER))
            .replace("__ICONS__", json.dumps(_icons()))
            .replace("__DATA__", data))


TEMPLATE = r"""<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Match report</title>
<style>
.viz-root {
  color-scheme: light;
  --surface-0: #f4f4f2; --surface-1: #fcfcfb; --border: #e2e1dc;
  --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #85847f;
  --grid: #ecebe7; --cursor: #52514e;
  --series-food: #e4608c; --series-wood: #9c5a24; --series-stone: #6f97d4; --series-gold: #f0bd1a; --series-idle: #8f8e86;
  --status-info: #6da7ec; --status-warn: #fab219; --status-critical: #d03b3b; --status-good: #0ca30c;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) .viz-root {
    color-scheme: dark;
    --surface-0: #111110; --surface-1: #1a1a19; --border: #2c2c2a;
    --text-primary: #f0efec; --text-secondary: #c3c2b7; --text-muted: #8f8e86;
    --grid: #262624; --cursor: #c3c2b7;
    --series-food: #e4608c; --series-wood: #9c5a24; --series-stone: #6f97d4; --series-gold: #f0bd1a; --series-idle: #8f8e86;
    --status-info: #5598e7;
  }
}
:root[data-theme="dark"] .viz-root {
  color-scheme: dark;
  --surface-0: #111110; --surface-1: #1a1a19; --border: #2c2c2a;
  --text-primary: #f0efec; --text-secondary: #c3c2b7; --text-muted: #8f8e86;
  --grid: #262624; --cursor: #c3c2b7;
  --series-food: #e4608c; --series-wood: #9c5a24; --series-stone: #6f97d4; --series-gold: #f0bd1a; --series-idle: #8f8e86;
  --status-info: #5598e7;
}
body { margin: 0; background: var(--surface-0); }
.viz-root { background: var(--surface-0); color: var(--text-primary); font: 14px/1.45 system-ui, "Segoe UI", sans-serif;
  max-width: 1180px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 20px; margin: 0 0 4px; } h2 { font-size: 15px; margin: 0 0 8px; }
.muted { color: var(--text-muted); }
.stats { display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 8px; margin: 20px 0 24px; }
.stat { background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }
.stat span { display: block; color: var(--text-secondary); font-size: 12px; } .stat b { font-size: 16px; }
.layout { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 16px; align-items: start; }
@media (max-width: 900px) { .layout { grid-template-columns: 1fr; } }
.card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px; padding: 14px; margin-bottom: 12px; }
.legend { display: flex; flex-wrap: wrap; gap: 12px; font-size: 12px; color: var(--text-secondary); margin-bottom: 6px; }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 5px; vertical-align: -1px; }
svg { display: block; width: 100%; height: auto; overflow: visible; }
svg text { fill: var(--text-muted); font-size: 11px; }
.side { position: sticky; top: 12px; }
.m-head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 10px; }
.m-clock { font-size: 26px; font-weight: 700; font-variant-numeric: tabular-nums; letter-spacing: .5px; }
.m-pin { font-size: 11px; color: var(--text-muted); border: 1px solid var(--border); border-radius: 999px; padding: 1px 8px; }
.m-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.chip { display: inline-flex; align-items: center; gap: 6px; background: var(--surface-0); border: 1px solid var(--border);
  border-radius: 6px; padding: 4px 8px; font-size: 13px; font-variant-numeric: tabular-nums; }
.chip img, .res img { width: 18px; height: 18px; object-fit: contain; }
.chip sup { font-size: 9px; color: var(--text-muted); margin-left: -5px; }
.chip.ok { color: var(--text-secondary); } .chip.bad { border-color: var(--status-warn); }
.res { display: grid; grid-template-columns: 22px 1fr auto auto; align-items: center; gap: 8px;
  padding: 7px 0; border-top: 1px solid var(--border); font-variant-numeric: tabular-nums; }
.res b { font-size: 16px; }
.res .vil { display: inline-flex; align-items: center; gap: 2px; color: var(--text-secondary); font-size: 13px; }
.res .vil img { width: 12px; height: 16px; }
.res .inc { color: var(--text-muted); font-size: 12px; min-width: 62px; text-align: right; }
.m-alerts { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
.pill { font-size: 12px; border-radius: 999px; padding: 2px 9px; color: #111; font-weight: 600; }
.pill.info { background: var(--status-info); } .pill.warn { background: var(--status-warn); } .pill.critical { background: var(--status-critical); color: #fff; }
.side .frame { width: 100%; border-radius: 6px; margin-top: 12px; background: #000; display: block; }
.side .frame[hidden] { display: none; }
.legend img { width: 14px; height: 14px; object-fit: contain; vertical-align: -3px; margin-right: 4px; }
.hint { font-size: 12px; color: var(--text-muted); }
</style>
</head>
<body>
<div class="viz-root">
<h1>Match report</h1>
<div class="muted">session __TITLE__ · aoe4-overlay __VERSION__ · times are game time</div>
<div class="stats">__SUMMARY__</div>
<div class="layout">
  <div id="charts"></div>
  <aside class="side card">
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
const img = (name, cls = "") => ICON[name] ? `<img src="${ICON[name]}" alt="${name}" class="${cls}">` : "";
const RES = ["food", "wood", "stone", "gold"];
const css = n => getComputedStyle(document.querySelector(".viz-root")).getPropertyValue(n).trim();
const color = k => `var(--series-${k})`;
const fmt = s => s == null ? "–" : `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
const rows = D.rows;
const t0 = rows.length ? rows[0].t : 0, t1 = rows.length ? rows[rows.length - 1].t : 1;
const W = 820, PAD = { l: 92, r: 64, t: 8, b: 22 };
const x = t => PAD.l + (t - t0) / Math.max(1, t1 - t0) * (W - PAD.l - PAD.r);
const NS = "http://www.w3.org/2000/svg";
const el = (tag, attrs, parent) => { const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; };
const cursors = [];
let pinned = null;

function niceMax(v) { if (v <= 0) return 1; const p = 10 ** Math.floor(Math.log10(v)); return Math.ceil(v / p) * p; }

function frame(title, legend, H) {
  const card = document.createElement("div"); card.className = "card";
  card.innerHTML = `<h2>${title}</h2>` + (legend.length > 1 ? `<div class="legend">${legend.map(k =>
    `<span><i style="background:${color(k)}"></i>${img(k === "idle" ? "villager" : k)}${k}</span>`).join("")}</div>` : "");
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": title }, card);
  document.getElementById("charts").appendChild(card);
  return svg;
}

function axes(svg, H, ymax, unit) {
  const y = v => H - PAD.b - v / ymax * (H - PAD.t - PAD.b);
  for (let i = 0; i <= 4; i++) {
    const v = ymax * i / 4, yy = y(v);
    el("line", { x1: PAD.l, x2: W - PAD.r, y1: yy, y2: yy, stroke: "var(--grid)", "stroke-width": 1 }, svg);
    el("text", { x: PAD.l - 6, y: yy + 4, "text-anchor": "end" }, svg).textContent = Math.round(v) + (i === 4 && unit ? unit : "");
  }
  const step = [60, 120, 300, 600, 900].find(s => (t1 - t0) / s <= 10) || 1200;
  for (let t = Math.ceil(t0 / step) * step; t <= t1; t += step)
    el("text", { x: x(t), y: H - 6, "text-anchor": "middle" }, svg).textContent = fmt(t);
  return y;
}

function hover(svg, H) {
  const cur = el("line", { y1: PAD.t, y2: H - PAD.b, stroke: "var(--cursor)", "stroke-width": 1, "stroke-dasharray": "3 3", visibility: "hidden" }, svg);
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
  ends.sort((a, b) => a.y - b.y).forEach((e, i, a) => { if (i && e.y - a[i - 1].y < 12) e.y = a[i - 1].y + 12; });
  ends.forEach(e => el("text", { x: W - PAD.r + 6, y: e.y + 4, style: "fill:var(--text-secondary)" }, svg).textContent = e.k);
  hover(svg, H);
}

function stacked(title, keys, H = 190) {
  const svg = frame(title, keys, H);
  const tot = r => keys.reduce((s, k) => s + ((k === "idle" ? r.idle : r.vil[k]) || 0), 0);
  const y = axes(svg, H, niceMax(Math.max(1, ...rows.map(tot)) * 1.05), "");
  const val = (r, k) => (k === "idle" ? r.idle : r.vil[k]) || 0;
  let base = rows.map(() => 0);
  keys.forEach(k => {
    const top = rows.map((r, i) => base[i] + val(r, k));
    let d = rows.map((r, i) => (i ? "L" : "M") + x(r.t).toFixed(1) + "," + y(top[i]).toFixed(1)).join("");
    d += rows.slice().reverse().map((r, j) => "L" + x(r.t).toFixed(1) + "," + y(base[rows.length - 1 - j]).toFixed(1)).join("") + "Z";
    el("path", { d, fill: color(k), stroke: "var(--surface-1)", "stroke-width": 2, "stroke-linejoin": "round" }, svg);
    base = top;
  });
  hover(svg, H);
}

function population(H = 150) {
  const svg = frame("Population and cap", [], H);
  const y = axes(svg, H, niceMax(Math.max(10, ...rows.map(r => r.cap || 0)) * 1.05), "");
  const path = key => rows.filter(r => r[key] != null).map((r, i) => (i ? "L" : "M") + x(r.t).toFixed(1) + "," + y(r[key]).toFixed(1)).join("");
  el("path", { d: path("cap"), fill: "none", stroke: "var(--text-muted)", "stroke-width": 2, "stroke-dasharray": "5 4" }, svg);
  el("path", { d: path("pop"), fill: "none", stroke: "var(--text-primary)", "stroke-width": 2 }, svg);
  const last = [...rows].reverse().find(r => r.pop != null);
  if (last) { el("text", { x: W - PAD.r + 6, y: y(last.pop) + 4, style: "fill:var(--text-secondary)" }, svg).textContent = "population";
              el("text", { x: W - PAD.r + 6, y: y(last.cap) - 6, style: "fill:var(--text-secondary)" }, svg).textContent = "cap"; }
  hover(svg, H);
}

function alertLanes() {
  const ids = ["housed", "tc_idle", "idle_villager", "floating"];
  const names = { housed: "housed", tc_idle: "TC idle", idle_villager: "idle villagers", floating: "floating" };
  const lane = 18, H = PAD.t + ids.length * (lane + 6) + PAD.b;
  const card = document.createElement("div"); card.className = "card";
  card.innerHTML = `<h2>Alerts</h2><div class="legend">
    <span><i style="background:var(--status-info)"></i>info</span>
    <span><i style="background:var(--status-warn)"></i>warn</span>
    <span><i style="background:var(--status-critical)"></i>critical</span></div>`;
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Alert timeline" }, card);
  document.getElementById("charts").appendChild(card);
  ids.forEach((id, i) => {
    const yy = PAD.t + i * (lane + 6);
    el("text", { x: PAD.l - 6, y: yy + 13, "text-anchor": "end" }, svg).textContent = names[id];
    el("rect", { x: PAD.l, y: yy, width: W - PAD.l - PAD.r, height: lane, fill: "var(--grid)", rx: 3 }, svg);
    D.alerts.filter(a => a.id === id).forEach(a => {
      const r = el("rect", { x: x(a.start), y: yy, width: Math.max(2, x(a.end) - x(a.start) - 2), height: lane, rx: 3,
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
  const tc = r.producing == null ? "" : r.producing
    ? `<span class="chip ok">TC producing</span>` : `<span class="chip bad">TC idle</span>`;
  let h = `<div class="m-head"><span class="m-clock">${fmt(r.t)}</span>${pinned != null ? `<span class="m-pin">pinned</span>` : ""}</div>
    <div class="m-chips">
      <span class="chip" title="population">${img("pop")}${r.pop == null ? "–" : `${r.pop}/${r.cap}`}</span>
      <span class="chip" title="idle villagers">${img("villager")}<sup>zz</sup>${v(r.idle)}</span>${tc}
    </div>`;
  RES.forEach(k => {
    h += `<div class="res"><span title="${k}">${img(k)}</span><b>${v(r.res[k])}</b>
      <span class="vil" title="villagers on ${k}">${img("villager")}${v(r.vil[k])}</span>
      <span class="inc" title="income per minute">${r.inc[k] == null ? "–" : r.inc[k] + "/min"}</span></div>`;
  });
  const active = D.alerts.filter(a => a.start <= r.t && r.t < a.end);
  h += `<div class="m-alerts">${active.length ? active.map(a => `<span class="pill ${a.severity}">${a.text}</span>`).join("")
                                               : `<span class="hint">No alerts</span>`}</div>`;
  document.getElementById("moment").innerHTML = h;
  const frameImg = document.getElementById("sel-frame"), note = document.getElementById("sel-frame-note");
  const f = D.frames.length ? D.frames.reduce((b, q) => Math.abs(q - r.t) < Math.abs(b - r.t) ? q : b) : null;
  if (f != null && Math.abs(f - r.t) <= 15) {
    frameImg.src = `frames/${String(f).padStart(5, "0")}.jpg`; frameImg.hidden = false;
    note.textContent = `Panel as captured at ${fmt(f)}`;
  } else { frameImg.hidden = true; note.textContent = D.frames.length ? "No frame near this moment." : ""; }
}

if (rows.length) {
  stacked("Villagers per resource", ["food", "wood", "stone", "gold", "idle"]);
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
