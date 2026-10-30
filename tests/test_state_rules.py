from reeve.rules import RuleEngine
from reeve.state import StateTracker

CFG = {
    "idle_villager": {"enabled": True, "persist_s": 4, "warn_at": 1, "critical_at": 3},
    "tc_idle": {"enabled": True, "persist_s": 0, "critical_after_s": 10},
    "housed": {"enabled": True, "warn_ratio": 0.9, "critical_ratio": 1.0, "max_pop": 200},
    "floating": {"enabled": True, "persist_s": 6, "age_limits": [400, 800, 1500]},
}


def _values(clock, pop=(20, 30), idle=0, producing=True, food=100, wood=100, gold=100, stone=0, vils=(5, 5, 0, 0),
            age=None):
    return {"age": age,
        "clock": clock, "pop": pop, "idle": idle, "producing_villager": producing,
        "food": food, "wood": wood, "gold": gold, "stone": stone,
        "vil_food": vils[0], "vil_wood": vils[1], "vil_gold": vils[2], "vil_stone": vils[3],
    }


def _run(seq, every=2.0, config=CFG):
    """Feeds readings every `every` seconds; returns (states, {alert id: severity}
    active after each step, transitions)."""
    tracker, engine = StateTracker(), RuleEngine(config=config)
    states, active, log = [], [], []
    for i, v in enumerate(seq):
        wall = i * every
        s = tracker.update(v, wall)
        log += [(i, tr.kind, tr.alert.id) for tr in engine.evaluate(s, wall)]
        states.append(s)
        active.append({a.id: a.severity for a in engine.alerts()})
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


def test_housed_levels_by_population_ratio():
    def sev(pop):
        _, active, _ = _run([_values(100 + 2 * i, pop=pop, producing=True) for i in range(3)])
        return active[-1].get("housed")
    assert sev((17, 20)) is None            # 85%
    assert sev((18, 20)) == "warn"          # 90%
    assert sev((19, 20)) == "warn"          # 95%
    assert sev((20, 20)) == "critical"      # at the cap
    assert sev((199, 200)) is None          # max population: nothing to build


def _floating_at(age, food):
    _, active, _ = _run([_values(200 + 2 * i, food=food, age=age) for i in range(8)])
    return active[-1].get("floating")


def test_floating_threshold_depends_on_the_age():
    assert _floating_at(1, 500) == "info"    # > 400 in Age I
    assert _floating_at(2, 500) is None      # limit is 800 in Age II
    assert _floating_at(None, 500) == "info"  # age not read yet: Age I


def test_idle_villager_levels():
    def sev(n):
        _, active, _ = _run([_values(100 + 2 * i, idle=n) for i in range(6)])
        return active[-1].get("idle_villager")
    assert sev(0) is None
    assert sev(1) == "warn" and sev(2) == "warn"
    assert sev(3) == "critical"


def test_tc_idle_escalates_after_10_seconds():
    seq = [_values(100 + 2 * i, producing=False) for i in range(10)]
    _, active, log = _run(seq)
    levels = [a.get("tc_idle") for a in active]
    first_warn = levels.index("warn")
    first_crit = levels.index("critical")
    assert 2 * (first_crit - first_warn) == 10  # shows at once, critical after 10 s
    assert any(k == "change" and a == "tc_idle" for _, k, a in log)


def test_floating_escalates_within_the_same_age():
    assert _floating_at(1, 450) == "info"        # > 400 in Age I
    assert _floating_at(1, 900) == "warn"        # already above the Age II limit
    assert _floating_at(1, 1600) == "critical"   # above the Age III limit
    assert _floating_at(2, 900) == "info"
    assert _floating_at(2, 1600) == "warn"
    assert _floating_at(3, 1600) == "info"       # Age III: only its own limit
    assert _floating_at(4, 9000) is None         # Age IV: no limit by default


def test_floating_age_iv_limit_when_set():
    cfg = {**CFG, "floating": {**CFG["floating"], "age_limits": [400, 800, 1500, 3000]}}
    _, active, _ = _run([_values(200 + 2 * i, food=3500, age=4) for i in range(8)], config=cfg)
    assert active[-1].get("floating") == "info"
    assert _floating_at(3, 3500) == "info"       # three limits (older config): Age III has no later one


SOUND_CFG = {"enabled": True, "repeat_s": 5, "volume": 1.0, "info": "blip", "warn": "chime", "critical": "alarm_low"}


def test_sound_plays_on_new_escalation_and_repeat_only():
    from reeve.rules import Alert
    from reeve.sound import AlertSounds

    played = []
    snd = AlertSounds(SOUND_CFG, play=lambda path: played.append(path.stem))
    w = Alert("tc_idle", "warn", "", {})
    c = Alert("tc_idle", "critical", "", {})
    i = Alert("floating", "info", "", {})
    assert snd.update([i], 0) == "info"             # info plays once...
    assert snd.update([i], 6) is None               # ...and never repeats
    assert snd.update([w, i], 7) == "warn"          # new warn
    assert snd.update([w, i], 9) is None            # within repeat window
    assert snd.update([c, i], 10) == "critical"     # escalation plays at once
    assert snd.update([c, i], 12) is None
    assert snd.update([c, i], 15) == "critical"     # repeat after 5 s
    assert snd.update([], 16) is None               # resolved: silence
    assert played == ["blip", "chime", "alarm_low", "alarm_low"]


def test_sound_plays_once_for_simultaneous_alerts():
    from reeve.rules import Alert
    from reeve.sound import AlertSounds

    played = []
    snd = AlertSounds(SOUND_CFG, play=lambda path: played.append(path.stem))
    alerts = [Alert("housed", "critical", "", {}), Alert("idle_villager", "warn", "", {}), Alert("floating", "info", "", {})]
    assert snd.update(alerts, 0) == "critical"
    assert snd.update(alerts, 2) is None
    assert played == ["alarm_low"]


def test_severity_without_sound_is_silent():
    from reeve.rules import Alert
    from reeve.sound import AlertSounds

    snd = AlertSounds(SOUND_CFG | {"info": ""}, play=lambda path: None)
    assert snd.update([Alert("floating", "info", "", {})], 0) is None


def test_configured_sounds_exist_in_library():
    from reeve.rules import SEVERITIES, load_config
    from reeve.sound import library

    cfg = load_config()["sound"]
    for sev in SEVERITIES:
        assert not cfg.get(sev) or cfg[sev] in library(), sev


def test_volume_curve_and_silence_at_zero():
    from reeve.rules import Alert
    from reeve.sound import AlertSounds, gain

    assert gain(0) == 0 and gain(1) == 1
    assert gain(0.5) == 0.25            # default: a quarter of the file's amplitude
    assert gain(2) == 1 and gain(-1) == 0
    played = []
    snd = AlertSounds(SOUND_CFG | {"volume": 0.0}, play=lambda path: played.append(path))
    assert snd.update([Alert("housed", "critical", "", {})], 0) is None
    assert played == []


def test_idle_town_center_is_no_alert_past_the_villager_limit():
    from reeve.rules import _tc_idle
    from reeve.state import GameState

    s = GameState(clock=900, pop=150, pop_cap=200, producing_villager=False,
                  villagers={"food": 40, "wood": 30, "gold": 25, "stone": 5})
    assert _tc_idle(s, {"critical_after_s": 10, "max_villagers": 100}, 0) is None
    assert _tc_idle(s, {"critical_after_s": 10, "max_villagers": 120}, 0) is not None
