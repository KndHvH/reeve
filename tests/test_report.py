import json

from reeve.report import build_timeline, render, summarize, write_report


def _log(tmp_path, n=40):
    """Synthetic session: 7 → 26 villagers, an idle town center from 0:40 to 0:50."""
    lines = []
    for i in range(n):
        clock = 10 + 2 * i
        vils = 5 + i // 2
        lines.append({
            "t": i * 2.0, "wall": "00:00:00",
            "values": {
                "clock": clock, "pop": [vils + 1, 50], "idle": 0,
                "producing_villager": not (40 <= clock < 50),
                "food": 100 + 20 * i, "wood": 50 + 10 * i, "gold": 100, "stone": 0,
                "vil_food": vils, "vil_wood": 1, "vil_gold": 0, "vil_stone": 0,
            },
        })
    session = tmp_path / "20260101-000000"
    session.mkdir()
    (session / "log.jsonl").write_text("\n".join(json.dumps(l) for l in lines) + "\n", encoding="utf-8")
    return session


def test_timeline_and_summary(tmp_path):
    session = _log(tmp_path)
    tl = build_timeline(session / "log.jsonl")
    assert len(tl["rows"]) == 40
    tc = [a for a in tl["alerts"] if a["id"] == "tc_idle"]
    assert tc and tc[0]["start"] >= 40 and tc[0]["end"] <= 54
    assert tl["rows"][-1]["inc"]["food"] > 0
    summary = summarize(tl)
    tc = next(p for p in summary["problems"] if p["id"] == "tc_idle")
    assert tc["seconds"] > 0 and tc["severity"] == "warn"
    assert summary["income"]["food"] > 0


def test_report_is_self_contained_html(tmp_path):
    out = write_report(_log(tmp_path))
    text = out.read_text(encoding="utf-8")
    assert text.startswith("<!doctype html>")
    assert "http://" not in text.replace('http://www.w3.org/2000/svg', "")  # no network resources
    assert '"rows":' in text


def test_empty_session_renders():
    assert "No readings" in render({"rows": [], "alerts": [], "frames": []}, "empty")


def _with_build_step(session):
    log = session / "log.jsonl"
    event = {"wall": "00:00:00", "event": "build_step", "build": "hXttcVQcMxTniZjgS79s", "name": "Mali", "step": 1, "of": 12}
    log.write_text(json.dumps(event) + "\n" + log.read_text(encoding="utf-8"), encoding="utf-8")
    return session


def test_report_follows_the_build_the_match_followed(tmp_path):
    from pathlib import Path

    from reeve import builds

    mali = Path(__file__).parent / "fixtures" / "builds" / "mali.json"
    (builds.builds_dir() / "hXttcVQcMxTniZjgS79s.json").write_text(mali.read_text(encoding="utf-8"), encoding="utf-8")
    try:
        tl = build_timeline(_with_build_step(_log(tmp_path)) / "log.jsonl")
        assert tl["build"] == {"id": "hXttcVQcMxTniZjgS79s", "name": "Mali", "civ": "Malians"}   # civ: the stored build's
        off = [a for a in tl["alerts"] if a["id"] == "build"]
        assert off and off[0]["text"].startswith("Move")         # everyone on food; the build wants wood
        assert any(p["id"] == "build" and p["seconds"] > 0 for p in summarize(tl)["problems"])
    finally:
        builds.delete("hXttcVQcMxTniZjgS79s")


def test_report_ignores_the_build_in_use_now_for_a_match_without_one(tmp_path):
    cfg_build = {"build_order": {"active": "hXttcVQcMxTniZjgS79s", "show": True}}
    from reeve.paths import load_config

    tl = build_timeline(_log(tmp_path) / "log.jsonl", load_config() | cfg_build)
    assert tl["build"] is None
    assert not any(a["id"] == "build" for a in tl["alerts"])
    assert all(p["id"] != "build" for p in summarize(tl)["problems"])


def test_the_match_civilization_is_the_followed_builds(tmp_path):
    session = _with_build_step(_log(tmp_path))
    log = session / "log.jsonl"
    log.write_text(log.read_text(encoding="utf-8").replace('"name": "Mali",', '"name": "Mali", "civ": "Malians",', 1),
                   encoding="utf-8")
    out = write_report(session)
    digest = json.loads((session / "summary.json").read_text(encoding="utf-8"))
    assert (digest["civ"], digest["build"]) == ("Malians", "Mali")
    text = out.read_text(encoding="utf-8")
    assert "<p class='civ'><img src='data:image/png;base64," in text and "<b>Malians</b>" in text


def test_a_match_without_a_build_has_no_civilization(tmp_path):
    session = _log(tmp_path)
    write_report(session)
    digest = json.loads((session / "summary.json").read_text(encoding="utf-8"))
    assert digest["civ"] is None and digest["build"] is None
    assert "class='civ'" not in (session / "report.html").read_text(encoding="utf-8")
