import numpy as np
from PIL import Image

import reeve.capture as capm
import reeve.live as live
from reeve.glyphs import FIXTURES
from reeve.window import GameWindow


class _FakeWin(GameWindow):
    @property
    def foreground(self):
        return True


def test_ui_scale_change_recalibrates_in_same_session(monkeypatch, tmp_path):
    """Changing the UI scale in the options does not change the window size: the
    panel "disappears" from the expected position. The engine must find it again
    and continue the same match, instead of waiting 30 s and closing the log."""
    a = np.asarray(Image.open(FIXTURES / "720p_0217.png").convert("RGB"))
    im = Image.fromarray(a)
    b = im.copy()
    b.paste(im.crop((0, 400, 300, 720)).resize((375, 400), Image.BICUBIC), (0, 320))  # UI 125%
    b = np.asarray(b)

    win = _FakeWin(1, "AoE4", 0, 0, 1280, 720)
    cur = {"f": a}

    def grab(self, w):
        buf = np.zeros_like(cur["f"])
        for x, y, rw, rh in self.rects:
            buf[y:y + rh, x:x + rw] = cur["f"][y:y + rh, x:x + rw]
        return buf

    monkeypatch.setattr(live, "find_game_window", lambda: win)
    monkeypatch.setattr(capm.Capture, "full", lambda self, w: cur["f"])
    monkeypatch.setattr(capm.Capture, "grab", grab)

    reader = live.LiveReader(2.0, sessions_dir=tmp_path)
    steps = []
    for frame in [a, a] + [b] * 6:
        cur["f"] = frame
        steps.append(reader.step())
    reader.close()

    assert [s.status for s in steps[:2]] == ["reading", "reading"]
    assert steps[2].status == "hidden"
    assert abs(steps[-1].match.scale - 1.25) < 0.03
    assert steps[-1].status == "reading"
    assert steps[-1].frame.values["pop"] == (10, 40)
    assert steps[-1].frame.values["food"] == 100
    assert len(list(tmp_path.iterdir())) == 1, "should continue in the same session"


def test_report_written_when_reading_stops(monkeypatch, tmp_path):
    """The report is written once the match has not been read for a while
    (end screen, menu, alt-tab), not only when the app closes."""
    a = np.asarray(Image.open(FIXTURES / "720p_0217.png").convert("RGB"))
    state = {"fg": True}

    class _Win(_FakeWin):
        @property
        def foreground(self):
            return state["fg"]

    w = _Win(1, "AoE4", 0, 0, 1280, 720)
    clock = {"t": 0.0}
    monkeypatch.setattr(live, "find_game_window", lambda: w)
    monkeypatch.setattr(capm.Capture, "full", lambda self, _w: a)
    monkeypatch.setattr(capm.Capture, "grab", lambda self, _w: a)
    monkeypatch.setattr(live.time, "monotonic", lambda: clock["t"])

    reader = live.LiveReader(2.0, sessions_dir=tmp_path)
    for _ in range(3):
        reader.step(); clock["t"] += 2
    session = next(tmp_path.iterdir())
    assert not (session / "report.html").exists()
    state["fg"] = False                      # player alt-tabs / match over
    for _ in range(4):
        reader.step(); clock["t"] += 2
    assert not (session / "report.html").exists()   # 6 s: not yet
    for _ in range(3):
        reader.step(); clock["t"] += 2
    assert (session / "report.html").exists()       # >= 10 s without reading


def test_session_without_readings_is_discarded(tmp_path):
    """The panel was seen for a moment (menu, alt-tab) but no frame was read:
    no match folder is left behind."""
    reader = live.LiveReader(2.0, sessions_dir=tmp_path)
    reader._open_session([])
    reader._write({"event": "panel_hidden"})
    reader.close()
    assert list(tmp_path.iterdir()) == []


def test_clock_going_back_starts_a_new_match(monkeypatch, tmp_path):
    """Restarting a match keeps the panel on screen: the clock going back
    (4:47 -> 0:03 in a live session) closes the match and opens a new one,
    so the age, alerts and build order start over."""
    a = np.asarray(Image.open(FIXTURES / "720p_0217.png").convert("RGB"))
    clocks = iter([287, 289, 291, 3, 5, 7, 9])
    real = live.read_frame

    def read(buf, match):
        f = real(buf, match)
        f.values["clock"] = next(clocks)
        return f

    monkeypatch.setattr(live, "find_game_window", lambda: _FakeWin(1, "AoE4", 0, 0, 1280, 720))
    monkeypatch.setattr(capm.Capture, "full", lambda self, _w: a)
    monkeypatch.setattr(capm.Capture, "grab", lambda self, _w: a)
    monkeypatch.setattr(live, "read_frame", read)
    t = {"now": 0.0}
    monkeypatch.setattr(live.time, "monotonic", lambda: t["now"])

    reader = live.LiveReader(2.0, sessions_dir=tmp_path)
    states = []
    for _ in range(7):
        states.append(reader.step().state.clock)
        t["now"] += 2
    reader.close()
    assert states[-1] == 9
    sessions = sorted(tmp_path.iterdir())
    assert len(sessions) == 2
    first = (sessions[0] / "log.jsonl").read_text(encoding="utf-8")
    assert '"clock_reset"' in first


def _menu_then_match(monkeypatch, tmp_path, frames):
    """Steps the reader over `frames` (None: a menu with no panel), counting full searches."""
    a = np.asarray(Image.open(FIXTURES / "720p_0217.png").convert("RGB"))
    menu = np.zeros_like(a)
    cur = {"f": a}
    probes = []

    def grab(self, w):
        buf = np.zeros_like(cur["f"])
        for x, y, rw, rh in self.rects:
            buf[y:y + rh, x:x + rw] = cur["f"][y:y + rh, x:x + rw]
        return buf

    real_probe = capm.Capture.probe
    monkeypatch.setattr(live, "find_game_window", lambda: _FakeWin(1, "AoE4", 0, 0, 1280, 720))
    monkeypatch.setattr(capm.Capture, "full", lambda self, w: cur["f"])
    monkeypatch.setattr(capm.Capture, "grab", grab)
    monkeypatch.setattr(capm.Capture, "probe", lambda self, w: probes.append(1) or real_probe(self, w))
    reader = live.LiveReader(2.0, sessions_dir=tmp_path)
    steps, counts = [], []
    for f in frames:
        cur["f"] = a if f else menu
        steps.append(reader.step().status)
        counts.append(len(probes))
    reader.close()
    return steps, counts


def test_menus_search_the_whole_window_only_every_few_cycles(monkeypatch, tmp_path):
    steps, probes = _menu_then_match(monkeypatch, tmp_path, [None] * 9)
    assert steps == ["waiting"] * 9
    assert probes[-1] == 3


def test_a_match_at_the_same_ui_scale_is_found_at_once(monkeypatch, tmp_path):
    # Read once, back to the menus (the match ends), then a new match: found on
    # the first cycle from where the panel was, without a full search.
    frames = [1] + [None] * (live.HIDDEN_END_S // 2 + 1) + [None, None, 1]
    steps, probes = _menu_then_match(monkeypatch, tmp_path, frames)
    assert steps[0] == "reading" and steps[-2] == "waiting" and steps[-1] == "reading"
    assert probes[-1] == probes[-2]
