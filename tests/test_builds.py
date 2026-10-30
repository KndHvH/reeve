import io
import json
from pathlib import Path

import pytest
from PIL import Image

from reeve import builds
from reeve.builds import BuildTracker, describe, id_from_url, instructions, parse, tokens
from reeve.rules import RuleEngine
from reeve.state import GameState

MALI = Path(__file__).parent / "fixtures" / "builds" / "mali.json"


def _mali():
    return parse(json.loads(MALI.read_text(encoding="utf-8")))


def _state(food=0, wood=0, gold=0, stone=0, idle=0, age=1, clock=60, landmark=None):
    return GameState(clock=clock, idle=idle, age=age, ageup_builders=landmark,
                     villagers={"food": food, "wood": wood, "gold": gold, "stone": stone})


def _read(t, s):
    """Two readings of the same state: a villager count must be read twice to count."""
    t.update(s)
    return t.update(s)


def _eval(e, s, wall):
    e.evaluate(s, wall)
    return e.evaluate(s, wall)


def test_parse_reads_the_aoe4guides_overlay_format():
    b = _mali()
    assert (b.id, b.name, b.civ, len(b.steps)) == ("hXttcVQcMxTniZjgS79s", "Mali", "Malians", 12)
    first = b.steps[0]
    assert (first.age, first.villagers, first.time) == (1, 6, 0)
    assert first.targets == {"food": 0, "wood": 5, "gold": 0, "stone": 0, "builder": 1}
    assert b.steps[4].targets["builder"] is None          # -1: not given


def test_parse_rejects_what_is_not_a_build():
    with pytest.raises(ValueError):
        parse({"name": "x"})


@pytest.mark.parametrize("text, expected", [
    ("https://aoe4guides.com/builds/hXttcVQcMxTniZjgS79s", "hXttcVQcMxTniZjgS79s"),
    ("aoe4guides.com/builds/hXttcVQcMxTniZjgS79s?tab=2", "hXttcVQcMxTniZjgS79s"),
    ("hXttcVQcMxTniZjgS79s", "hXttcVQcMxTniZjgS79s"),
    ("https://example.com/builds/x", None),
    ("not a link", None),
])
def test_id_from_url(text, expected):
    assert id_from_url(text) == expected


def test_tokens_split_text_and_icons():
    assert tokens("5 @unit_worker/villager-malians.webp@on one @resource/sheep.webp@") == [
        ("text", "5 "), ("icon", "unit_worker/villager-malians.webp"), ("text", "on one "), ("icon", "resource/sheep.webp")]


def test_tracker_advances_by_villagers_and_waits_for_the_age():
    t = BuildTracker(_mali())
    assert t.index == 0
    _read(t, _state(food=6, wood=0))           # 6 villagers: steps 1 (6) only
    assert t.index == 0
    _read(t, _state(food=1, wood=6))           # 7: step 2
    assert t.index == 1
    _read(t, _state(food=10, wood=7))          # 17 villagers, still in age I: up to step 4 (15)
    assert t.index == 3
    _read(t, _state(food=10, wood=7, age=2))   # Feudal: step 5 (17)
    assert t.index == 4


def test_tracker_keeps_the_step_when_villagers_leave_to_build():
    t = BuildTracker(_mali())
    _read(t, _state(food=6, wood=8))           # 14 villagers: step 3
    assert t.index == 2
    _read(t, _state(food=4, wood=5))           # 5 went to build: the step stays
    assert t.index == 2


def test_stepping_back_by_hand_waits_for_one_more_villager():
    t = BuildTracker(_mali())
    _read(t, _state(food=1, wood=6))           # 7 villagers: step 2
    assert t.index == 1
    assert t.step_back() and t.index == 0
    _read(t, _state(food=1, wood=6))           # the same count does not move it again
    assert t.index == 0
    _read(t, _state(food=2, wood=6))           # one more villager: step 2 again
    assert t.index == 1


def test_stepping_forward_by_hand_then_on_by_villagers():
    t = BuildTracker(_mali())
    _read(t, _state(food=6, wood=0))           # step 1
    assert t.step_forward() and t.index == 1
    _read(t, _state(food=6, wood=0))           # fewer than the step: it stays
    assert t.index == 1
    _read(t, _state(food=6, wood=8))           # 14: step 3
    assert t.index == 2


def test_manual_moves_stop_at_the_ends():
    t = BuildTracker(_mali())
    assert not t.step_back()
    for _ in range(11):
        assert t.step_forward()
    assert not t.step_forward() and t.index == 11


def test_landmark_builders_count_as_villagers():
    t = BuildTracker(_mali())
    _read(t, _state(food=4, wood=6, landmark=5))   # 15 with the landmark builders
    assert t.index == 3


def test_instructions_move_extra_villagers_then_ask_for_more():
    target = {"food": 7, "wood": 10, "gold": 2, "stone": 0}
    assert instructions(target, {"food": 5, "wood": 11, "gold": 2, "stone": 0}) == [
        ("move", 1, "wood", "food"), ("put", 1, "food")]
    assert instructions(target, {"food": 7, "wood": 10, "gold": 2, "stone": 3}) == []   # ahead: fine
    assert instructions(target, {"food": 7, "wood": 10, "gold": 0, "stone": 0}) == [("put", 2, "gold")]
    assert describe(("move", 2, "wood", "food")) == "Move 2 villagers from wood to food"
    assert describe(("put", 1, "gold")) == "Put 1 villager on gold"


OTHERS_OFF = {r: {"enabled": False} for r in ("idle_villager", "tc_idle", "housed", "floating")}


def _engine(tmp_build):
    cfg = OTHERS_OFF | {"build": {"enabled": True, "warn_after_s": 6, "critical_after_s": 12},
                        "build_order": {"active": tmp_build.id, "show": True}}
    return RuleEngine(config=cfg)


@pytest.fixture
def stored_mali():
    b = _mali()
    (builds.builds_dir() / f"{b.id}.json").write_text(json.dumps(b.raw), encoding="utf-8")
    yield b
    builds.delete(b.id)


def test_build_alert_starts_as_info_and_escalates_while_off_the_step(stored_mali):
    e = _engine(stored_mali)
    _eval(e, _state(food=0, wood=12, clock=100), 0)          # 12 villagers: step 2 (wood 6); more is only being ahead
    assert e.build.index == 1 and "build" not in e.active
    _eval(e, _state(food=2, wood=12, clock=110), 10)         # 14: step 3 (food 4, wood 5) reached now
    assert e.build.index == 2
    a = e.active["build"]
    assert (a.severity, a.text) == ("info", "Move 2 villagers from wood to food")
    assert a.reason["to"] == "food"
    _eval(e, _state(food=2, wood=12, clock=116), 16)
    assert e.active["build"].severity == "warn"
    _eval(e, _state(food=2, wood=12, clock=122), 22)
    assert e.active["build"].severity == "critical"
    _eval(e, _state(food=4, wood=10, clock=124), 24)         # placed: the alert goes
    assert "build" not in e.active


def test_a_resource_reached_once_stays_reached(stored_mali):
    e = _engine(stored_mali)
    _eval(e, _state(food=4, wood=10, clock=100), 0)          # 14: step 3 (food 4, wood 5), food reached
    assert e.build.index == 2 and "build" not in e.active
    _eval(e, _state(food=3, wood=10, clock=110), 10)         # one left food (to build, most likely)
    assert "build" not in e.active


def test_no_build_chosen_means_no_build_alert():
    e = RuleEngine(config=OTHERS_OFF | {"build": {"enabled": True}})
    _eval(e, _state(), 0)
    assert e.build is None and not e.active


def test_import_from_a_link_saves_the_build_and_its_icons(monkeypatch):
    raw = MALI.read_bytes()
    png = io.BytesIO()
    Image.new("RGBA", (48, 48), (200, 160, 80, 255)).save(png, "PNG")
    asked = []

    def get(url):
        asked.append(url)
        return raw if "/api/builds/" in url else png.getvalue()

    b = builds.import_build("https://aoe4guides.com/builds/hXttcVQcMxTniZjgS79s", get=get)
    assert asked[0] == "https://aoe4guides.com/api/builds/hXttcVQcMxTniZjgS79s?overlay=true"
    assert builds.load(b.id).name == "Mali"
    assert builds.icon_file("resource/sheep.webp").exists()
    assert builds.icon_file("resource/sheep.webp").suffix == ".png"
    n = len(asked)
    builds.import_build(MALI.read_text(encoding="utf-8"), get=get)    # pasted JSON; icons already stored
    assert len(asked) == n
    assert builds.delete(b.id) and builds.load(b.id) is None


def test_import_explains_what_it_needs():
    with pytest.raises(ValueError, match="aoe4guides"):
        builds.import_build("hello")



def _pop_state(pop, clock, producing=True, idle=0, **vils):
    s = _state(idle=idle, clock=clock, **vils)
    s.pop, s.producing_villager = pop, producing
    return s


def _producing(t, pop, start, end, **vils):
    """Readings every 2 s from `start` (still idle) to `end` with the town center producing."""
    t.update(_pop_state(pop, start, producing=False, **vils))
    for clock in range(start + 2, end + 1, 2):
        t.update(_pop_state(pop, clock, **vils))  # one reading


def test_a_villager_building_counts_through_the_population():
    """Live match: 6 villagers + scout (pop 7); at 1:48 pop 8 with 6 on wood and
    the 7th building a house: step 2 (7 villagers) is reached then, not a villager later."""
    t = BuildTracker(_mali())
    _read(t, _pop_state(7, 37, producing=False, idle=6))
    _producing(t, 7, 80, 106, wood=6)                 # the 7th villager in training (26 s)
    _read(t, _pop_state(8, 108, wood=6))
    assert (t.builders, t.index) == (1, 1)


def test_units_trained_are_not_taken_for_builders():
    t = BuildTracker(_mali())
    _read(t, _pop_state(7, 37, producing=False, idle=6))
    _producing(t, 7, 80, 106, wood=6)                 # one villager trained
    _read(t, _pop_state(14, 108, producing=False, wood=6))   # 6 more pop: 1 villager, the rest units
    assert (t.builders, t.peak) == (1, 7)


def test_without_production_seen_only_the_villagers_seen_count():
    t = BuildTracker(_mali())
    _read(t, _pop_state(7, 37, producing=False, idle=6))
    _read(t, _pop_state(8, 108, producing=False, wood=6))
    assert (t.builders, t.peak, t.index) == (0, 6, 0)


def test_one_misread_never_moves_the_build():
    """Live match: the landmark builders read 51 for 5 once; with the age-up the
    panel jumped to the last step of age II."""
    t = BuildTracker(_mali())
    _read(t, _pop_state(16, 214, wood=5, food=5, landmark=5))
    t.update(_pop_state(16, 216, wood=5, food=5, landmark=51))   # impossible: more than the population
    t.update(_pop_state(16, 218, wood=5, food=5, landmark=15))   # possible, but read once
    _read(t, _pop_state(16, 220, wood=5, food=5, landmark=5))
    assert t.peak == 15
    _read(t, _pop_state(17, 255, wood=8, food=5, age=2))     # Feudal, 16 villagers and the scout
    assert t.index == 3                                        # step 4 until the 17th villager, not step 12


def test_refresh_updates_only_builds_their_author_changed():
    raw = json.loads(MALI.read_text(encoding="utf-8"))
    builds.import_build(json.dumps(raw), get=lambda url: b"")
    try:
        same = json.dumps(raw).encode()
        assert builds.refresh(get=lambda url: same if "/api/" in url else b"") == []
        raw["build_order"][2]["resources"]["food"] = 7                 # the author edited step 3
        changed = builds.refresh(get=lambda url: json.dumps(raw).encode() if "/api/" in url else b"")
        assert [b.name for b in changed] == ["Mali"]
        assert builds.load("hXttcVQcMxTniZjgS79s").steps[2].targets["food"] == 7

        def offline(url):
            raise OSError("no network")
        assert builds.refresh(get=offline) == []                        # keeps the stored build
        assert builds.load("hXttcVQcMxTniZjgS79s").steps[2].targets["food"] == 7
    finally:
        builds.delete("hXttcVQcMxTniZjgS79s")


def test_joined_late_the_starting_villagers_come_from_the_population():
    """Live session split by a pause: the first reading came at 1:29 with one
    villager building (pop 11 = 9 seen + scout + builder)."""
    t = BuildTracker(_mali())
    t.update(_pop_state(11, 89, food=9))
    assert t.start == 10


def test_rally_follows_the_notes_and_stays_until_changed():
    t = BuildTracker(_mali())
    seen = []
    for i in range(len(t.build.steps)):
        t.index = i
        seen.append(t.rally())
    assert seen[:5] == [None, "resource/sheep.webp", "resource/resource_food.webp",
                        "resource/resource_wood.webp", "resource/resource_wood.webp"]
    assert seen[-1] == "resource/resource_gold.webp"


def test_the_build_is_over_a_while_after_its_last_step():
    t = BuildTracker(_mali())
    last = len(t.build.steps) - 1
    t.index, t.reached_at, t.clock = last, 500, 520
    assert not t.finished
    t.clock = 530
    assert t.finished
    t.end_after_s = 60
    assert not t.finished


def test_no_build_alert_when_already_placed_for_the_next_step(stored_mali):
    e = _engine(stored_mali)
    _eval(e, _state(food=1, wood=6, clock=100), 0)               # 7 villagers: step 2 (wood 6)
    assert e.build.index == 1
    _eval(e, _state(food=0, wood=6, clock=120), 20)              # one building, wood as step 2 wants
    assert "build" not in e.active
    # Placed for step 3 (food 4, wood 5) before the 14th villager is counted.
    _eval(e, _state(food=4, wood=5, clock=140), 40)
    assert e.build.index == 1 and "build" not in e.active
