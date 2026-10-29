import json

from reeve import paths
from reeve.hub import HubApi, diff, match_summaries


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


def test_report_url_builds_the_report_once():
    folder = _session("20260101-100000")
    url = HubApi().report_url("20260101-100000")
    report = folder / "report.html"
    assert url == report.as_uri() and report.exists()
    stamp = report.stat().st_mtime
    HubApi().report_url("20260101-100000")
    assert report.stat().st_mtime == stamp   # fresh report is reused


def _tone(seconds=3.0, lead_silence=0.5):
    import base64

    import numpy as np

    t = np.arange(int(seconds * 44100)) / 44100
    x = np.concatenate([np.zeros(int(lead_silence * 44100)), 0.9 * np.sin(2 * np.pi * 660 * t)]).astype("<f4")
    return base64.b64encode(x.tobytes()).decode()


def test_add_sound_saves_a_trimmed_leveled_wav_with_a_safe_name():
    import wave

    import numpy as np

    api = HubApi()
    r = api.add_sound("My Horn!.mp3", _tone())
    assert r["name"] == "my_horn" and r["user_sounds"] == ["my_horn"]
    with wave.open(str(paths.user_sounds_dir() / "my_horn.wav")) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2") / 32767
        assert (w.getframerate(), w.getnchannels()) == (44100, 1)
    assert len(x) == int(1.5 * 44100)          # capped
    assert np.abs(x[:220]).max() > 0.01        # leading silence trimmed
    assert np.abs(x).max() <= 0.98 + 1e-3      # never clips
    assert "my_horn" in api.settings()["sounds"]
    assert api.add_sound("my horn.wav", _tone())["name"] == "my_horn_2"   # never overwrites
    assert api.add_sound("blip.ogg", _tone())["name"] == "blip_2"         # nor a built-in


def test_add_sound_rejects_silence():
    import base64

    import numpy as np

    silent = base64.b64encode(np.zeros(44100, "<f4").tobytes()).decode()
    assert "silent" in HubApi().add_sound("quiet.mp3", silent)["error"]


def test_remove_sound_puts_its_severities_back_to_default():
    api = HubApi()
    name = api.add_sound("horn.mp3", _tone())["name"]
    values = api.settings()["values"]
    default_warn = values["sound"]["warn"]
    values["sound"]["warn"] = name
    api.save_settings(values)
    r = api.remove_sound(name)
    assert r["user_sounds"] == [] and r["sound"]["warn"] == default_warn
    assert not (paths.user_sounds_dir() / f"{name}.wav").exists()
    assert "error" in api.remove_sound("blip")            # built-ins cannot be removed
    assert "error" in api.remove_sound("../config/rules")  # nor anything outside the folder


def test_code_mtime_falls_back_when_the_source_is_not_on_disk():
    import types

    from reeve.hub import _code_mtime
    from reeve import report

    assert _code_mtime(report) > 0
    assert _code_mtime(types.SimpleNamespace(__file__="Z:/nowhere/report.pyc")) == 0.0


def test_sessions_without_game_time_are_not_listed():
    _session("20260101-100000")
    empty = paths.sessions_dir() / "20260104-100000"
    empty.mkdir()
    (empty / "log.jsonl").write_text('{"wall": "10:00:00", "event": "panel_hidden"}\n', encoding="utf-8")
    assert [m["session"] for m in match_summaries()] == ["20260101-100000"]


def test_delete_matches_removes_only_recorded_matches():
    a, b = _session("20260101-100000"), _session("20260102-100000")
    keep = paths.data_dir() / "config"
    keep.mkdir(exist_ok=True)
    api = HubApi()
    assert api.delete_matches(["20260101-100000", "../config", "..", "nope", ""]) == 1
    assert not a.exists() and b.exists() and keep.exists()
    assert [m["session"] for m in match_summaries()] == ["20260102-100000"]


def test_update_build_imports_it_again_from_its_link(monkeypatch):
    import json
    from pathlib import Path

    from reeve import builds
    from reeve.hub import HubApi

    raw = json.loads((Path(__file__).parent / "fixtures" / "builds" / "mali.json").read_text(encoding="utf-8"))
    builds.import_build(json.dumps(raw), get=lambda url: b"")         # pasted; icons fail quietly
    raw["build_order"] = raw["build_order"][:3]                           # the author shortened it
    monkeypatch.setattr(builds, "_get", lambda url: json.dumps(raw).encode() if "/api/" in url else b"")
    monkeypatch.setattr(builds.import_build, "__defaults__", (builds._get,))
    try:
        r = HubApi().update_build("hXttcVQcMxTniZjgS79s")
        assert r["updated"]["steps"] == 3
        assert len(builds.load("hXttcVQcMxTniZjgS79s").steps) == 3
    finally:
        builds.delete("hXttcVQcMxTniZjgS79s")
