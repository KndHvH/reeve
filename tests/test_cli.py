from aoe4ov.cli import main
from aoe4ov.window import find_game_window


def test_find_game_window_missing_title_returns_none():
    assert find_game_window("titulo-que-nao-existe-xyz") is None


def test_cli_parses_window_command():
    # Sem o jogo aberto o comando retorna 1, com ele aberto 0 — ambos são válidos aqui.
    assert main(["window"]) in (0, 1)
