"""The build order panel: previous, current and next step, on the right of the screen.

Each step is a card of its own (cards.CardStack, as the alert cards), on the
right edge of the game: when a step is reached the previous one leaves, the
others move up and the next one comes in, with the alert cards' animations.
A step is a block: its age and planned time and the five villager places
(food, wood, gold, stone, builder; empty when none, or a dash by setting), then its notes with
aoe4guides' icons inline, wrapped to the panel's width. The current step
stands out (accent bar, full ink); the other two are dimmed. The current
step's tips (advice the author wrote as steps of their own) follow it in a
card with the info color.
Above them, one row: the arrows that move the build a step by hand,
centered over the steps, and where the rally point goes, at the right edge.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageTk

from .builds import SLOTS, BuildStep, icon_file, tokens
from .cards import CardStack
from .paths import ROOT

ICONS = ROOT / "assets" / "report_icons"
ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV"}
WIDTH = 300        # panel width at k = 1
DIM_ALPHA = 0.5    # icons of the previous and next step


def row_height(k: float) -> int:
    """Height of the panel's top row: the rally card and the step arrows."""
    return 2 * round(6 * k) + round(22 * k)


def _fmt(t: int | None) -> str:
    return "" if t is None else f"{t // 60}:{t % 60:02d}"


@dataclass(frozen=True)
class StepCard:
    id: str            # build id and step index: a step keeps its card as the build advances
    step: BuildStep
    current: bool
    empty_places: bool = False   # places with no villagers show their icon and "-"

    @property
    def sig(self):
        return self.current, self.empty_places


@dataclass(frozen=True)
class TipCard:
    id: str            # build id and step index
    tips: tuple[str, ...]

    @property
    def sig(self):
        return self.tips


@dataclass(frozen=True)
class RallyCard:
    id: str            # changes with the target, so a new rally comes in as a new card
    target: str        # aoe4guides picture the rally point goes on (sheep, wood...)

    @property
    def sig(self):
        return self.target


class BuildPanel:
    def __init__(self, root: tk.Tk, key: str, setup_window, box):
        """`setup_window(toplevel) -> hwnd` makes a card window click-through;
        `box(canvas, x0, y0, x1, y1, radius, fill)` draws a block (overlay._box)."""
        self.root, self.box = root, box
        self.stack = CardStack(root, key, setup_window, self._paint_card, side="right",
                               signature=lambda card: card.sig)
        # The rally card has a stack of its own: it shares the top row with
        # the step arrows (StepControls), at the row's right end.
        self.rally_stack = CardStack(root, key, setup_window, self._paint_card, side="right",
                                     signature=lambda card: card.sig)
        self._k, self._look = 1.0, {}
        self._images: dict[tuple, ImageTk.PhotoImage] = {}
        self._fonts: dict[tuple, tkfont.Font] = {}

    def set_effects(self, effects) -> None:
        self.stack.effects = self.rally_stack.effects = effects

    def windows(self) -> list[int]:
        return self.stack.windows() + self.rally_stack.windows()

    def hide(self) -> None:
        self.stack.clear()
        self.rally_stack.clear()

    def update(self, tracker, origin: tuple[int, int], game_width: int, margin: int, top: int, k: float,
               look: dict, show_prev: bool = True, show_next: bool = True, controls: bool = False,
               empty_places: bool = False, tips: bool = True) -> int | None:
        """Shows the tracker's steps on the right of the game window at
        `origin` (its top-left on screen), `margin` from its right edge and
        from `top` down, under a row with the step arrows (`controls`: shown
        by StepControls) and, at its right end, where the rally point goes;
        `look`: theme colors and radius. A finished build leaves the screen.
        Returns the rally card's left edge in the game window (None without one),
        so the arrows never overlap it. `empty_places`: places with no
        villagers show their icon and a dash instead of nothing; `tips`: the
        current step's tips card."""
        if tracker is None or tracker.finished:
            self.hide()
            return None
        prev, cur, nxt = tracker.window()
        i, bid = tracker.index, tracker.build.id
        rally = tracker.rally()
        steps = (([StepCard(f"{bid}:{i - 1}", prev, False, empty_places)] if prev and show_prev else []) +
                 [StepCard(f"{bid}:{i}", cur, True, empty_places)] +
                 ([TipCard(f"{bid}:{i}:tips", cur.tips)] if cur.tips and tips else []) +
                 ([StepCard(f"{bid}:{i + 1}", nxt, False, empty_places)] if nxt and show_next else []))
        self._k, self._look = k, look
        gap, sig = round(5 * k), (round(k, 3), tuple(sorted(look.items())))
        rally_card = RallyCard(f"{bid}:rally:{rally}", rally) if rally else None
        self.rally_stack.update([rally_card] if rally_card else [], origin, margin, top, gap, None, sig,
                                right=game_width)
        if rally or controls:
            top += row_height(k) + gap
        self.stack.update(steps, origin, margin, top, gap, None, sig, right=game_width)
        shown = self.rally_stack.cards.get(rally_card.id) if rally_card else None
        # A right-side card's window reaches the game's edge: it starts w from it.
        return game_width - shown.w if shown else None

    def _paint_card(self, c: tk.Canvas, card, x: int, y: int) -> tuple[int, int]:
        if isinstance(card, RallyCard):
            return self._rally(c, card.target, x, y, self._k, self._look)
        width = round(WIDTH * self._k)
        if isinstance(card, TipCard):
            return x + width, self._tips(c, card.tips, x, y, width, self._k, self._look)
        return x + width, self._block(c, card.step, card.current, x, y, width, self._k, self._look, card.empty_places)

    def _rally(self, c: tk.Canvas, target: str, x0: int, y0: int, k: float, look: dict) -> tuple[int, int]:
        """Rally point icon, an arrow and what it goes on (its name if the icon is missing)."""
        pad, h = round(6 * k), round(22 * k)
        x, cy = x0 + pad, y0 + pad + h // 2
        flag = self._image(ICONS / "rally.png", h, False)
        if flag is not None:
            c.create_image(x, cy, image=flag, anchor="w")
            x += flag.width() + round(4 * k)
        arrow = c.create_text(x, cy, text="›", fill=look["accent"], anchor="w", font=self._font(max(8, round(12 * k)), True))
        x = c.bbox(arrow)[2] + round(4 * k)
        img = self._image(icon_file(target), h, False)
        if img is not None:
            c.create_image(x, cy, image=img, anchor="w")
            x += img.width()
        else:
            name = c.create_text(x, cy, text=Path(target).stem.replace("-", " "), fill=look["ink"], anchor="w",
                                 font=self._font(max(7, round(9 * k))))
            x = c.bbox(name)[2]
        x1, y1 = x + pad, y0 + 2 * pad + h
        c.tag_lower(self.box(c, x0, y0, x1, y1, round(look["radius"] * k), look["card"]))
        return x1, y1

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

    def _block(self, c: tk.Canvas, step, current: bool, x0: int, y0: int, width: int, k: float, look: dict,
               empty_places: bool = False) -> int:
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
        sx = xmax - slot_w * len(SLOTS) + round(9 * k)
        for name in SLOTS:
            value = step.targets[name]
            shown = bool(value) or empty_places
            img = self._image(ICONS / f"{name}.png", round(icon_h * 0.72), dim) if shown else None
            if img is not None:
                items.append(c.create_image(sx + icon_w // 2, cy, image=img, anchor="center"))
            if shown:
                items.append(c.create_text(sx + icon_w + round(2 * k), cy, text=str(value) if value else "–",
                                           fill=ink if value else look["muted"], anchor="w", font=self._font(fs + 1)))
            sx += slot_w   # an empty place keeps its column, so the steps line up

        y = self._notes(c, step.notes, x0 + bar + pad, xmax, y0 + pad + icon_h + round(4 * k), fs, ink, dim)
        y1 = y + pad - round(2 * k)

        r = round(look["radius"] * k)
        if not current:
            c.tag_lower(self.box(c, x0, y0, x0 + width, y1, r, look["card"]))
            return y1
        self._barred(c, x0, y0, x0 + width, y1, bar, r, look["accent"], look)
        return y1

    def _tips(self, c: tk.Canvas, tips, x0: int, y0: int, width: int, k: float, look: dict) -> int:
        """The current step's tips, under a bar in the info color; returns the bottom y."""
        pad, bar = round(8 * k), round(3 * k)
        fs = max(7, round(8 * k))
        y = self._notes(c, tips, x0 + bar + pad, x0 + width - pad, y0 + pad - round(2 * k), fs, look["ink"], False)
        y1 = y + pad - round(2 * k)
        self._barred(c, x0, y0, x0 + width, y1, bar, round(look["radius"] * k), look.get("info", look["accent"]), look)
        return y1

    def _notes(self, c: tk.Canvas, notes, x_left: int, xmax: int, y: int, fs: int, ink: str, dim: bool) -> int:
        """Notes: words and icons, wrapped to the width; returns the y under them."""
        icon_h = round(fs * 1.9)
        font = self._font(fs + 1)
        lh = max(font.metrics("linespace"), icon_h)
        space = font.measure(" ")
        for note in notes:
            x = x_left
            for kind, value in tokens(note):
                pieces = [("icon", value)] if kind == "icon" else [("text", w) for w in value.split()]
                for pk, pv in pieces:
                    img = self._image(icon_file(pv), icon_h, dim) if pk == "icon" else None
                    if pk == "icon" and img is None:      # icon missing: its name instead
                        pk, pv = "text", Path(pv).stem.replace("-", " ")
                    w = img.width() if img is not None else font.measure(pv)
                    if x + w > xmax and x > x_left:
                        x, y = x_left, y + lh
                    if img is not None:
                        c.create_image(x, y + lh // 2, image=img, anchor="w")
                    else:
                        c.create_text(x, y + lh // 2, text=pv, fill=ink, anchor="w", font=font)
                    x += w + space
            y += lh
        return y

    def _barred(self, c: tk.Canvas, x0: int, y0: int, x1: int, y1: int, bar: int, r: int, color: str,
                look: dict) -> None:
        """The card's block with a colored bar on its left. As on the alert
        cards: the color fills the whole block shape and the block sits on top
        from the bar's width on, straight on its left side, so the bar runs the
        full height and follows the rounded corners."""
        card = self.box(c, x0 + bar, y0, x1, y1, r, look["card"])
        square = c.create_rectangle(x0 + bar, y0, x0 + bar + r, y1, fill=look["card"], outline="")
        strip = self.box(c, x0, y0, x1, y1, r, color)
        for item in (square, card, strip):
            c.tag_lower(item)



class StepControls:
    """Two arrows centered above the build panel ("‹ 4 / 14 ›") that move the
    build a step back or forward when the villager count got it wrong. Like the
    build picker it takes clicks but never the focus; like the cards it shows in
    recordings unless that setting is off."""

    def __init__(self, root: tk.Tk, key: str, setup_window, box, on_move):
        """`on_move("back" | "forward")` moves the build."""
        self.root, self.key, self.setup_window, self.box, self.on_move = root, key, setup_window, box, on_move
        self.win: tk.Toplevel | None = None
        self.hwnd: int | None = None
        self.canvas: tk.Canvas | None = None
        self._sig = None
        self._split = (0, 0)     # x where the back arrow ends and the forward one starts
        self._width = 0
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
        w.update_idletasks()
        self.hwnd = self.setup_window(w)
        self.win = w

    def hide(self) -> None:
        if self.win is not None and self._sig is not None:
            self.win.withdraw()
        self._sig = None

    def update(self, tracker, center: int, top: int, k: float, look: dict, max_right: int | None = None) -> int:
        """Centered on `center` (screen x) at `top`, in the panel's top row (as
        tall as the rally card), never past `max_right` (the rally card's left
        edge, less a gap). Returns its width, 0 when hidden."""
        if tracker is None or tracker.finished:
            self.hide()
            return 0
        self._ensure()
        n = len(tracker.build.steps)
        sig = (tracker.index, n, center, top, max_right, round(k, 3), tuple(sorted(look.items())))
        if sig == self._sig:
            return self._width
        self._sig = sig
        c = self.canvas
        c.delete("all")
        pad, gap = round(6 * k), round(10 * k)
        arrow, text = self._font(max(9, round(13 * k)), True), self._font(max(7, round(8 * k)))
        label = f"{tracker.index + 1} / {n}"
        aw = arrow.measure("‹") + 2 * pad
        width = self._width = 2 * aw + text.measure(label) + 2 * gap
        height = row_height(k)
        cy = height // 2
        back = tracker.index > 0
        fwd = tracker.index + 1 < n
        c.create_text(aw // 2, cy, text="‹", fill=look["accent"] if back else look["muted"], font=arrow)
        c.create_text(width // 2, cy, text=label, fill=look["muted"], font=text)
        c.create_text(width - aw // 2, cy, text="›", fill=look["accent"] if fwd else look["muted"], font=arrow)
        self._split = (aw + gap // 2, width - aw - gap // 2)
        c.tag_lower(self.box(c, 0, 0, width, height, round(look["radius"] * k), look["card"]))
        c.configure(width=width, height=height)
        left = center - width // 2
        if max_right is not None:
            left = min(left, max_right - width)
        self.win.geometry(f"{width}x{height}+{left}+{top}")
        self.win.deiconify()
        return width

    def _font(self, size: int, bold: bool = False) -> tkfont.Font:
        key = (size, bold)
        if key not in self._fonts:
            self._fonts[key] = tkfont.Font(root=self.root, family="Segoe UI", size=size, weight="bold" if bold else "normal")
        return self._fonts[key]

    def _click(self, e) -> None:
        if e.x < self._split[0]:
            self.on_move("back")
        elif e.x >= self._split[1]:
            self.on_move("forward")
