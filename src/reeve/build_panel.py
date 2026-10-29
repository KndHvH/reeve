"""The build order panel: previous, current and next step, on the right of the screen.

A click-through window of its own (like each alert card, see cards.py),
redrawn only when the step, the theme or the size changes. Each step is a
block: its age and planned time, the villager count and the five villager
places (food, wood, gold, stone, builder), then its notes with aoe4guides'
icons inline, wrapped to the panel's width. The current step stands out
(accent bar, full ink); the other two are dimmed.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path

from PIL import Image, ImageTk

from .builds import SLOTS, icon_file, tokens
from .paths import ROOT

ICONS = ROOT / "assets" / "report_icons"
ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV"}
WIDTH = 300        # panel width at k = 1
DIM_ALPHA = 0.5    # icons of the previous and next step


def _fmt(t: int | None) -> str:
    return "" if t is None else f"{t // 60}:{t % 60:02d}"


class BuildPanel:
    def __init__(self, root: tk.Tk, key: str, setup_window, box):
        """`box(canvas, x0, y0, x1, y1, radius, fill)` draws a block (overlay._box)."""
        self.root, self.key, self.setup_window, self.box = root, key, setup_window, box
        self.win: tk.Toplevel | None = None
        self.hwnd: int | None = None
        self.canvas: tk.Canvas | None = None
        self._sig = None
        self._pos = None
        self._images: dict[tuple, ImageTk.PhotoImage] = {}
        self._fonts: dict[tuple, tkfont.Font] = {}

    # --- window -------------------------------------------------------------
    def _ensure(self) -> None:
        if self.win is not None:
            return
        w = tk.Toplevel(self.root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.attributes("-transparentcolor", self.key)
        w.configure(bg=self.key)
        self.canvas = tk.Canvas(w, bg=self.key, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        w.update_idletasks()
        self.hwnd = self.setup_window(w)
        self.win = w

    def windows(self) -> list[int]:
        return [self.hwnd] if self.hwnd else []

    def hide(self) -> None:
        if self.win is not None:
            self.win.withdraw()
        self._sig = None

    def update(self, tracker, right: int, top: int, k: float, look: dict,
               show_prev: bool = True, show_next: bool = True) -> None:
        """Shows the tracker's steps with the panel's top-right corner at
        (right, top) in screen coordinates; `look`: theme colors and radius."""
        if tracker is None:
            self.hide()
            return
        self._ensure()
        sig = (tracker.build.id, tracker.index, round(k, 3), tuple(sorted(look.items())), show_prev, show_next)
        if sig != self._sig:
            self._sig = sig
            self._w, self._h = self._paint(tracker, k, look, show_prev, show_next)
            self._pos = None
        pos = (right - self._w, top)
        if pos != self._pos:
            self._pos = pos
            self.win.geometry(f"{self._w}x{self._h}+{pos[0]}+{pos[1]}")
        self.win.deiconify()

    # --- drawing --------------------------------------------------------------
    def _font(self, size: int, bold: bool = False, family: str = "Segoe UI") -> tkfont.Font:
        key = (family, size, bold)
        if key not in self._fonts:
            self._fonts[key] = tkfont.Font(root=self.root, family=family, size=size, weight="bold" if bold else "normal")
        return self._fonts[key]

    def _image(self, path: Path, height: int, dim: bool) -> ImageTk.PhotoImage | None:
        key = (str(path), height, dim)
        if key not in self._images:
            if not path.exists():
                return None
            im = Image.open(path).convert("RGBA")
            w = max(1, round(im.width * height / im.height))
            im = im.resize((w, height), Image.LANCZOS)
            if dim:
                im.putalpha(im.getchannel("A").point(lambda a: round(a * DIM_ALPHA)))
            self._images[key] = ImageTk.PhotoImage(im)
        return self._images[key]

    def _paint(self, tracker, k: float, look: dict, show_prev: bool, show_next: bool) -> tuple[int, int]:
        c = self.canvas
        c.delete("all")
        width, gap = round(WIDTH * k), round(5 * k)
        y = 0
        prev, cur, nxt = tracker.window()
        prev, nxt = prev if show_prev else None, nxt if show_next else None
        for step, current in ((prev, False), (cur, True), (nxt, False)):
            if step is not None:
                y = self._block(c, step, current, 0, y, width, k, look) + gap
        h = max(1, y - gap)
        c.configure(width=width, height=h)
        return width, h

    def _block(self, c: tk.Canvas, step, current: bool, x0: int, y0: int, width: int, k: float, look: dict) -> int:
        """One step; returns its bottom y."""
        pad, bar = round(8 * k), round(3 * k)
        fs = max(7, round(8 * k))
        ink = look["ink"] if current else look["muted"]
        dim = not current
        icon_h = round(fs * 1.9)
        x, xmax = x0 + bar + pad, x0 + width - pad
        items = []

        # Header: age and planned time, then the villager count and its places.
        cy = y0 + pad + icon_h // 2
        items.append(c.create_text(x, cy, text=ROMAN.get(step.age, ""), fill=look["accent"] if current else look["muted"],
                                   anchor="w", font=self._font(fs + 1, True, "Palatino Linotype")))
        x += round(16 * k)
        items.append(c.create_text(x, cy, text=_fmt(step.time), fill=look["muted"], anchor="w", font=self._font(fs)))
        # Fixed columns wide enough for two digits, so the three steps line up.
        icon_w = round(icon_h * 0.8)
        slot_w = icon_w + self._font(fs + 1, True).measure("00") + round(9 * k)
        sx = xmax - slot_w * (len(SLOTS) + 1) + round(9 * k)
        for name, value in [("villager", step.villagers)] + [(s, step.targets[s]) for s in SLOTS]:
            img = self._image(ICONS / f"{name}.png", round(icon_h * 0.72), dim)
            if img is not None:
                items.append(c.create_image(sx + icon_w // 2, cy, image=img, anchor="center"))
            items.append(c.create_text(sx + icon_w + round(2 * k), cy, text="–" if value is None else str(value),
                                       fill=look["muted"] if not value else ink, anchor="w",
                                       font=self._font(fs + 1, name == "villager")))
            sx += slot_w

        # Notes: words and icons, wrapped to the width.
        y = y0 + pad + icon_h + round(4 * k)
        font = self._font(fs + 1)
        lh = max(font.metrics("linespace"), icon_h)
        space = font.measure(" ")
        for note in step.notes:
            x = x0 + bar + pad
            for kind, value in tokens(note):
                pieces = [("icon", value)] if kind == "icon" else [("text", w) for w in value.split()]
                for pk, pv in pieces:
                    img = self._image(icon_file(pv), icon_h, dim) if pk == "icon" else None
                    if pk == "icon" and img is None:      # icon missing: its name instead
                        pk, pv = "text", Path(pv).stem.replace("-", " ")
                    w = img.width() if img is not None else font.measure(pv)
                    if x + w > xmax and x > x0 + bar + pad:
                        x, y = x0 + bar + pad, y + lh
                    if img is not None:
                        items.append(c.create_image(x, y + lh // 2, image=img, anchor="w"))
                    else:
                        items.append(c.create_text(x, y + lh // 2, text=pv, fill=ink, anchor="w", font=font))
                    x += w + space
            y += lh
        y1 = y + pad - round(2 * k)

        r = round(look["radius"] * k)
        if not current:
            c.tag_lower(self.box(c, x0, y0, x0 + width, y1, r, look["card"]))
            return y1
        # As on the alert cards: the accent fills the whole block shape and the
        # block sits on top from the bar's width on, straight on its left side,
        # so the bar runs the full height and follows the rounded corners.
        card = self.box(c, x0 + bar, y0, x0 + width, y1, r, look["card"])
        square = c.create_rectangle(x0 + bar, y0, x0 + bar + r, y1, fill=look["card"], outline="")
        strip = self.box(c, x0, y0, x0 + width, y1, r, look["accent"])
        for item in (square, card, strip):
            c.tag_lower(item)
        return y1

