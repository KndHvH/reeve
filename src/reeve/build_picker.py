"""The build order picker shown over the game's menus.

While AoE4 is in front but no match is read (menus, lobby, loading and end
screens), a small card on the right shows the build order in use; clicking
it lists the imported builds and "None", and a click on one makes it the
build in use (saved like the hub's settings). Unlike the rest of the
overlay this window takes clicks, but never the focus (WS_EX_NOACTIVATE),
so the game stays in front; it is hidden from screen captures.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont

WIDTH = 230       # at k = 1
NONE_LABEL = "None"


def elide(text: str, width: int, measure) -> str:
    """`text` cut to fit `width` pixels with an ellipsis; `measure(text)` gives
    its width. Long build names otherwise wrap and spill over the next rows."""
    if measure(text) <= width:
        return text
    lo, hi = 0, len(text)
    while lo < hi:   # the longest prefix that fits with the ellipsis
        mid = (lo + hi + 1) // 2
        if measure(text[:mid].rstrip() + "…") <= width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + "…"


class BuildPicker:
    def __init__(self, root: tk.Tk, key: str, setup_window, box):
        """`setup_window(win)` makes it a no-focus tool window (returns its
        hwnd); `box` draws a block (overlay._box)."""
        self.root, self.key, self.setup_window, self.box = root, key, setup_window, box
        self.win: tk.Toplevel | None = None
        self.hwnd: int | None = None
        self.canvas: tk.Canvas | None = None
        self.open = False
        self.hover: int | None = None
        self._rows: list[tuple[int, int, str | None]] = []   # (y0, y1, build id) of each clickable row
        self._sig = None
        self._args = None
        self._fonts: dict[tuple, tkfont.Font] = {}

    def windows(self) -> list[int]:
        return [self.hwnd] if self.hwnd else []

    def _ensure(self) -> None:
        if self.win is not None:
            return
        w = tk.Toplevel(self.root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.attributes("-transparentcolor", self.key)
        w.configure(bg=self.key)
        self.canvas = tk.Canvas(w, bg=self.key, highlightthickness=0, cursor="hand2")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<Motion>", self._move)
        self.canvas.bind("<Leave>", lambda _e: self._set_hover(None))
        w.update_idletasks()
        self.hwnd = self.setup_window(w)
        self.win = w

    def hide(self) -> None:
        if self.win is not None:
            self.win.withdraw()
        self.open, self.hover, self._sig = False, None, None

    def update(self, builds: list, active: str | None, right: int, top: int, k: float, look: dict) -> None:
        """`builds`: (id, name, civ) of the imported builds; (right, top): the
        card's top-right corner on screen."""
        self._ensure()
        self._args = (builds, active, right, top, k, look)
        self._draw()
        self.win.deiconify()

    def _draw(self) -> None:
        builds, active, right, top, k, look = self._args
        sig = (tuple(builds), active, right, top, round(k, 3), tuple(sorted(look.items())), self.open, self.hover)
        if sig == self._sig:
            return
        self._sig = sig
        c = self.canvas
        c.delete("all")
        width, pad = round(WIDTH * k), round(8 * k)
        fs = max(7, round(8 * k))
        small, bold, plain = self._font(fs), self._font(fs + 2, True), self._font(fs + 1)
        r = round(look["radius"] * k)
        names = {b[0]: b[1] for b in builds}

        # The card: what is in use, and the arrow that opens the list.
        y = pad
        c.create_text(pad + round(3 * k), y, text="Build order", fill=look["muted"], anchor="nw", font=small)
        y += small.metrics("linespace")
        current = names.get(active, NONE_LABEL)
        current = elide(current, width - 2 * pad - round(3 * k) - bold.measure("▾") - pad, bold.measure)
        c.create_text(pad + round(3 * k), y, text=current, fill=look["ink"] if active in names else look["muted"],
                      anchor="nw", font=bold)
        c.create_text(width - pad, y + bold.metrics("linespace") // 2, text="▴" if self.open else "▾",
                      fill=look["accent"], anchor="e", font=bold)
        y += bold.metrics("linespace") + pad
        self._rows = [(0, y, "toggle")]

        # The list: None, then every imported build; the one in use is marked.
        if self.open:
            c.create_line(pad, y, width - pad, y, fill=look["rule"])
            lh = round(plain.metrics("linespace") * 1.5)
            for i, (bid, label, sub) in enumerate([(None, NONE_LABEL, "show nothing")] +
                                                  [(b[0], b[1], b[2]) for b in builds]):
                y0 = y + i * lh
                if self.hover == i + 1:
                    c.create_rectangle(round(3 * k), y0, width - round(3 * k), y0 + lh, fill=look["rule"], outline="")
                if bid == active or (bid is None and active not in names):
                    c.create_rectangle(round(3 * k), y0 + round(4 * k), round(6 * k), y0 + lh - round(4 * k),
                                       fill=look["accent"], outline="")
                room = width - 2 * pad - round(3 * k) - (small.measure(sub) + round(6 * k) if sub else 0)
                t = c.create_text(pad + round(3 * k), y0 + lh // 2, text=elide(label, room, plain.measure),
                                  fill=look["ink"], anchor="w", font=plain)
                if sub:
                    x1 = c.bbox(t)[2]
                    c.create_text(x1 + round(6 * k), y0 + lh // 2, text=sub, fill=look["muted"], anchor="w", font=small)
                self._rows.append((y0, y0 + lh, bid))
            y += lh * (len(builds) + 1) + round(4 * k)

        height = y
        bg = self.box(c, 0, 0, width, height, r, look["card"])
        c.tag_lower(bg)
        c.configure(width=width, height=height)
        self.win.geometry(f"{width}x{height}+{right - width}+{top}")

    def _font(self, size: int, bold: bool = False) -> tkfont.Font:
        key = (size, bold)
        if key not in self._fonts:
            self._fonts[key] = tkfont.Font(root=self.root, family="Segoe UI", size=size, weight="bold" if bold else "normal")
        return self._fonts[key]

    def _row_at(self, y: int) -> int | None:
        for i, (y0, y1, _) in enumerate(self._rows):
            if y0 <= y < y1:
                return i
        return None

    def _set_hover(self, i: int | None) -> None:
        if i != self.hover and self._args:
            self.hover = i
            self._draw()

    def _move(self, e) -> None:
        i = self._row_at(e.y)
        self._set_hover(i if i else None)

    def _click(self, e) -> None:
        i = self._row_at(e.y)
        if i is None:
            return
        if i == 0:
            self.open = not self.open
        else:
            from .catalog import ensure_active
            from .paths import set_setting

            set_setting("build_order", "active", self._rows[i][2])
            ensure_active()   # the civilization's units and icons, in the background
            builds, _, *rest = self._args
            self._args = (builds, self._rows[i][2], *rest)
            self.open = False
        self.hover = None
        self._draw()
