"""The build order panel: previous, current and next step, on the right of the screen.

Each step is a card of its own (cards.CardStack, as the alert cards), on the
right edge of the game: when a step is reached the previous one leaves, the
others move up and the next one comes in, with the alert cards' animations.
A step is a block: its age and planned time, the villager count and the five
villager places (food, wood, gold, stone, builder), then its notes with
aoe4guides' icons inline, wrapped to the panel's width. The current step
stands out (accent bar, full ink); the other two are dimmed.
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


def _fmt(t: int | None) -> str:
    return "" if t is None else f"{t // 60}:{t % 60:02d}"


@dataclass(frozen=True)
class StepCard:
    id: str            # build id and step index: a step keeps its card as the build advances
    step: BuildStep
    current: bool

    @property
    def sig(self):
        return self.current


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
        self._k, self._look = 1.0, {}
        self._images: dict[tuple, ImageTk.PhotoImage] = {}
        self._fonts: dict[tuple, tkfont.Font] = {}

    def windows(self) -> list[int]:
        return self.stack.windows()

    def hide(self) -> None:
        self.stack.clear()

    def update(self, tracker, origin: tuple[int, int], game_width: int, margin: int, top: int, k: float,
               look: dict, show_prev: bool = True, show_next: bool = True) -> None:
        """Shows the tracker's steps on the right of the game window at
        `origin` (its top-left on screen), `margin` from its right edge and
        from `top` down, under a card with where the rally point goes;
        `look`: theme colors and radius. A finished build leaves the screen."""
        if tracker is None:
            self.hide()
            return
        prev, cur, nxt = tracker.window()
        i, bid = tracker.index, tracker.build.id
        rally = tracker.rally()
        cards = ([RallyCard(f"{bid}:rally:{rally}", rally)] if rally else []) +                 ([StepCard(f"{bid}:{i - 1}", prev, False)] if prev and show_prev else []) +                 [StepCard(f"{bid}:{i}", cur, True)] +                 ([StepCard(f"{bid}:{i + 1}", nxt, False)] if nxt and show_next else [])
        if tracker.finished:
            cards = []
        self._k, self._look = k, look
        self.stack.update(cards, origin, margin, top, round(5 * k), None, (round(k, 3), tuple(sorted(look.items()))),
                          right=game_width)

    def _paint_card(self, c: tk.Canvas, card, x: int, y: int) -> tuple[int, int]:
        if isinstance(card, RallyCard):
            return self._rally(c, card.target, x, y, self._k, self._look)
        width = round(WIDTH * self._k)
        return x + width, self._block(c, card.step, card.current, x, y, width, self._k, self._look)

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

