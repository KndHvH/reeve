"""Transparent overlay on top of the game.

Two modes share the same window and engine:
- clean (default): only the active alerts, as small cards; nothing is drawn
  when there is nothing to say.
- debug: what the reader is seeing (anchor, regions with value and
  confidence, production queue) plus a HUD with window, scale, timings, RAM,
  CPU and the active alerts.

- The window is excluded from screen captures (WDA_EXCLUDEFROMCAPTURE),
  otherwise the overlay itself would show up in the image being read. As an
  extra safeguard, nothing is drawn inside the regions that are read.
- Clicks pass through (WS_EX_TRANSPARENT) and the window never takes focus,
  so the game stays in the foreground.
- The canvas is only redrawn on each reading (default 2 s), with no animation;
  the clean mode redraws only when the alerts change.
"""

from __future__ import annotations

import ctypes
import tkinter as tk

from .digits import MIN_SCORE
from .live import LiveReader, Step
from .rules import Alert
from .metrics import CpuMeter, ram_mb

KEY = "#010203"  # color treated as transparent
BG, CARD, FG, MUTED = "#0f1115", "#14171d", "#e6e6e6", "#8b93a1"
GOOD, WARN, BAD, ACCENT = "#3ddc84", "#f5c542", "#ff5c5c", "#4da3ff"
FONT = "Segoe UI"

GWL_EXSTYLE = -20
WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x80000, 0x20
WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80, 0x8000000
WDA_EXCLUDEFROMCAPTURE = 0x11

user32 = ctypes.windll.user32


SEVERITY_COLOR = {"danger": BAD, "warn": WARN, "info": ACCENT}


def _conf_color(c: float) -> str:
    return GOOD if c >= 0.85 else WARN if c >= MIN_SCORE else BAD


class Overlay:
    """Window, engine loop and alert cards shared by both modes."""

    def __init__(self, every: float):
        self.every = every
        self.live = LiveReader(every)
        self.cpu = CpuMeter()
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", KEY)
        self.root.configure(bg=KEY)
        self.canvas = tk.Canvas(self.root, bg=KEY, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.root.update_idletasks()
        self.excluded = self._win32_setup()
        self.geom = None
        self.last_events: list[str] = []
        self.root.after(100, self.tick)

    def _win32_setup(self) -> bool:
        hwnd = user32.GetParent(self.root.winfo_id())
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                              style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        return bool(user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE))

    # --- loop -------------------------------------------------------------
    def tick(self):
        s = self.live.step()
        if s.events:
            self.last_events = (self.last_events + s.events)[-3:]
        if s.win is None or s.status == "no_game":
            self.root.withdraw()
        else:
            g = (s.win.width, s.win.height, s.win.left, s.win.top)
            if g != self.geom:
                self.root.geometry("{}x{}+{}+{}".format(*g))
                self.geom = g
            self.root.deiconify()
            self.draw(s)
        self.root.after(int(self.every * 1000), self.tick)

    def run(self):
        try:
            self.root.mainloop()
        finally:
            self.live.close()

    def draw(self, s: Step):
        raise NotImplementedError

    def _draw_alerts(self, alerts: list[Alert], x0: int, y0: int, k: float, fs: int) -> None:
        """One card per alert, stacked downwards from (x0, y0)."""
        c = self.canvas
        pad, gap = round(8 * k), round(6 * k)
        y = y0
        for a in alerts:
            t = c.create_text(x0 + pad + round(6 * k), y + pad, text=a.text, fill=FG, anchor="nw",
                              font=(FONT, fs + 2, "bold"))
            _, _, x1, y1 = c.bbox(t)
            card = c.create_rectangle(x0, y, x1 + pad, y1 + pad, fill=CARD, outline="#262b33")
            bar = c.create_rectangle(x0, y, x0 + round(4 * k), y1 + pad, fill=SEVERITY_COLOR[a.severity], outline="")
            c.tag_lower(bar, t)
            c.tag_lower(card, bar)
            y = y1 + pad + gap


class CleanOverlay(Overlay):
    """Only the alerts. Redraws only when they change."""

    def __init__(self, every: float):
        self._shown = None
        super().__init__(every)

    def draw(self, s: Step):
        alerts = s.alerts if s.status == "reading" else []
        sig = (tuple((a.id, a.text) for a in alerts), self.geom)
        if sig == self._shown:
            return
        self._shown = sig
        self.canvas.delete("all")
        k = s.match.scale if s.match else 1.0
        self._draw_alerts(alerts, round(16 * k), round(s.win.height * 0.16), k, max(8, round(8 * k)))


class DebugOverlay(Overlay):
    # --- drawing ----------------------------------------------------------
    def draw(self, s: Step):
        c = self.canvas
        c.delete("all")
        k = s.match.scale if s.match else 1.0
        fs = max(8, round(8 * k))
        if s.status == "reading":
            self._draw_detection(s, k, fs)
        bottom = self._draw_hud(s, k, fs)
        if s.status == "reading":
            self._draw_alerts(s.alerts, round(16 * k), bottom + round(8 * k), k, fs)

    def _box(self, x, y, w, h, color, width=1, dash=None):
        # 2 px outside the region: nothing from the overlay falls inside what is read.
        self.canvas.create_rectangle(x - 2, y - 2, x + w + 1, y + h + 1, outline=color, width=width, dash=dash)

    def _draw_detection(self, s: Step, k: float, fs: int):
        c, f, m = self.canvas, s.frame, s.match
        from .anchor import template_box

        self._box(*template_box(m), GOOD, 2)

        for name, (x, y, w, h) in f.rois.items():
            r = f.readings[name]
            self._box(x, y, w, h, _conf_color(r.conf) if r.glyphs else BAD)

        # Values to the right of everything captured, aligned with the panel rows.
        cap_right = max(x + w for x, y, w, h in self.live.cap.rects[:1])
        lx = cap_right + round(10 * k)
        rows = [("pop", "idle", "pop", "idle"), ("food", "vil_food", "food", "villagers"),
                ("wood", "vil_wood", "wood", "villagers"), ("gold", "vil_gold", "gold", "villagers"),
                ("stone", "vil_stone", "stone", "villagers")]
        for a, b, la, lb in rows:
            ra, rb = f.readings[a], f.readings[b]
            va = f.values[a]
            va = f"{va[0]}/{va[1]}" if isinstance(va, tuple) else va
            y = f.rois[a][1] + f.rois[a][3] // 2
            vb = f.values[b]
            text = f"{la} {va if va is not None else '?'} ({ra.conf:.2f})    {lb} {vb if vb is not None else '?'} ({rb.conf:.2f})"
            self._label(lx, y, text, _conf_color(min(ra.conf, rb.conf)), fs)

        x, y, w, h = f.rois["clock"]
        rc = f.readings["clock"]
        secs = f.values["clock"]
        clock = f"{secs // 60:02d}:{secs % 60:02d}" if secs is not None else "--:--"
        self._label(x + w // 2, y + h + round(12 * k), f"clock {clock} ({rc.conf:.2f})", _conf_color(rc.conf), fs, anchor="n")

        p = f.production
        px, py, pw, ph = p.region
        self._box(px, py, pw, ph, MUTED, dash=(4, 3))
        if p.box:
            bx, by, bw, bh = p.box
            self._box(bx, by, bw, bh, GOOD if p.villager else MUTED, 2 if p.villager else 1)
        text = f"villager queued ({p.score:.2f})" if p.villager else f"TC idle? ({p.score:.2f})"
        self._label(lx, py + round(10 * k), text, GOOD if p.villager else WARN, fs)

    def _label(self, x, y, text, color, fs, anchor="w"):
        c = self.canvas
        t = c.create_text(x, y, text=text, fill=color, font=(FONT, fs, "bold"), anchor=anchor)
        x0, y0, x1, y1 = c.bbox(t)
        bg = c.create_rectangle(x0 - 4, y0 - 2, x1 + 4, y1 + 2, fill=CARD, outline="")
        c.tag_lower(bg, t)

    def _draw_hud(self, s: Step, k: float, fs: int) -> int:
        """Draws the HUD card; returns its bottom y."""
        c = self.canvas
        cpu_total, cpu_core = self.cpu.sample()
        status = {
            "waiting": ("waiting for a match", MUTED),
            "hidden": (f"menu/pause · shape {s.shape:.2f} · contrast {s.contrast:.2f}", WARN),
            "reading": ("reading", GOOD),
        }[s.status]
        lines = [
            ("aoe4-overlay · debug", FG, True),
            (status[0], status[1], False),
            (f"window {s.win.width}×{s.win.height}", MUTED, False),
        ]
        if s.match:
            lines.append((f"UI {s.match.scale:.2f}× · anchor {s.match.score:.2f}", MUTED, False))
        if s.status == "reading":
            lines.append((f"read {s.read_ms:.0f} ms · capture {s.grab_ms:.0f} ms · every {self.every:g} s", MUTED, False))
            if s.bad:
                lines.append(("failed: " + ", ".join(s.bad), BAD, False))
        lines.append((f"RAM {ram_mb():.0f} MB · CPU {cpu_total:.1f}% ({cpu_core:.0f}% of 1 core)", MUTED, False))
        if not self.excluded:
            lines.append(("warning: overlay visible in capture", BAD, False))
        for e in self.last_events:
            lines.append((e, MUTED, False))

        x0, y0 = round(16 * k), round(s.win.height * 0.16)
        pad, lh = round(10 * k), round(fs * 1.9)
        width = round(fs * 34)
        height = pad * 2 + lh * len(lines)
        c.create_rectangle(x0, y0, x0 + width, y0 + height, fill=CARD, outline="#262b33")
        c.create_rectangle(x0, y0, x0 + 3, y0 + height, fill=ACCENT, outline="")
        for i, (text, color, bold) in enumerate(lines):
            c.create_text(x0 + pad + 4, y0 + pad + i * lh + lh // 2, text=text, fill=color, anchor="w",
                          font=(FONT, fs + (1 if bold else 0), "bold" if bold else "normal"))
        return y0 + height


def run(every: float, debug: bool = False) -> None:
    (DebugOverlay if debug else CleanOverlay)(every).run()
