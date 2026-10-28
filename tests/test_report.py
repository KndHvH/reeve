import json

from aoe4ov.report import build_timeline, render, summarize, write_report


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
