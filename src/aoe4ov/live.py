"""Live reading of a match: the engine used by `watch` and by the overlay.

Each `step()` runs one cycle: finds the window, calibrates the anchor when
needed, captures only the regions, checks whether the panel is visible
(menu/pause) and reads. It also records the match in sessions/<start>/
(log.jsonl + images of failed readings), so callers only have to display
the result.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from .anchor import MIN_SCORE, AnchorMatch, panel_state
from .capture import Capture
from .reader import Frame, read_frame
from .window import GameWindow, find_game_window

MAX_FAIL_SHOTS = 30  # failure images saved per match
HIDDEN_END_S = 30    # panel hidden for longer than this = end of match
MIN_CONTRAST = 0.7   # anchor contrast ÷ template contrast: game ~0.88; menu/veil 0.03–0.38
DOUBT_BAND = (0.55, 0.72)  # queue score in this band: save the image for analysis
MAX_DOUBT_SHOTS = 20
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


class LiveReader:
    def __init__(self, every: float, sessions_dir: Path = Path("sessions")):
        self.every = every
        self.sessions_dir = sessions_dir
        self.cap = Capture()
        self.match: AnchorMatch | None = None
        self.size: tuple[int, int] | None = None
        self.fails = 0
        self.hidden = 0
        self.session: Path | None = None
        self.log = None
        self.saved_fails = 0
        self.saved_doubts = 0

    # --- session ----------------------------------------------------------
    def _open_session(self, events: list[str]) -> None:
        if self.log is None:
            self.session = self.sessions_dir / f"{datetime.now():%Y%m%d-%H%M%S}"
            self.session.mkdir(parents=True, exist_ok=True)
            self.log = open(self.session / "log.jsonl", "a", encoding="utf-8")
            self.saved_fails = self.saved_doubts = 0
            events.append(f"recording to {self.session}")

    def close(self, events: list[str] | None = None) -> None:
        if self.log:
            self.log.close()
            if events is not None:
                events.append(f"log saved to {self.session}")
        self.session, self.log = None, None

    def _write(self, obj: dict) -> None:
        self.log.write(json.dumps({"wall": f"{datetime.now():%H:%M:%S}", **obj}, ensure_ascii=False) + "\n")
        self.log.flush()

    # --- cycle ------------------------------------------------------------
    def step(self) -> Step:
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

        self._write({
            "values": f.values,
            "text": {n: r.text for n, r in f.readings.items()},
            "conf": {n: round(r.conf, 3) for n, r in f.readings.items()},
            "prod_score": round(f.production.score, 3),
            "anchor": [match.x, match.y, round(match.scale, 3), round(match.score, 3)],
            "ms": round(grab_ms + read_ms, 1),
            "grab_ms": round(grab_ms, 1),
        })
        if bad and self.saved_fails < MAX_FAIL_SHOTS:
            Image.fromarray(np.ascontiguousarray(buf)).save(
                self.session / f"fail_{datetime.now():%H%M%S}_{'-'.join(bad)}.png")
            self.saved_fails += 1
        if DOUBT_BAND[0] <= f.production.score <= DOUBT_BAND[1] and self.saved_doubts < MAX_DOUBT_SHOTS:
            # Queue score close to the threshold: keep the image to understand what it is.
            Image.fromarray(np.ascontiguousarray(buf)).save(
                self.session / f"doubt_queue_{datetime.now():%H%M%S}_{f.production.score:.2f}.png")
            self.saved_doubts += 1
        return Step("reading", win, match, f, bad, grab_ms, read_ms, shape, contrast, events)
