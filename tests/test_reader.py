import numpy as np
import pytest
from PIL import Image

from aoe4ov.glyphs import bank_from, labeled_fixtures
from aoe4ov.reader import _clock_y_hint, clock_seconds, read_frame

FIXTURES = labeled_fixtures()
IDS = [p.stem for p, _ in FIXTURES]


def _rgb(png):
    return np.asarray(Image.open(png).convert("RGB"))


@pytest.mark.parametrize("i", range(len(FIXTURES)), ids=IDS)
def test_reads_fixture_leave_one_out(i):
    """Lê cada captura com um banco de glifos que NÃO contém os glifos dela:
    mede generalização de verdade, não memorização."""
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
    f = read_frame(_rgb(png))
    a, b = label["pop"].split("/")
    assert f.values["pop"] == (int(a), int(b))
    assert f.values["clock"] == clock_seconds(label["clock"].replace(":", ""))
    for name in ["idle", "food", "wood", "gold", "stone", "vil_food", "vil_wood", "vil_gold", "vil_stone"]:
        assert f.values[name] == int(label[name]), name


def test_clock_moved_down_is_still_found():
    """Na troca de era o relógio desce: simula deslocando a imagem 12 px."""
    png, label = FIXTURES[0]
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
