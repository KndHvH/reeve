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
            while not win.foreground:
                print("  aguardando o AoE4 ficar em primeiro plano...", end="\r")
                time.sleep(1)
            shot = sct.grab(win.rect)
            path = out / f"{datetime.now():%Y%m%d-%H%M%S}_{win.width}x{win.height}.png"
            mss.tools.to_png(shot.rgb, shot.size, output=str(path))
            print(f"[{i + 1}/{args.count}] {path}")
            if i + 1 < args.count:
                time.sleep(args.every)
    return 0


def cmd_inspect(args) -> int:
    from .inspect import run

    paths = [Path(p) for p in args.images]
    for out in run(paths):
        print(out)
    return 0


def cmd_label(args) -> int:
    """Abre o rotulador; capturas que já viraram fixture são puladas."""
    import json

    from .glyphs import FIXTURES
    from .label import run

    done = {json.loads(j.read_text(encoding="utf-8")).get("source") for j in FIXTURES.glob("*.json")}
    paths = [Path(p) for p in args.images if Path(p).suffix == ".png" and Path(p).stem not in done]
    if not paths:
        print("Nada novo para rotular (todas já são fixtures).")
        return 0
    run(paths)
    return 0


def cmd_glyphs(_args) -> int:
    from .glyphs import build

    print(build())
    return 0


def _fmt_clock(secs) -> str:
    if secs is None:
        return "--:--"
    h, rem = divmod(secs, 3600)
    return f"{h}:{rem // 60:02d}:{rem % 60:02d}" if h else f"{rem // 60:02d}:{rem % 60:02d}"


def cmd_watch(args) -> int:
    """Lê o jogo ao vivo e imprime uma linha por leitura: validação antes do overlay."""
    from .capture import Capture
    from .reader import read_frame

    cap = Capture()
    match = None
    size = None
    fails = 0
    print("Ctrl+C para sair.")
    try:
        while True:
            win = find_game_window()
            if win is None or not win.foreground:
                print("  aguardando o AoE4 em primeiro plano...".ljust(100), end="\r")
                time.sleep(args.every)
                continue
            if match is None or size != (win.width, win.height) or fails >= 3:
                match = cap.calibrate(win)
                size = (win.width, win.height)
                fails = 0
                if not match.ok:
                    # Menu, tela de carregamento ou fim de partida: sem painel na tela.
                    print(f"  aguardando partida (painel não encontrado, score {match.score:.2f})...".ljust(100), end="\r")
                    match = None
                    time.sleep(args.every)
                    continue
                print(f"[partida] painel encontrado: score {match.score:.3f} escala {match.scale:.3f}".ljust(100))
            t0 = time.perf_counter()
            f = read_frame(cap.grab(win), match)
            dt = (time.perf_counter() - t0) * 1000
            v = f.values
            bad = [n for n, r in f.readings.items() if not r.ok]
            fails = fails + 1 if len(bad) > 3 else 0
            pop = f"{v['pop'][0]}/{v['pop'][1]}" if v["pop"] else "?"
            res = "  ".join(f"{k[0].upper()} {v[k]}({v['vil_' + k]})" for k in ("food", "wood", "gold", "stone"))
            tc = "TC produzindo" if v["producing_villager"] else "TC PARADO"
            warn = f"  ?? {','.join(bad)}" if bad else ""
            print(f"{_fmt_clock(v['clock'])} | pop {pop} | ociosos {v['idle']} | {res} | {tc} | {dt:.1f} ms{warn}")
            time.sleep(max(0.0, args.every - dt / 1000))
    except KeyboardInterrupt:
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

    i = sub.add_parser("inspect", help="gera <imagem>.inspect.html com cada estágio da leitura")
    i.add_argument("images", nargs="+")

    lb = sub.add_parser("label", help="rotulador: confirme/corrija leituras e gere fixtures")
    lb.add_argument("images", nargs="+")

    sub.add_parser("glyphs", help="refaz assets/glyphs/ a partir das fixtures rotuladas")

    w = sub.add_parser("watch", help="lê o jogo ao vivo e imprime os valores")
    w.add_argument("--every", type=float, default=1.0, help="segundos entre leituras (1 a 2)")

    args = p.parse_args(argv)
    cmds = {
        "window": cmd_window, "snap": cmd_snap, "inspect": cmd_inspect,
        "label": cmd_label, "glyphs": cmd_glyphs, "watch": cmd_watch,
    }
    return cmds[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
