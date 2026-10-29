import os
from datetime import datetime, timedelta

from reeve import paths, retention

NOW = datetime(2026, 6, 1, 12, 0, 0)


def _session(days_ago, frames=3, with_age=True, doubts=1):
    """A session folder named after its start, `days_ago` before NOW."""
    name = (NOW - timedelta(days=days_ago)).strftime("%Y%m%d-%H%M%S")
    s = paths.sessions_dir() / name
    (s / "frames").mkdir(parents=True)
    (s / "log.jsonl").write_text('{"t": 0, "values": {"age": 1}}\n' if with_age else '{"t": 0, "values": {}}\n')
    (s / "report.html").write_text("<html></html>")
    (s / "summary.json").write_text("{}")
    for i in range(frames):
        (s / "frames" / f"{i:05d}.jpg").write_bytes(b"x" * 1000)
        (s / "frames" / f"top_{i:05d}.jpg").write_bytes(b"x" * 1000)
    for i in range(doubts):
        (s / f"doubt_queue_{i}.png").write_bytes(b"x" * 5000)
    old = (NOW - timedelta(days=days_ago)).timestamp()
    os.utime(s / "log.jsonl", (old, old))     # not a match being recorded
    return s


def _apply(**cfg):
    base = {"enabled": True, "full_days": 7, "keep_days": 90, "max_mb": 500} | cfg
    return retention.apply({"retention": base}, now=NOW.timestamp())


def _names(paths_):
    return sorted(p.name for p in paths_)


def test_recent_match_is_kept_whole():
    s = _session(2)
    p = _apply()
    assert not p.light and not p.delete
    assert len(list((s / "frames").iterdir())) == 6


def test_week_old_match_keeps_only_log_report_and_summary():
    s = _session(10)
    p = _apply()
    assert _names(p.light) == [s.name]
    assert _names(s.iterdir()) == ["log.jsonl", "report.html", "summary.json"]


def test_top_frames_stay_when_the_log_has_no_ages():
    """Matches recorded before age detection get their ages from these frames."""
    s = _session(10, with_age=False)
    _apply()
    assert _names((s / "frames").iterdir()) == ["top_00000.jpg", "top_00001.jpg", "top_00002.jpg"]


def test_old_match_is_deleted():
    s = _session(120)
    p = _apply()
    assert _names(p.delete) == [s.name] and not s.exists()


def test_size_cap_lightens_the_oldest_first_then_deletes():
    old, mid, new = _session(5, frames=200), _session(3, frames=200), _session(1, frames=200)
    each = 400 * 1000 + 5000          # frames + doubts per session
    cap_mb = (3 * each - each // 2) / 1024 / 1024
    p = _apply(max_mb=cap_mb)
    assert old.name in _names(p.light) and new.name not in _names(p.light)
    assert not p.delete
    p = _apply(max_mb=0)              # nothing fits: everything but the newest goes
    assert sorted([old.name, mid.name]) == _names(p.delete)
    assert new.exists()


def test_disabled_does_nothing():
    _session(200)
    p = _apply(enabled=False)
    assert not p.light and not p.delete


def test_a_match_being_recorded_is_never_touched():
    s = _session(200)
    os.utime(s / "log.jsonl")         # written just now
    p = _apply(max_mb=0)
    assert not p.delete and s.exists()
