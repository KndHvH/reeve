"""Transparent overlay on top of the game.

Two modes share the same window and engine:
- clean (default): only the active alerts, as small cards; nothing is drawn
  when there is nothing to say.
- debug: what the reader is seeing (anchor, regions with value and
  confidence, production queue) plus a HUD with window, scale, timings, RAM,
  CPU and the active alerts.

- The alert cards show in recordings and streams (a setting, on by default):
  they sit away from the regions that are read, and the stack stops before
  the panel's region. The debug view draws on the read regions, so it is
  always excluded from screen captures (WDA_EXCLUDEFROMCAPTURE), as is the
  whole overlay when the setting is off.
- Clicks pass through (WS_EX_TRANSPARENT) and the window never takes focus,
  so the game stays in the foreground.
- The canvas is only redrawn on each reading (default 2 s); the clean mode
  redraws only when the alerts change. Each alert card is a small window of
  its own (cards.py), so it can fade or slide in, out and into place.
"""

from __future__ import annotations

import ctypes
import time
import tkinter as tk
import traceback
from pathlib import Path

from PIL import Image, ImageTk

from .version import shown as shown_version
from .cards import CardStack, settings as animation_settings
from .digits import MIN_SCORE
from .live import LOW_CONF, LiveReader, Step
from .rules import Alert
from .sound import AlertSounds
from .metrics import CpuMeter, ram_mb
from .paths import ROOT

KEY = "#010203"  # color treated as transparent
# Same visual language as the hub and the report: colors from the chosen
# theme (apply_theme), a classic serif for the alert text. Defaults: Age.
CARD, RULE, FG, MUTED = "#151c25", "#263140", "#ece4d0", "#98a0a8"
ACCENT, ACCENT_DIM, ACCENT_LIGHT = "#c9a45c", "#6b5734", "#ead39a"
GOOD, WARN, BAD, INFO = "#5cc98a", "#f0b429", "#e5484d", "#7fb2c9"
RADIUS = 0          # card corner radius at k = 1 (0: square)
ICON_PLATE = None   # dark plate behind the game icons on light cards (theme's card-icon)
FONT = "Segoe UI"
SERIF = "Palatino Linotype"
ICONS = ROOT / "assets" / "report_icons"

GWL_EXSTYLE = -20
WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x80000, 0x20
WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80, 0x8000000
WDA_NONE, WDA_EXCLUDEFROMCAPTURE = 0x0, 0x11

user32 = ctypes.windll.user32


SEVERITY_COLOR = {"critical": BAD, "warn": WARN, "info": INFO}


def apply_theme(config: dict | None = None) -> None:
    """Takes the colors and corner style of the chosen theme (settings)."""
    global CARD, RULE, FG, MUTED, ACCENT, ACCENT_DIM, ACCENT_LIGHT, GOOD, WARN, BAD, INFO, RADIUS, ICON_PLATE
    from . import themes

    c = themes.colors(themes.current(config)[1])
    # A theme may give the in-game cards colors of their own (card, card-ink).
    CARD, RULE, FG, MUTED = c.get("card", c["panel"]), c["rule"], c.get("card-ink", c["ink"]), c["mist"]
    ICON_PLATE = c.get("card-icon")
    ACCENT, ACCENT_DIM, ACCENT_LIGHT = c["accent"], c["accent-dim"], c["accent-light"]
    GOOD, WARN, BAD, INFO = c["good"], c["warn"], c["critical"], c["info"]
    SEVERITY_COLOR.update(critical=BAD, warn=WARN, info=INFO)
    RADIUS = 8 if themes.corners(config) == "rounded" else 0


def _box(c: tk.Canvas, x0: int, y0: int, x1: int, y1: int, r: int, fill: str) -> int:
    """A filled rectangle, with corners of radius `r` (Tk has no rounded
    rectangle: a smoothed polygon with each corner point doubled)."""
    r = min(r, (x1 - x0) // 2, (y1 - y0) // 2)
    if r <= 0:
        return c.create_rectangle(x0, y0, x1, y1, fill=fill, outline="")
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
           x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return c.create_polygon(pts, fill=fill, outline="", smooth=True)


def _alert_icon(a: Alert) -> str:
    """Game icon shown on an alert card."""
    if a.id == "housed":
        return "pop"
    if a.id == "floating":
        return next(iter(a.reason.get("over", {})), "gold")
    return "villager"


def _status_color(s: Step | None) -> str:
    """Watermark dot: grey = no game / menu / waiting, red = error or a failed
    field, yellow = some field with low confidence, green = all good."""
    if s is None:
        return BAD
    if s.status != "reading":
        return MUTED
    if s.bad:
        return BAD
    if min(r.conf for r in s.frame.readings.values()) < LOW_CONF:
        return WARN
    return GOOD


def _conf_color(c: float) -> str:
    return GOOD if c >= 0.85 else WARN if c >= MIN_SCORE else BAD


class Overlay:
    """Window, engine loop and both views. The mode, pause, mute and quit are
    plain attributes so the tray (another thread) can change them; the Tk loop
    in the main thread picks them up on the next tick."""

    def __init__(self, every: float, mute: bool = False, debug: bool = False):
        self.every = every
        self.debug = debug          # debug view vs clean alert cards
        self.enabled = True         # False: paused, nothing read or drawn
        self.quit_requested = False
        self._shown = None          # clean view: last drawn signature
        apply_theme()
        self.live = LiveReader(every)
        self.muted = mute           # tray mute, on top of the config's sound switch
        self._config_stamp = self._config_mtime()
        self._apply_sounds()
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
        self.cards = CardStack(self.root, KEY, self._setup_card_window, self._paint_card)
        self.cards.effects = animation_settings(self.live.rules.config)
        self.geom = None
        self.last_events: list[str] = []
        self.last_status = "no_game"
        # First-run and environment notices; the tray replaces `notify` with
        # its notifications, the bare overlay prints them.
        from .checks import Notices

        self.notices = Notices()
        self.notify = lambda title, message: print(f"{title}: {message}")
        self._icon_cache: dict[tuple[str, int], ImageTk.PhotoImage] = {}
        self.root.after(100, self.tick)

    @staticmethod
    def _config_mtime() -> float:
        from .paths import user_config_path

        p = user_config_path()
        return p.stat().st_mtime if p.exists() else 0.0

    def _apply_sounds(self) -> None:
        cfg = dict(self.live.rules.config.get("sound", {}))
        if self.muted:
            cfg["enabled"] = False
        self.sounds = AlertSounds(cfg)

    def set_muted(self, muted: bool) -> None:
        self.muted = muted
        self.sounds.enabled = not muted and self.live.rules.config.get("sound", {}).get("enabled", True)

    def _reload_config_if_changed(self) -> None:
        """Settings saved in the hub apply without restarting: the rule
        thresholds change in place (active alerts are kept) and the sounds are
        rebuilt."""
        stamp = self._config_mtime()
        if stamp != self._config_stamp:
            from .rules import load_config

            self._config_stamp = stamp
            self.live.rules.config = load_config()
            apply_theme(self.live.rules.config)
            self.cards.effects = animation_settings(self.live.rules.config)
            self._apply_sounds()
            self._shown = None

    @staticmethod
    def _click_through(win: tk.Misc) -> int:
        """Clicks pass through, no taskbar button, never takes focus; returns the hwnd."""
        hwnd = user32.GetParent(win.winfo_id())
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                              style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        return hwnd

    def _win32_setup(self) -> bool:
        self.hwnd = self._click_through(self.root)
        return self._set_excluded(True)

    def _setup_card_window(self, win: tk.Toplevel) -> int:
        hwnd = self._click_through(win)
        user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE if self.excluded else WDA_NONE)
        return hwnd

    def _set_excluded(self, excluded: bool) -> bool:
        """Hides the overlay and its cards from screen captures (recordings,
        streams, and Reeve's own reading) or shows them; returns whether hidden."""
        mode = WDA_EXCLUDEFROMCAPTURE if excluded else WDA_NONE
        ok = user32.SetWindowDisplayAffinity(self.hwnd, mode)
        for hwnd in (self.cards.windows() if hasattr(self, "cards") else []):
            user32.SetWindowDisplayAffinity(hwnd, mode)
        return excluded if ok else not excluded

    def _sync_capture(self) -> None:
        """The debug view always stays out of captures (it draws on the read
        regions); the alert cards show in recordings unless the setting is off."""
        show = (self.live.rules.config.get("overlay") or {}).get("show_in_recordings", True)
        want = self.debug or not show
        if want != self.excluded:
            self.excluded = self._set_excluded(want)

    # --- loop -------------------------------------------------------------
    def tick(self):
        if self.quit_requested:
            self.root.destroy()
            return
        if not self.enabled:
            self.root.withdraw()
            self.cards.clear()
            self._shown = None
            self.root.after(int(self.every * 1000), self.tick)
            return
        try:
            self._reload_config_if_changed()
            self._sync_capture()
            s = self.live.step()
            self.last_status = s.status   # "reading"/"hidden": a match is open (no update notices)
            if s.events:
                self.last_events = (self.last_events + s.events)[-3:]
            for title, message in self.notices.observe(s):
                self.notify(title, message)
            if s.win is None or s.status == "no_game":
                self.root.withdraw()
                self.cards.clear()
            else:
                g = (s.win.width, s.win.height, s.win.left, s.win.top)
                if g != self.geom:
                    self.root.geometry("{}x{}+{}+{}".format(*g))
                    self.geom = g
                self.root.deiconify()
                self.draw(s)
            # Sounds follow what is on screen: nothing while in a menu or alt-tabbed.
            self.sounds.update(s.alerts if s.status == "reading" else [], time.monotonic())
        except Exception:
            # Keep running: an unexpected error shows as a red dot instead of
            # silently stopping the overlay.
            traceback.print_exc()
            self._show_error()
        finally:
            self.root.after(int(self.every * 1000), self.tick)

    def _show_error(self) -> None:
        self.cards.clear()
        self.canvas.delete("all")
        self._shown = None
        self._draw_watermark(1.0, BAD)

    def run(self):
        try:
            self.root.mainloop()
        finally:
            self.live.close()

    def draw(self, s: Step):
        if self.debug:
            self._shown = None
            self.cards.clear()
            self._draw_debug(s)
        else:
            self._draw_clean(s)

    def _draw_watermark(self, k: float, color: str) -> None:
        """Tiny "reeve <version>" tag in the top-left corner, above the game's
        own icons; the dot carries the state (see _status_color)."""
        c = self.canvas
        x, y = round(5 * k), round(2 * k)
        r = max(2, round(2 * k))
        t = c.create_text(x + 2 * r + round(3 * k), y, text=f"reeve {shown_version()}", fill=MUTED,
                          anchor="nw", font=(FONT, max(5, round(4 * k))))
        x0, y0, x1, y1 = c.bbox(t)
        cy = (y0 + y1) // 2
        bg = _box(c, x - 2, y0, x1 + 3, y1, round(RADIUS * k / 2), CARD)
        c.create_oval(x + 1, cy - r, x + 1 + 2 * r, cy + r, fill=color, outline="")
        c.tag_lower(bg, t)

    def _icon(self, name: str, height: int) -> ImageTk.PhotoImage | None:
        """Game icon scaled to `height` px (cached; transparent edges blend with the card)."""
        key = (name, height)
        if key not in self._icon_cache:
            path = ICONS / f"{name}.png"
            if not path.exists():
                return None
            im = Image.open(path).convert("RGBA")
            w = max(1, round(im.width * height / im.height))
            self._icon_cache[key] = ImageTk.PhotoImage(im.resize((w, height), Image.LANCZOS))
        return self._icon_cache[key]

    def _card_limit(self, x0: int) -> int | None:
        """Never reach the bottom-left region that is read (the cards may be
        visible to screen capture): the stack stops above it."""
        rects = getattr(getattr(getattr(self, "live", None), "cap", None), "rects", None) or []
        return min((ry for rx, ry, rw, rh in rects if rx < x0 + 1), default=None)

    def _paint_card(self, c: tk.Canvas, a: Alert, x0: int, y: int) -> tuple[int, int]:
        """One alert card at (x0, y): severity bar, game icon and the alert
        text on the theme's card color (no outline). Returns its right and
        bottom edges. Sized by self._k and self._fs, set by the caller."""
        k, fs = self._k, self._fs
        pad, bar_w = round(8 * k), round(4 * k)
        icon_h = round((fs + 2) * 1.9)
        icon = self._icon(_alert_icon(a), icon_h)
        tx = x0 + bar_w + pad
        if icon is not None:
            # The icons are cropped from the game's dark panel and keep dark
            # edges: on a light card they sit on a small dark plate, as in game.
            # Every plate has the same size (the widest icon's), the icon centered on it.
            if ICON_PLATE:
                m = round(3 * k)
                side = round(icon_h * 1.2) + 2 * m
                _box(c, tx, y + pad - m, tx + side, y + pad + icon_h + m, round(RADIUS * k / 2), ICON_PLATE)
                c.create_image(tx + side // 2, y + pad + icon_h // 2, image=icon, anchor="center")
                tx += side + round(6 * k)
            else:
                c.create_image(tx, y + pad, image=icon, anchor="nw")
                tx += icon.width() + round(6 * k)
        t = c.create_text(tx, y + pad + icon_h // 2, text=a.text, fill=FG, anchor="w",
                          font=(SERIF, fs + 2, "bold"))
        _, _, x1, _ = c.bbox(t)
        y1 = y + pad + icon_h
        # The severity color fills the whole card shape; the card sits on top
        # from the bar's width on, rounded on the right and straight on the
        # left, so the bar is a strip that follows the outer corners.
        r = round(RADIUS * k)
        card = _box(c, x0 + bar_w, y, x1 + pad, y1 + pad, r, CARD)
        square = c.create_rectangle(x0 + bar_w, y, x0 + bar_w + r, y1 + pad, fill=CARD, outline="")
        bar = _box(c, x0, y, x1 + pad, y1 + pad, r, SEVERITY_COLOR[a.severity])
        for item in (square, card, bar):
            c.tag_lower(item)
        return x1 + pad, y1 + pad

    def _draw_alerts(self, alerts: list[Alert], x0: int, y0: int, k: float, fs: int) -> None:
        """Debug view: the cards drawn on the overlay's canvas, stacked down from (x0, y0)."""
        self._k, self._fs = k, fs
        gap, limit, y = round(6 * k), self._card_limit(x0), y0
        height = 2 * round(8 * k) + round((fs + 2) * 1.9)
        for a in alerts:
            if limit is not None and y + height > limit - gap:
                break
            _, y1 = self._paint_card(self.canvas, a, x0, y)
            y = y1 + gap

    # --- clean view: only the alerts, redrawn only when they change --------
    def _draw_clean(self, s: Step):
        alerts = s.alerts if s.status == "reading" else []
        k = s.match.scale if s.match else 1.0
        sig = (self.geom, _status_color(s), CARD, MUTED, RADIUS, k)
        if sig != self._shown:                   # the watermark: redrawn only when it changes
            self._shown = sig
            self.canvas.delete("all")
            self._draw_watermark(k, sig[1])
        self._k, self._fs = k, max(8, round(8 * k))
        x0 = round(16 * k)
        look = (CARD, FG, RADIUS, tuple(SEVERITY_COLOR.items()), k)
        self.cards.update(alerts, (s.win.left, s.win.top), x0, round(s.win.height * 0.16), round(6 * k),
                          self._card_limit(x0), look)


    # --- debug view ---------------------------------------------------------
    def _draw_debug(self, s: Step):
        c = self.canvas
        c.delete("all")
        k = s.match.scale if s.match else 1.0
        fs = max(8, round(8 * k))
        self._draw_watermark(k, _status_color(s))
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
            ("Reeve · debug", FG, True),
            (status[0], status[1], False),
            (f"window {s.win.width}×{s.win.height}", MUTED, False),
        ]
        if s.match:
            lines.append((f"UI {s.match.scale:.2f}× · anchor {s.match.score:.2f}", MUTED, False))
        if s.status == "reading":
            lines.append((f"read {s.read_ms:.0f} ms · capture {s.grab_ms:.0f} ms · every {self.every:g} s", MUTED, False))
            if s.income:
                fmt = lambda v: "–" if v is None else f"{v:.0f}"
                pm, pv = s.income.per_min, s.income.per_villager
                lines.append(("income/min " + " · ".join(f"{r[0].upper()} {fmt(pm[r])}" for r in pm), FG, False))
                lines.append(("per villager " + " · ".join(f"{r[0].upper()} {fmt(pv[r])}" for r in pv), MUTED, False))
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
        c.create_rectangle(x0, y0, x0 + width, y0 + height, fill=CARD, outline=ACCENT_DIM)
        c.create_rectangle(x0 + 1, y0 + 1, x0 + 3, y0 + height, fill=ACCENT, outline="")
        for i, (text, color, bold) in enumerate(lines):
            c.create_text(x0 + pad + 4, y0 + pad + i * lh + lh // 2, text=text, fill=ACCENT_LIGHT if bold else color,
                          anchor="w", font=(SERIF, fs + 2, "bold") if bold else (FONT, fs))
        return y0 + height


def run(every: float, debug: bool = False, mute: bool = False) -> None:
    Overlay(every, mute, debug).run()
