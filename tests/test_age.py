"""Age detection on real frames from a full match (I → IV).

The fixtures are top-center crops saved by the live engine; they are pasted
back into a 1920-wide canvas at the position the capture took them from.
"""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from aoe4ov.age import read_age
from aoe4ov.anchor import AnchorMatch
from aoe4ov.state import StateTracker

AGE = Path(__file__).parent / "fixtures" / "age"
SCALE, WIDTH = 1.485, 1920
MATCH = AnchorMatch(9, 1214, SCALE, 0.93)


def _canvas(name):
    crop = np.asarray(Image.open(AGE / name).convert("RGB"))
    canvas = np.zeros((1440, WIDTH, 3), np.uint8)
    x0, y0 = round(WIDTH / 2 - 75 * SCALE), round(12 * SCALE)
    canvas[y0:y0 + crop.shape[0], x0:x0 + crop.shape[1]] = crop
    return canvas


@pytest.mark.parametrize("name,age", [
    ("age1.jpg", 1), ("age2.jpg", 2), ("age3.jpg", 3), ("age4.jpg", 4),
    ("age2_no_bar.jpg", 2), ("age1_no_bar.jpg", 1),
    ("ageup1_92pct_5.jpg", 1), ("ageup2_4pct_9.jpg", 2), ("ageup3_73pct_20.jpg", 3),
])
def test_numeral(name, age):
    assert read_age(_canvas(name), MATCH, WIDTH).age == age


@pytest.mark.parametrize("name,builders", [
    ("ageup1_92pct_5.jpg", 5), ("ageup2_4pct_9.jpg", 9), ("ageup3_73pct_20.jpg", 20),
])
def test_ageup_bar(name, builders):
    """The bar is read on the part common to all civilizations, so only its
    presence matters (the report shows "I → II", not a percentage)."""
    r = read_age(_canvas(name), MATCH, WIDTH)
    assert r.progress is not None
    assert r.builders == builders


@pytest.mark.parametrize("name", ["age1.jpg", "age2_no_bar.jpg", "age1_no_bar.jpg", "age4.jpg", "age2_cattle.jpg"])
def test_no_bar_without_ageup(name):
    assert read_age(_canvas(name), MATCH, WIDTH).progress is None


def test_low_score_frame_gives_no_age_instead_of_a_wrong_one():
    """A building behind the numeral drops the score below the minimum: the
    reader says nothing rather than guessing."""
    assert read_age(_canvas("age1_building_behind.jpg"), MATCH, WIDTH).age in (None, 1)


def test_hard_frame_is_rejected_by_state():
    """Cattle behind the numeral: the single frame may misread (it gave III in
    age II); the state layer must keep age II."""
    t = StateTracker()
    for i, name in enumerate(["age2.jpg", "age2.jpg", "age2_cattle.jpg", "age2.jpg"]):
        a = read_age(_canvas(name), MATCH, WIDTH).age
        st = t.update({"clock": 300 + 2 * i, "age": a}, 2.0 * i)
    assert st.age == 2


def test_age_on_720p_full_frames():
    """Templates are scaled: the 720p captures (scale 1.0) are all in age I."""
    from aoe4ov.anchor import detect, to_gray

    for png in sorted((AGE.parent).glob("720p_*.png")):
        rgb = np.asarray(Image.open(png).convert("RGB"))
        m = detect(to_gray(rgb))
        assert read_age(rgb, m, rgb.shape[1]).age == 1, png.name


def _ages(seq, bars=()):
    t = StateTracker()
    out = []
    for i, a in enumerate(seq):
        up = 0.5 if i in bars else None
        out.append(t.update({"clock": 100 + 2 * i, "age": a, "ageup_progress": up, "ageup_builders": 5 if up else None}, 2.0 * i).age)
    return out


def test_state_age_only_moves_forward_one_step():
    # isolated misreads and an impossible jump; an age-up bar precedes each real step
    seq = [1, 1, 2, 1, 1, 3, 1, 2, 2, 2, 4, 2, 3, 3]
    assert _ages(seq, bars={6, 11}) == [None, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 3]


def test_age_needs_longer_confirmation_without_a_bar():
    """Two consecutive misreads (something parked behind the numeral) must not
    advance the age when no landmark bar was seen."""
    assert _ages([2, 2, 3, 3, 2, 2])[-1] == 2
    assert _ages([2, 2, 3, 3, 3, 3, 3])[-1] == 3   # five reads: accepted (e.g. overlay started mid age-up)


@pytest.mark.parametrize("name,age", [("ageup_no_builders_late.jpg", 1), ("ageup_no_builders_early.jpg", 2)])
def test_ageup_bar_without_builders(name, age):
    """Some civilizations age up without villagers building the landmark: the
    bar has no builder count and is longer. It must still be detected."""
    r = read_age(_canvas(name), MATCH, WIDTH)
    assert r.age == age
    assert r.progress is not None
    assert r.builders is None


def test_empty_bar_at_the_start_of_an_ageup():
    """At the very start the bar is all black track with a sliver of fill;
    it must count as an age-up, not as dark terrain."""
    r = read_age(_canvas("ageup_start_no_builders.jpg"), MATCH, WIDTH)
    assert r.age == 1 and r.progress is not None
