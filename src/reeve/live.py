"""Live reading of a match: the engine used by `watch` and by the overlay.

Each `step()` runs one cycle: finds the window, calibrates the anchor when
needed, captures only the regions, checks whether the panel is visible
(menu/pause) and reads. It also records the match in sessions/<start>/
(log.jsonl + images of failed readings), turns readings into a confirmed
game state and evaluates the alert rules, so callers only have to display
the result.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from .anchor import MIN_SCORE, AnchorMatch, panel_state
from .capture import Capture
from .income import Income, IncomeTracker
from .reader import Frame, read_frame
from .rules import Alert, RuleEngine
from .state import GameState, StateTracker
from .window import GameWindow, find_game_window

MAX_FAIL_SHOTS = 30  # failure images saved per match
# Panel hidden for longer than this = end of match. Long, since a pause or a
# menu must not split a match; a new match is told by the clock going back.
HIDDEN_END_S = 600
REPORT_AFTER_S = 10  # a match not being read for this long gets its report written (end screen, menu, alt-tab)
MIN_CONTRAST = 0.7   # anchor contrast ÷ template contrast: game ~0.88; menu/veil 0.03–0.38
DOUBT_BAND = (0.55, 0.72)  # queue score in this band: save the image for analysis
MAX_DOUBT_SHOTS = 20
LOW_CONF = 0.75      # a field read below this is kept as a doubt_read_ image (and turns the dot yellow)
MAX_LOW_SHOTS = 30
FRAME_EVERY_S = 10   # game seconds between audit frames (panel crop) kept for the report
NEW_MATCH_BACK_S = 30  # the clock going back more than this = a new match (restarted or a new game started quickly)
SHAPE_RATIO = 0.85   # anchor shape below 85% of calibration = panel covered/fading
RECAL_EVERY = 3      # with the panel gone, search again every 3 cycles (did the UI scale change?)


@dataclass
class Step:
    status: str                       # "no_game" | "waiting" | "hidden" | "reading"
    win: GameWindow | None = None
    match: AnchorMatch | None = None
    frame: Frame | None = None
    bad: list[str] = field(default_factory=list)
    grab_ms: float = 0.0
    read_ms: float = 0.0
    shape: float = 0.0                # anchor shape in this cycle
    contrast: float = 1.0             # anchor contrast ÷ template contrast
    events: list[str] = field(default_factory=list)  # messages for the display side
    state: GameState | None = None
    income: Income | None = None
    alerts: list[Alert] = field(default_factory=list)  # active alerts, most severe first
    build: object = None              # BuildTracker of the build order being followed, if any


class LiveReader:
    def __init__(self, every: float, sessions_dir: Path | None = None):
        from .paths import sessions_dir as default_sessions

        self.every = every
        self.sessions_dir = sessions_dir or default_sessions()
        self.cap = Capture()
        self.match: AnchorMatch | None = None
        self.size: tuple[int, int] | None = None
        self.fails = 0
        self.hidden = 0
        self.session: Path | None = None
        self.log = None
        self.saved_fails = 0
        self.saved_doubts = 0
        self._low_seen: set[tuple[str, str]] = set()
        self.tracker = StateTracker()
        self.rules = RuleEngine()
        self.income = IncomeTracker()
        self._last_frame_clock: int | None = None
        self._build_step: tuple | None = None   # (build id, step index) last logged
        self._match_clock: int | None = None    # latest game clock of the open match
        self.readings = 0
        self._idle_since: float | None = None   # when the open match stopped being read
        self._report_fresh = False              # report written since the last reading

    # --- session ----------------------------------------------------------
    def _open_session(self, events: list[str]) -> None:
        if self.log is None:
            name = f"{datetime.now():%Y%m%d-%H%M%S}"
            self.session = self.sessions_dir / name
            n = 2
            while self.session.exists():          # a match opened in the same second as the last one
                self.session, n = self.sessions_dir / f"{name}-{n}", n + 1
            self.session.mkdir(parents=True)
            self.log = open(self.session / "log.jsonl", "a", encoding="utf-8")
            self.saved_fails = self.saved_doubts = 0
            self._low_seen: set[tuple[str, str]] = set()
            self.tracker = StateTracker()
            self.rules = RuleEngine()
            self.income = IncomeTracker()
            self._last_frame_clock = None
            self._build_step = None
            self._match_clock = None
            self.readings = 0
            events.append(f"recording to {self.session}")

    def close(self, events: list[str] | None = None) -> None:
        if self.log:
            self.log.close()
            if events is not None:
                events.append(f"log saved to {self.session}")
            if self.readings and not self._report_fresh:
                self._report(events)
            elif not self.readings:
                # The panel showed up for a moment and no match was read: not a match.
                shutil.rmtree(self.session, ignore_errors=True)
        self.session, self.log = None, None

    def _report(self, events: list[str] | None) -> None:
        try:
            from .report import write_report

            out = write_report(self.session)
            self._report_fresh = True
            if events is not None:
                events.append(f"report: {out}")
        except Exception as e:  # the report must never break the overlay
            if events is not None:
                events.append(f"report failed: {e}")

    def _write(self, obj: dict) -> None:
        self.log.write(json.dumps({"wall": f"{datetime.now():%H:%M:%S}", **obj}, ensure_ascii=False) + "\n")
        self.log.flush()

    # --- cycle ------------------------------------------------------------
    def step(self) -> Step:
        """One cycle; also writes the report of the open match once it has not
        been read for REPORT_AFTER_S (end screen, menu, alt-tab), so a report
        exists even if the app is closed abruptly afterwards. Reading again
        makes it stale; it is rewritten the next time reading stops."""
        s = self._step()
        now = time.monotonic()
        if s.status == "reading":
            self._idle_since, self._report_fresh = None, False
        elif self.log and self.readings and not self._report_fresh:
            self._idle_since = self._idle_since or now
            if now - self._idle_since >= REPORT_AFTER_S:
                self._report(s.events)
        return s

    def _step(self) -> Step:
        events: list[str] = []
        win = find_game_window()
        if win is None or not win.foreground:
            return Step("no_game", win)

        if self.match is None or self.size != (win.width, win.height) or self.fails >= 3:
            self.match = self.cap.calibrate(win)
            self.size = (win.width, win.height)
            self.fails = 0
            if not self.match.ok:
                # Menu, options, loading screen or end of match: no panel on screen.
                # With a match open, only end it after HIDDEN_END_S (going into
                # the options to change the resolution must not split the match in two).
                m, self.match = self.match, None
                if self.log:
                    if self.hidden == 0:
                        self._write({"event": "panel_hidden", "anchor": round(m.score, 3)})
                    self.hidden += 1
                    if self.hidden * self.every >= HIDDEN_END_S:
                        self.close(events)
                        self.hidden = 0
                return Step("waiting", win, m, events=events)
            events.append(f"panel found: score {self.match.score:.3f} scale {self.match.scale:.3f}")
            self._open_session(events)

        match = self.match
        t0 = time.perf_counter()
        buf = self.cap.grab(win)
        grab_ms = (time.perf_counter() - t0) * 1000

        # Menu, pause or the end screen either hide the panel (shape disappears)
        # or draw a veil over it (shape stays, contrast drops): skip the reading
        # instead of logging garbage.
        shape, contrast = panel_state(buf, match)
        if not (shape >= max(MIN_SCORE, SHAPE_RATIO * match.score) and contrast >= MIN_CONTRAST):
            if self.hidden == 0:
                self._write({"event": "panel_hidden", "shape": round(shape, 3), "contrast": round(contrast, 2)})
            self.hidden += 1
            # A "missing" panel may just be the UI scale changed in the options
            # (the window keeps its size): search again every so often and,
            # if it turns up at another position/scale, continue the same match.
            if self.hidden % RECAL_EVERY == 0:
                new = self.cap.probe(win)
                moved = abs(new.scale - match.scale) > 0.01 * match.scale or abs(new.x - match.x) + abs(new.y - match.y) > 2
                if new.ok and moved:
                    self.cap.adopt(new, win)
                    self.match, self.hidden = new, 0
                    self._write({"event": "recalibrated", "anchor": [new.x, new.y, round(new.scale, 3), round(new.score, 3)]})
                    events.append(f"panel moved: recalibrated (scale {new.scale:.3f})")
                    return Step("hidden", win, new, grab_ms=grab_ms, shape=shape, contrast=contrast, events=events)
            if self.hidden * self.every >= HIDDEN_END_S:
                self.close(events)
                self.match, self.hidden = None, 0
            return Step("hidden", win, match, grab_ms=grab_ms, shape=shape, contrast=contrast, events=events)
        if self.hidden:
            self._write({"event": "panel_visible"})
            self.hidden = 0

        t1 = time.perf_counter()
        f = read_frame(buf, match)
        read_ms = (time.perf_counter() - t1) * 1000
        bad = [n for n, r in f.readings.items() if not r.ok]
        self.fails = self.fails + 1 if len(bad) > 3 else 0

        wall = time.monotonic()
        state = self.tracker.update(f.values, wall)
        if (self._match_clock is not None and state.clock is not None
                and state.clock < self._match_clock - NEW_MATCH_BACK_S):
            # Restarted, or a new match began before the old one was closed:
            # its own session, with the age, alerts and build order from zero.
            self._write({"event": "clock_reset", "from": self._match_clock, "to": state.clock})
            self.close(events)
            self._open_session(events)
            state = self.tracker.update(f.values, wall)
        if state.clock is not None:
            self._match_clock = state.clock
        transitions = self.rules.evaluate(state, wall)
        income = self.income.update(state)
        self.readings += 1

        self._write({
            "t": round(wall, 2),
            "values": f.values,
            "text": {n: r.text for n, r in f.readings.items()},
            "conf": {n: round(r.conf, 3) for n, r in f.readings.items()},
            "prod_score": round(f.production.score, 3),
            "anchor": [match.x, match.y, round(match.scale, 3), round(match.score, 3)],
            "ms": round(grab_ms + read_ms, 1),
            "grab_ms": round(grab_ms, 1),
            "state": state.to_dict(),
            "income": income.to_dict(),
        })
        self._save_frame(buf, state)
        b = self.rules.build
        if b is not None and (b.build.id, b.index) != self._build_step:
            self._build_step = (b.build.id, b.index)
            self._write({"event": "build_step", "build": b.build.id, "name": b.build.name,
                         "step": b.index + 1, "of": len(b.build.steps), "clock": state.clock})
        for tr in transitions:
            a = tr.alert
            self._write({"event": f"alert_{tr.kind}", "id": a.id, "severity": a.severity, "text": a.text, "reason": a.reason})
            events.append(f"alert off: {a.id}" if tr.kind == "off" else f"alert {tr.kind} [{a.severity}]: {a.text}")
        if bad and self.saved_fails < MAX_FAIL_SHOTS:
            Image.fromarray(np.ascontiguousarray(buf)).save(
                self.session / f"fail_{datetime.now():%H%M%S}_{'-'.join(bad)}.png")
            self.saved_fails += 1
        if DOUBT_BAND[0] <= f.production.score <= DOUBT_BAND[1] and self.saved_doubts < MAX_DOUBT_SHOTS:
            # Queue score close to the threshold: keep the image to understand what it is.
            Image.fromarray(np.ascontiguousarray(buf)).save(
                self.session / f"doubt_queue_{datetime.now():%H%M%S}_{f.production.score:.2f}.png")
            self.saved_doubts += 1
        # Low-confidence reads are right most of the time but show where the
        # glyph bank lacks samples: keep one image per (field, text) so they
        # can be labeled (`reeve label`) and become references and tests.
        low = [(n, r.text) for n, r in f.readings.items() if r.ok and r.conf < LOW_CONF]
        new = [k for k in low if k not in self._low_seen]
        if new and len(self._low_seen) < MAX_LOW_SHOTS:
            self._low_seen.update(new)
            tag = "-".join(f"{n}={t.replace('/', 'of')}" for n, t in new)
            Image.fromarray(np.ascontiguousarray(buf)).save(
                self.session / f"doubt_read_{datetime.now():%H%M%S}_{tag}.png")
        return Step("reading", win, match, f, bad, grab_ms, read_ms, shape, contrast, events,
                    state=state, income=income, alerts=self.rules.alerts(), build=self.rules.build)

    def _save_frame(self, buf: np.ndarray, state: GameState) -> None:
        """Small JPEG of the bottom-left capture every FRAME_EVERY_S game
        seconds: lets the report show what was actually read at any point."""
        c = state.clock
        if c is None or not self.cap.rects:
            return
        if self._last_frame_clock is not None and c - self._last_frame_clock < FRAME_EVERY_S:
            return
        self._last_frame_clock = c
        frames = self.session / "frames"
        frames.mkdir(exist_ok=True)
        x, y, w, h = self.cap.rects[0]
        Image.fromarray(np.ascontiguousarray(buf[y:y + h, x:x + w])).save(frames / f"{c:05d}.jpg", quality=70)
        if len(self.cap.rects) > 1:  # top center: clock, age numeral and age-up bar
            x, y, w, h = self.cap.rects[1]
            Image.fromarray(np.ascontiguousarray(buf[y:y + h, x:x + w])).save(frames / f"top_{c:05d}.jpg", quality=80)
