"""Entrada de linha de comando: `aoe4ov <comando>`."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from .window import find_game_window

MAX_FAIL_SHOTS = 30  # imagens de falha salvas por partida no watch
HIDDEN_END_S = 30    # painel oculto por mais que isso = fim de partida
DIM_RATIO = 0.7      # âncora abaixo de 70% do brilho normal = tela escurecida (menu)
SHAPE_RATIO = 0.85   # forma da âncora abaixo de 85% da calibração = painel coberto/esmaecendo


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
    """Lê o jogo ao vivo e imprime uma linha por leitura: validação antes do overlay.

    Cada partida também vai para sessions/<início>/log.jsonl (uma linha por
    leitura, com valores, textos e confiança) e, quando algum campo falha,
    a imagem das regiões capturadas vai para sessions/<início>/falha_*.png.
    """
    import json

    from PIL import Image

    from .anchor import MIN_SCORE, panel_state
    from .capture import Capture
    from .reader import read_frame

    cap = Capture()
    match = None
    size = None
    fails = 0
    hidden = 0
    ref_bright = 0.0  # brilho da âncora na partida (o maior visto): base para detectar escurecimento
    session: Path | None = None
    log = None
    saved_fails = 0

    def close_session():
        nonlocal session, log
        if log:
            log.close()
            print(f"[partida] log salvo em {session}".ljust(100))
        session, log = None, None

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
                    close_session()
                    print(f"  aguardando partida (painel não encontrado, score {match.score:.2f})...".ljust(100), end="\r")
                    match = None
                    time.sleep(args.every)
                    continue
                print(f"[partida] painel encontrado: score {match.score:.3f} escala {match.scale:.3f}".ljust(100))
                ref_bright = 0.0
                if log is None:
                    session = Path("sessions") / f"{datetime.now():%Y%m%d-%H%M%S}"
                    session.mkdir(parents=True, exist_ok=True)
                    log = open(session / "log.jsonl", "a", encoding="utf-8")
                    saved_fails = 0
                    print(f"[partida] gravando em {session}".ljust(100))
            t0 = time.perf_counter()
            buf = cap.grab(win)
            t1 = time.perf_counter()

            # Menu, pausa ou tela de fim escondem o painel (forma some) ou
            # escurecem a tela (forma fica, brilho cai): pula a leitura em vez
            # de registrar lixo. Escondido por muito tempo = fim de partida.
            vis, bright = panel_state(buf, match)
            rel = bright / ref_bright if ref_bright else 1.0
            if vis >= max(MIN_SCORE, SHAPE_RATIO * match.score) and rel >= DIM_RATIO:
                ref_bright = max(ref_bright, bright)
            else:
                if hidden == 0:
                    log.write(json.dumps({"wall": f"{datetime.now():%H:%M:%S}", "event": "painel_oculto",
                                          "forma": round(vis, 3), "brilho": round(rel, 2)}) + "\n")
                    log.flush()
                hidden += 1
                print(f"  menu/pausa (painel oculto ou escurecido: forma {vis:.2f}, brilho {rel:.0%})...".ljust(100), end="\r")
                if hidden * args.every >= HIDDEN_END_S:
                    close_session()
                    match, hidden = None, 0
                time.sleep(args.every)
                continue
            if hidden:
                log.write(json.dumps({"wall": f"{datetime.now():%H:%M:%S}", "event": "painel_visivel"}) + "\n")
                hidden = 0

            f = read_frame(buf, match)
            dt = (time.perf_counter() - t0) * 1000
            grab_ms = (t1 - t0) * 1000
            v = f.values
            bad = [n for n, r in f.readings.items() if not r.ok]
            fails = fails + 1 if len(bad) > 3 else 0

            log.write(json.dumps({
                "wall": f"{datetime.now():%H:%M:%S}",
                "values": v,
                "text": {n: r.text for n, r in f.readings.items()},
                "conf": {n: round(r.conf, 3) for n, r in f.readings.items()},
                "prod_score": round(f.production.score, 3),
                "anchor": [match.x, match.y, round(match.scale, 3), round(match.score, 3)],
                "ms": round(dt, 1),
                "grab_ms": round(grab_ms, 1),
                "clock_conf": round(f.readings["clock"].conf, 3),
            }, ensure_ascii=False) + "\n")
            log.flush()
            if bad and saved_fails < MAX_FAIL_SHOTS:
                Image.fromarray(buf).save(session / f"falha_{datetime.now():%H%M%S}_{'-'.join(bad)}.png")
                saved_fails += 1
            pop = f"{v['pop'][0]}/{v['pop'][1]}" if v["pop"] else "?"
            res = "  ".join(f"{k[0].upper()} {v[k]}({v['vil_' + k]})" for k in ("food", "wood", "gold", "stone"))
            tc = "TC produzindo" if v["producing_villager"] else "TC PARADO"
            warn = f"  ?? {','.join(bad)}" if bad else ""
            print(f"{_fmt_clock(v['clock'])} | pop {pop} | ociosos {v['idle']} | {res} | {tc} | {dt:.0f} ms (captura {grab_ms:.0f}){warn}")
            time.sleep(max(0.0, args.every - dt / 1000))
    except KeyboardInterrupt:
        close_session()
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
    w.add_argument("--every", type=float, default=2.0, help="segundos entre leituras (padrão 2)")

    args = p.parse_args(argv)
    cmds = {
        "window": cmd_window, "snap": cmd_snap, "inspect": cmd_inspect,
        "label": cmd_label, "glyphs": cmd_glyphs, "watch": cmd_watch,
    }
    return cmds[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
