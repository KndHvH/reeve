"""Entrada de linha de comando: `aoe4ov <comando>`."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from .window import find_game_window


def cmd_window(_args) -> int:
    win = find_game_window()
    if win is None:
        print("AoE4 não encontrado. O jogo está aberto (borderless/janela)?")
        return 1
    print(f"Janela: {win.title!r}")
    print(f"Área do jogo: {win.width}x{win.height} em ({win.left}, {win.top})")
    return 0


def cmd_snap(args) -> int:
    """Salva screenshots da área do jogo — matéria-prima para templates e fixtures."""
    import mss
    import mss.tools

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with mss.mss() as sct:
        for i in range(args.count):
            win = find_game_window()
            if win is None:
                print("AoE4 não encontrado.")
                return 1
            shot = sct.grab(win.rect)
            path = out / f"{datetime.now():%Y%m%d-%H%M%S}_{win.width}x{win.height}.png"
            mss.tools.to_png(shot.rgb, shot.size, output=str(path))
            print(f"[{i + 1}/{args.count}] {path}")
            if i + 1 < args.count:
                time.sleep(args.every)
    return 0


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="aoe4ov")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("window", help="mostra a janela do AoE4 detectada e sua resolução")

    s = sub.add_parser("snap", help="tira screenshots da área do jogo")
    s.add_argument("--count", type=int, default=1)
    s.add_argument("--every", type=float, default=10.0, help="segundos entre screenshots")
    s.add_argument("--out", default="captures")

    args = p.parse_args(argv)
    return {"window": cmd_window, "snap": cmd_snap}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
