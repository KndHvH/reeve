"""Alert cards as small windows of their own, so each one can be animated.

The overlay's canvas is transparent through a color key, which is all or
nothing per pixel: a card drawn on it cannot fade alone. Here each card is a
borderless, click-through Toplevel; fading is the window's opacity and
moving is its position, so an animation never redraws anything.

Three moments, each with its own effect (settings, overlay.animation):
- enter: a new alert's card appears;
- exit: its alert clears;
- move: the cards below take the freed place (or make room).
Effects: none, short_fade, long_fade, slide. Sliding in comes from the
stack's edge of the game (left for the alert cards, right for the build
order steps) and sliding out goes back there; the window reaches that edge
and the card moves inside it, so it never shows on a neighbouring monitor.
For `move`, a fade fades out, jumps and fades back in.

Cost: a frame every ~15 ms only while something is animating (at most
~0.45 s per change), one opacity or position call per card per frame; the
overlay's 2 s reading loop is unchanged.
"""

from __future__ import annotations

import time
import tkinter as tk
from dataclasses import dataclass
from typing import Callable

EFFECTS = ("none", "short_fade", "long_fade", "slide")
DEFAULTS = {"enter": "slide", "exit": "long_fade", "move": "slide"}
DURATION_S = {"short_fade": 0.15, "long_fade": 0.45, "slide": 0.25}
FRAME_MS = 15


def settings(config: dict | None) -> dict:
    """The effect of each moment; unknown or missing values fall back to the defaults."""
    chosen = ((config or {}).get("overlay") or {}).get("animation") or {}
    return {k: chosen.get(k) if chosen.get(k) in EFFECTS else d for k, d in DEFAULTS.items()}


def ease_out(p: float) -> float:
    """Fast start, gentle stop (cubic)."""
    return 1 - (1 - p) ** 3


def stack_layout(heights: list[int], top: int, gap: int, limit: int | None) -> list[int]:
    """Top of each card, stacked down from `top`; the stack stops before
    `limit` (the region that is read), so it may hold fewer cards."""
    ys, y = [], top
    for h in heights:
        if limit is not None and y + h > limit - gap:
            break
        ys.append(y)
        y += h + gap
    return ys


@dataclass
class Tween:
    apply: Callable[[float], None]
    start_value: float
    end_value: float
    start: float
    duration: float
    done: Callable[[], None] | None = None

    def step(self, now: float) -> bool:
        """Applies the value for `now`; True when finished."""
        p = 1.0 if self.duration <= 0 else min(1.0, (now - self.start) / self.duration)
        self.apply(self.start_value + (self.end_value - self.start_value) * ease_out(p))
        return p >= 1.0


class Card:
    """One alert card: a Toplevel holding a canvas the card is painted on."""

    def __init__(self, stack: "CardStack"):
        self.win = tk.Toplevel(stack.root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-transparentcolor", stack.key)
        self.win.configure(bg=stack.key)
        self.canvas = tk.Canvas(self.win, bg=stack.key, highlightthickness=0)
        self.canvas.place(x=0, y=0)
        self.win.update_idletasks()
        self.hwnd = stack.setup_window(self.win)
        self.stack = stack
        self.sig = None
        self.w = self.h = 0
        self.y = 0.0            # top, relative to the game window
        self.target = 0         # where it is going (equals y when still)
        self.alpha = 1.0
        self.dx = 0.0           # the card slides inside its window
        self.shown = False

    def paint(self, alert, sig) -> None:
        c = self.canvas
        c.delete("all")
        right = self.stack.side == "right"
        x1, y1 = self.stack.paint(c, alert, 0 if right else self.stack.x0, 0)
        self.h = y1 + 1
        # The window reaches the stack's edge of the game: x0 is the margin there.
        self.w = x1 + 1 + (self.stack.x0 if right else 0)
        c.configure(width=x1 + 1, height=self.h)
        self.sig = sig
        self.place()

    def place(self) -> None:
        left, top = self.stack.origin
        x = left + self.stack.right - self.w if self.stack.side == "right" else left
        self.win.geometry(f"{self.w}x{self.h}+{x}+{top + round(self.y)}")

    def set_y(self, y: float) -> None:
        self.y = y
        self.place()

    def set_alpha(self, a: float) -> None:
        self.alpha = max(0.0, min(1.0, a))
        self.win.attributes("-alpha", self.alpha)

    def set_dx(self, dx: float) -> None:
        self.dx = dx
        self.canvas.place(x=round(dx), y=0)

    def show(self) -> None:
        if not self.shown:
            self.win.deiconify()
            self.shown = True

    def destroy(self) -> None:
        self.win.destroy()


class CardStack:
    """The alert cards on screen, kept in step with the active alerts.

    `paint(canvas, item, x, y) -> (right, bottom)` draws one card;
    `setup_window(toplevel) -> hwnd` makes a window click-through and applies
    the capture setting. Positions are relative to the game window. Items
    have an `id`; `signature(item)` tells when a card must be repainted
    (an alert's severity and text by default). `side`: the game edge the
    cards sit at and slide from ("left", or "right" with `right` set to
    the game window's width on each update)."""

    def __init__(self, root: tk.Tk, key: str, setup_window, paint, side: str = "left",
                 signature=lambda a: (a.severity, a.text)):
        self.root, self.key = root, key
        self.setup_window, self.paint = setup_window, paint
        self.side, self.signature = side, signature
        self.right = 0
        self.effects = dict(DEFAULTS)
        self.cards: dict[str, Card] = {}
        self.leaving: list[Card] = []
        self.tweens: dict[tuple[int, str], Tween] = {}
        self.origin = (0, 0)
        self.x0 = 0
        self._running = False

    # --- public -----------------------------------------------------------
    def windows(self) -> list[int]:
        return [c.hwnd for c in [*self.cards.values(), *self.leaving]]

    def update(self, alerts: list, origin: tuple[int, int], x0: int, top: int, gap: int,
               limit: int | None, look, right: int = 0) -> None:
        """Shows `alerts` (in order) as cards stacked down from (x0, top).
        `look` changes when the theme or scale does, to repaint every card.
        Cheap when nothing changed: no drawing, no window call."""
        now = time.monotonic()
        if origin != self.origin or x0 != self.x0 or right != self.right:
            self.origin, self.x0, self.right = origin, x0, right
            for c in self.cards.values():
                c.sig = None                      # repaint at the new place
        wanted = {a.id: a for a in alerts}
        for aid in [aid for aid in self.cards if aid not in wanted]:
            self._exit(self.cards.pop(aid), now)
        fresh: dict[str, Card] = {}
        for a in alerts:
            card = self.cards.get(a.id)
            if card is None:
                card = fresh[a.id] = Card(self)
            sig = (self.signature(a), look)
            if card.sig != sig:
                card.paint(a, sig)
        ordered = [self.cards.get(a.id) or fresh[a.id] for a in alerts]
        ys = stack_layout([c.h for c in ordered], top, gap, limit)
        for a, card, y in zip(alerts, ordered, ys):
            if a.id in fresh:
                self.cards[a.id] = card
                self._enter(card, y, now)
            elif y != card.target:
                self._move(card, y, now)
        for a, card in list(zip(alerts, ordered))[len(ys):]:   # no room left
            if a.id in fresh:
                card.destroy()
            else:
                self._exit(self.cards.pop(a.id), now)
        self._kick()

    def clear(self) -> None:
        """Removes every card at once (no game, overlay paused, debug view)."""
        self.tweens.clear()
        for c in [*self.cards.values(), *self.leaving]:
            c.destroy()
        self.cards.clear()
        self.leaving.clear()

    # --- moments ----------------------------------------------------------
    def _enter(self, card: Card, y: int, now: float) -> None:
        card.target = y
        card.set_y(y)
        effect = self.effects["enter"]
        if effect == "slide":
            self._tween(card, "dx", card.set_dx, self._away(card), 0, now, DURATION_S["slide"])
        elif effect in ("short_fade", "long_fade"):
            self._tween(card, "alpha", card.set_alpha, 0.0, 1.0, now, DURATION_S[effect])
        card.show()

    def _exit(self, card: Card, now: float) -> None:
        self._cancel(card)
        self.leaving.append(card)

        def gone():
            self._cancel(card)
            if card in self.leaving:
                self.leaving.remove(card)
            card.destroy()

        effect = self.effects["exit"]
        if effect == "slide":
            self._tween(card, "dx", card.set_dx, card.dx, self._away(card), now, DURATION_S["slide"], gone)
        elif effect in ("short_fade", "long_fade"):
            self._tween(card, "alpha", card.set_alpha, card.alpha, 0.0, now, DURATION_S[effect], gone)
        else:
            gone()

    def _away(self, card: Card) -> int:
        """Where a sliding card is out of sight: past the stack's edge."""
        return card.w if self.side == "right" else -card.w

    def _move(self, card: Card, y: int, now: float) -> None:
        card.target = y
        effect = self.effects["move"]
        if effect == "slide":
            self._tween(card, "y", card.set_y, card.y, y, now, DURATION_S["slide"])
        elif effect in ("short_fade", "long_fade"):
            half = DURATION_S[effect] / 2

            def jump():
                card.set_y(card.target)
                self._tween(card, "alpha", card.set_alpha, 0.0, 1.0, time.monotonic(), half)

            self._tween(card, "alpha", card.set_alpha, card.alpha, 0.0, now, half, jump)
        else:
            card.set_y(y)

    # --- animation loop ---------------------------------------------------
    def _tween(self, card: Card, prop: str, apply, a: float, b: float, now: float, duration: float,
               done=None) -> None:
        tw = Tween(apply, a, b, now, duration, done)
        tw.step(now)                                  # first frame at once: no flash at the end value
        self.tweens[(id(card), prop)] = tw

    def _cancel(self, card: Card) -> None:
        for key in [k for k in self.tweens if k[0] == id(card)]:
            del self.tweens[key]

    def _kick(self) -> None:
        if self.tweens and not self._running:
            self._running = True
            self.root.after(FRAME_MS, self._frame)

    def _frame(self) -> None:
        now = time.monotonic()
        for key, tw in list(self.tweens.items()):
            if self.tweens.get(key) is not tw:
                continue                              # replaced or cancelled during this frame
            try:
                finished = tw.step(now)
            except tk.TclError:                       # its window is gone
                finished, tw.done = True, None
            if finished:
                if self.tweens.get(key) is tw:
                    del self.tweens[key]
                if tw.done:
                    tw.done()
        if self.tweens:
            self.root.after(FRAME_MS, self._frame)
        else:
            self._running = False
