from types import SimpleNamespace

from reeve import checks


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _step(status, scale=2.0, height=1440):
    win = SimpleNamespace(width=2560, height=height)
    match = SimpleNamespace(scale=scale) if status == "reading" else None
    return SimpleNamespace(status=status, win=win, match=match)


def _notices(fullscreen=False):
    clock = Clock()
    n = checks.Notices(fullscreen=lambda: fullscreen, clock=clock, state={})
    return n, clock


def _titles(pairs):
    return [t for t, _ in pairs]


def test_welcome_only_on_the_first_run():
    n, _ = _notices()
    assert _titles(n.start()) == ["Reeve is running"]
    assert n.start() == []
    assert checks.Notices(state=checks.load_state()).start() == []   # remembered on disk


def test_first_calibration_is_told_once_with_resolution_and_ui_scale():
    n, _ = _notices()
    said = n.observe(_step("reading", scale=2.0, height=1440))
    assert _titles(said) == ["Reeve found the resource panel"]
    assert "2560×1440" in said[0][1] and "100%" in said[0][1]
    assert n.observe(_step("reading")) == []
    assert checks.load_state()["calibrated"] == {"width": 2560, "height": 1440, "scale": 2.0}


def test_exclusive_fullscreen_is_told_once_and_checked_sparingly():
    calls = []
    clock = Clock()
    n = checks.Notices(fullscreen=lambda: calls.append(clock.t) or True, clock=clock, state={"calibrated": {}})
    assert _titles(n.observe(_step("waiting"))) == ["AoE4 is in exclusive fullscreen"]
    for t in (2, 4, 12, 30):
        clock.t = t
        assert n.observe(_step("waiting")) == []
    assert calls == [0]                      # once said, never asked again


def test_no_fullscreen_check_without_the_game():
    calls = []
    n = checks.Notices(fullscreen=lambda: calls.append(1) or True, clock=Clock(), state={})
    assert n.observe(_step("no_game")) == [] and calls == []


def test_panel_never_found_after_five_minutes_in_the_game():
    n, clock = _notices()
    n.observe(_step("waiting"))
    clock.t = 299
    assert n.observe(_step("waiting")) == []
    clock.t = 300
    assert _titles(n.observe(_step("waiting"))) == ["Reeve hasn't found the resource panel yet"]
    clock.t = 900
    assert n.observe(_step("waiting")) == []             # said once per run


def test_leaving_the_game_restarts_the_no_panel_timer():
    n, clock = _notices()
    n.observe(_step("waiting"))
    clock.t = 250
    n.observe(_step("no_game"))                          # alt-tab
    clock.t = 260
    n.observe(_step("waiting"))
    clock.t = 400
    assert n.observe(_step("waiting")) == []             # only 140 s in the game since


def test_no_panel_notice_is_skipped_once_calibrated_before():
    n, clock = _notices()
    n.state["calibrated"] = {"width": 1920, "height": 1080, "scale": 1.5}
    n.observe(_step("waiting"))
    clock.t = 1000
    assert n.observe(_step("waiting")) == []


def test_webview2_lookup_reads_the_registry():
    v = checks.webview2_version()
    assert v is None or v.count(".") == 3
