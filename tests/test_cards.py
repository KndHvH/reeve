import time
import tkinter as tk
from types import SimpleNamespace

import pytest

from reeve import cards
from reeve.cards import CardStack, Tween, settings, stack_layout


def test_settings_fall_back_to_defaults():
    assert settings(None) == cards.DEFAULTS
    cfg = {"overlay": {"animation": {"enter": "slide", "exit": "bogus"}}}
    assert settings(cfg) == {"enter": "slide", "exit": "short_fade", "move": "slide"}


def test_stack_stops_before_the_read_region():
    assert stack_layout([20, 20, 20], top=100, gap=5, limit=None) == [100, 125, 150]
    assert stack_layout([20, 20, 20], top=100, gap=5, limit=149) == [100]   # 125 + 20 > 149 - 5


def test_tween_eases_to_the_end_value():
    seen = []
    tw = Tween(seen.append, 0.0, 10.0, start=0.0, duration=1.0)
    assert not tw.step(0.5) and 5 < seen[-1] < 10      # ease out: past halfway at half time
    assert tw.step(2.0) and seen[-1] == 10.0


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    r.withdraw()
    yield r
    r.destroy()


def _alert(aid, text="x"):
    return SimpleNamespace(id=aid, severity="warn", text=text)


def _stack(root, **effects):
    def paint(c, a, x, y):
        c.create_rectangle(x, y, x + 100, y + 30, fill="red")
        return x + 100, y + 30

    s = CardStack(root, "#010203", lambda win: 0, paint)
    s.effects.update(effects)
    return s


def _show(s, *ids):
    s.update([_alert(i) for i in ids], (0, 0), 10, 100, 5, None, "look")


def _finish(s, root):
    deadline = time.monotonic() + 3
    while s.tweens and time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)


def test_cards_enter_move_and_exit_without_animation(root):
    s = _stack(root, enter="none", exit="none", move="none")
    _show(s, "a", "b")
    assert list(s.cards) == ["a", "b"] and s.cards["b"].y == 136 and not s.tweens
    _show(s, "b")                                   # a clears, b takes its place
    assert list(s.cards) == ["b"] and s.cards["b"].y == 100 and not s.leaving


def test_animated_moments_finish_in_place(root):
    s = _stack(root, enter="short_fade", exit="slide", move="slide")
    _show(s, "a", "b")
    assert s.cards["a"].alpha < 1                   # fading in
    _finish(s, root)
    assert s.cards["a"].alpha == 1
    _show(s, "b")
    assert s.leaving and s.cards["b"].target == 100
    _finish(s, root)
    assert not s.leaving and s.cards["b"].y == 100 and not s.tweens


def test_unchanged_alerts_do_nothing(root):
    s = _stack(root, enter="none")
    _show(s, "a")
    card = s.cards["a"]
    card.paint = lambda *a: pytest.fail("repainted an unchanged card")
    _show(s, "a")
    assert not s.tweens


def test_clear_removes_everything_at_once(root):
    s = _stack(root)
    _show(s, "a", "b")
    _show(s, "b")
    s.clear()
    assert not s.cards and not s.leaving and not s.tweens
