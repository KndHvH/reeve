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
