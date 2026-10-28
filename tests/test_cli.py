from aoe4ov.cli import main
from aoe4ov.window import find_game_window


def test_find_game_window_missing_title_returns_none():
    assert find_game_window("title-that-does-not-exist-xyz") is None


def test_cli_parses_window_command():
    # Without the game open the command returns 1, with it open 0 — both are valid here.
    assert main(["window"]) in (0, 1)
