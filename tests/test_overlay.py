from types import SimpleNamespace

from reeve.overlay import Overlay


def _overlay(debug, show):
    o = Overlay.__new__(Overlay)       # no window: only the capture rule is exercised
    o.debug, o.excluded, o.calls = debug, True, []
    o.live = SimpleNamespace(rules=SimpleNamespace(config={"overlay": {"show_in_recordings": show}}))
    o._set_excluded = lambda excluded: o.calls.append(excluded) or excluded
    return o


def test_alert_cards_show_in_recordings_by_default():
    o = _overlay(debug=False, show=True)
    o._sync_capture()
    assert o.excluded is False and o.calls == [False]
    o._sync_capture()
    assert o.calls == [False]                     # only changed when needed


def test_debug_view_is_always_hidden_from_captures():
    o = _overlay(debug=True, show=True)
    o._sync_capture()
    assert o.excluded is True and o.calls == []   # already hidden


def test_setting_off_hides_the_cards():
    o = _overlay(debug=False, show=False)
    o._sync_capture()
    assert o.excluded is True
