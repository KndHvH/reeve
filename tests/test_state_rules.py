from aoe4ov.rules import RuleEngine
from aoe4ov.state import StateTracker

CFG = {
    "idle_villager": {"enabled": True, "min_idle": 1, "persist_s": 4},
    "tc_idle": {"enabled": True, "persist_s": 6},
    "housed": {"enabled": True, "margin": 1, "max_pop": 200},
    "floating": {"enabled": True, "persist_s": 6,
                 "bands": [{"until_s": 300, "max": 400}, {"until_s": 900, "max": 800}, {"until_s": None, "max": 1500}]},
}


def _values(clock, pop=(20, 30), idle=0, producing=True, food=100, wood=100, gold=100, stone=0, vils=(5, 5, 0, 0)):
    return {
        "clock": clock, "pop": pop, "idle": idle, "producing_villager": producing,
        "food": food, "wood": wood, "gold": gold, "stone": stone,
        "vil_food": vils[0], "vil_wood": vils[1], "vil_gold": vils[2], "vil_stone": vils[3],
    }


def _run(seq, every=2.0):
    """Feeds readings every `every` seconds; returns (states, alert ids active after each step, transitions)."""
    tracker, engine = StateTracker(), RuleEngine(config=CFG)
    states, active, log = [], [], []
    for i, v in enumerate(seq):
        wall = i * every
        s = tracker.update(v, wall)
        log += [(i, tr.kind, tr.alert.id) for tr in engine.evaluate(s, wall)]
        states.append(s)
        active.append({a.id for a in engine.alerts()})
    return states, active, log


def test_one_off_misread_of_pop_is_ignored():
    """A tooltip over "10/10" was read as "10/1" for one frame (live session)."""
    seq = [_values(100 + 2 * i, pop=(10, 10)) for i in range(4)]
    seq.insert(2, _values(104, pop=(10, 1)))
    states, _, _ = _run(seq)
    assert all((s.pop, s.pop_cap) == (10, 10) for s in states[1:])


def test_new_pop_value_accepted_after_two_reads():
    seq = [_values(100, pop=(10, 20)), _values(102, pop=(10, 20)), _values(104, pop=(11, 20)), _values(106, pop=(11, 20))]
    states, _, _ = _run(seq)
    assert [s.pop for s in states] == [None, 10, 10, 11]


def test_clock_misread_jump_is_ignored():
    """At 1:23 one clock read came out as 12:31 (live session)."""
    seq = [_values(c) for c in (79, 81, 751, 85, 87)]
    states, _, _ = _run(seq)
    assert [s.clock for s in states] == [79, 81, 81, 85, 87]


def test_clock_jump_after_menu_is_accepted_when_confirmed():
    """In multiplayer the game keeps running behind the menu: a forward jump
    confirmed by the next read is real."""
    seq = [_values(c) for c in (2140, 2142, 2178, 2180, 2182)]
    states, _, _ = _run(seq)
    assert states[2].clock == 2142 and states[3].clock == 2180


def test_idle_villager_alert_needs_persistence_and_clears():
    seq = [_values(100 + 2 * i, idle=0) for i in range(2)]
    seq += [_values(104 + 2 * i, idle=2) for i in range(5)]
    seq += [_values(114 + 2 * i, idle=0) for i in range(3)]
    _, active, log = _run(seq)
    on = next(i for i, k, a in log if k == "on" and a == "idle_villager")
    off = next(i for i, k, a in log if k == "off" and a == "idle_villager")
    assert on == 5   # confirmed at step 3 (2 reads), then held 4 s
    assert off == 8  # cleared once the 0 is confirmed
    assert "idle_villager" not in active[-1]


def test_tc_idle_fires_but_not_when_housed():
    seq = [_values(100 + 2 * i, producing=False) for i in range(6)]
    _, active, _ = _run(seq)
    assert "tc_idle" in active[-1]
    seq = [_values(100 + 2 * i, producing=False, pop=(30, 30)) for i in range(6)]
    _, active, _ = _run(seq)
    assert "tc_idle" not in active[-1]
    assert "housed" in active[-1]


def test_housed_warns_one_before_cap_and_ignores_max_pop():
    _, active, _ = _run([_values(100 + 2 * i, pop=(29, 30)) for i in range(3)])
    assert "housed" in active[-1]
    _, active, _ = _run([_values(100 + 2 * i, pop=(199, 200)) for i in range(3)])
    assert "housed" not in active[-1]


def test_floating_threshold_depends_on_game_time():
    early = [_values(200 + 2 * i, food=500) for i in range(5)]
    _, active, _ = _run(early)
    assert "floating" in active[-1]          # > 400 before 5:00
    mid = [_values(600 + 2 * i, food=500) for i in range(5)]
    _, active, _ = _run(mid)
    assert "floating" not in active[-1]      # limit is 800 between 5:00 and 15:00
