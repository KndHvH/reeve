import json

from aoe4ov import paths
from aoe4ov.hub import HubApi, diff, match_summaries


def test_diff_keeps_only_changes():
    defaults = {"a": 1, "s": {"x": 1, "y": [1, 2]}, "t": {"z": True}}
    values = {"a": 1, "s": {"x": 2, "y": [1, 2]}, "t": {"z": True}}
    assert diff(defaults, values) == {"s": {"x": 2}}


def test_save_settings_writes_overrides_and_reset_clears():
    api = HubApi()
    values = api.settings()["values"]
    values["tc_idle"]["critical_after_s"] = 20
    values["sound"]["repeat"] = []
    saved = api.save_settings(values)
    assert saved == {"tc_idle": {"critical_after_s": 20}, "sound": {"repeat": []}}
    assert paths.load_config()["tc_idle"]["critical_after_s"] == 20
    assert api.reset_settings()
    assert json.loads(paths.user_config_path().read_text(encoding="utf-8")) == {}


def test_settings_lists_the_sound_library():
    s = HubApi().settings()
    assert {"blip", "chime", "alarm_low"} <= set(s["sounds"])
    assert s["values"]["sound"]["warn"] in s["sounds"]


def _session(name, n=30):
    folder = paths.sessions_dir() / name
    folder.mkdir()
    lines = [{"t": 2.0 * i, "wall": "00:00:00", "values": {
        "clock": 10 + 2 * i, "pop": [8, 20], "idle": 0, "producing_villager": True,
        "food": 100, "wood": 50, "gold": 0, "stone": 0,
        "vil_food": 5, "vil_wood": 2, "vil_gold": 0, "vil_stone": 0}} for i in range(n)]
    (folder / "log.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return folder


def test_match_list_builds_and_reuses_summaries():
    _session("20260101-100000")
    _session("20260102-100000")
    first = match_summaries()
    assert [m["session"] for m in first] == ["20260102-100000", "20260101-100000"]   # newest first
    assert first[0]["duration"] == 58
    stamp = (paths.sessions_dir() / "20260102-100000" / "summary.json").stat().st_mtime
    match_summaries()
    assert (paths.sessions_dir() / "20260102-100000" / "summary.json").stat().st_mtime == stamp  # reused


def test_broken_log_does_not_hide_other_matches():
    _session("20260101-100000")
    broken = paths.sessions_dir() / "20260103-100000"
    broken.mkdir()
    (broken / "log.jsonl").write_text("not json\n", encoding="utf-8")
    assert [m["session"] for m in match_summaries()] == ["20260101-100000"]
