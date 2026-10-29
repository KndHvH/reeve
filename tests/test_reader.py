import numpy as np
import pytest
from PIL import Image

from aoe4ov.glyphs import FIXTURES as FIXTURES_DIR
from aoe4ov.glyphs import bank_from, labeled_fixtures
from aoe4ov.reader import _clock_y_hint, clock_seconds, read_frame

FIXTURES = labeled_fixtures()
IDS = [p.stem for p, _ in FIXTURES]


def _fixture(stem):
    """Fixture by name: tests with fixed coordinates must not depend on file order."""
    return next((p, lab) for p, lab in FIXTURES if p.stem == stem)


def _rgb(png):
    return np.asarray(Image.open(png).convert("RGB"))


@pytest.mark.parametrize("i", range(len(FIXTURES)), ids=IDS)
def test_reads_fixture_leave_one_out(i):
    """Read each capture with a glyph bank that does NOT contain its own glyphs:
    measures real generalization, not memorization."""
    png, label = FIXTURES[i]
    bank = bank_from(FIXTURES[:i] + FIXTURES[i + 1:])
    _clock_y_hint.clear()
    f = read_frame(_rgb(png), bank=bank)
    got = {name: r.text for name, r in f.readings.items()}
    want = {name: label[name].replace(":", "") for name in got}
    assert got == want
    assert all(r.ok for r in f.readings.values())
    assert f.values["producing_villager"] == label["producing_villager"]


@pytest.mark.parametrize("i", range(len(FIXTURES)), ids=IDS)
def test_parsed_values_with_shipped_bank(i):
    png, label = FIXTURES[i]
    _clock_y_hint.clear()  # each capture on its own: a band cached from another one can be off
    f = read_frame(_rgb(png))
    a, b = label["pop"].split("/")
    assert f.values["pop"] == (int(a), int(b))
    assert f.values["clock"] == clock_seconds(label["clock"].replace(":", ""))
    for name in ["idle", "food", "wood", "gold", "stone", "vil_food", "vil_wood", "vil_gold", "vil_stone"]:
        assert f.values[name] == int(label[name]), name


def test_clock_moved_down_is_still_found():
    """On age-up the clock moves down: simulate it by shifting the image 12 px."""
    png, label = _fixture("720p_0036")
    rgb = _rgb(png).copy()
    top = rgb[60:100].copy()
    rgb[72:112] = top
    rgb[60:72] = rgb[59:60]
    _clock_y_hint.clear()
    f = read_frame(rgb)
    assert f.values["clock"] == clock_seconds(label["clock"].replace(":", ""))


@pytest.mark.parametrize(
    "digits,secs",
    [("0036", 36), ("0217", 137), ("1000", 600), ("10217", 3737), ("0060", None), ("123", None), ("7", None)],
)
def test_clock_seconds(digits, secs):
    assert clock_seconds(digits) == secs


@pytest.mark.parametrize("tint", [(1.0, 0.85, 0.2), (1.0, 0.25, 0.2)], ids=["yellow", "red"])
def test_pop_colored_near_cap(tint):
    """Population turns yellow near the cap and red at the cap."""
    from aoe4ov.anchor import detect, project_rois, to_gray

    png, label = _fixture("720p_0036")
    rgb = _rgb(png).astype(np.float32)
    m = detect(to_gray(rgb))
    x, y, w, h = project_rois(m, rgb.shape[1])["pop"]
    rgb[y:y + h, x:x + w] *= np.array(tint, np.float32)
    f = read_frame(rgb.astype(np.uint8), m)
    a, b = label["pop"].split("/")
    assert f.values["pop"] == (int(a), int(b))


def test_label_validation_rejects_empty_and_malformed():
    from aoe4ov.label import FIELDS, validate

    good = {"clock": "04:12", "pop": "9/10", "idle": "8", "food": "50", "wood": "150", "gold": "100", "stone": "0",
            "vil_food": "0", "vil_wood": "0", "vil_gold": "0", "vil_stone": "0"}
    assert validate(good) == []
    assert len(validate({n: "" for n in FIELDS})) == len(FIELDS)
    assert validate(good | {"pop": "910"}) == ["Population"]
    assert validate(good | {"clock": "4:72"}) == ["Clock"]


@pytest.mark.parametrize("name", ["queue_military_units.png", "queue_blocked_housed.png", "queue_tech_and_units.png"])
def test_non_villager_queue_icons_are_not_villagers(name):
    """Military units, technologies and production blocked by housing have
    human figures that scored 0.57–0.63 on shape alone (live session); the
    icon's background color rules them out."""
    from aoe4ov.anchor import detect, to_gray
    from aoe4ov.production import detect_villager_in, region

    rgb = _rgb(FIXTURES_DIR / name)
    m = detect(to_gray(rgb))
    x, y, w, h = region(m, rgb.shape)
    assert not detect_villager_in(rgb[y:y + h, x:x + w], (x, y), m).villager


def test_two_digit_villager_counts():
    """Villager counts above 9 touched the old 20 px region and lost a digit
    live (23 read as 3, 14 as 1). Values checked by eye on this capture."""
    f = read_frame(_rgb(FIXTURES_DIR / "vil_two_digits.png"))
    got = {k: f.values[k] for k in ("idle", "vil_food", "vil_wood", "vil_gold", "vil_stone")}
    assert got == {"idle": 34, "vil_food": 23, "vil_wood": 13, "vil_gold": 2, "vil_stone": 0}
