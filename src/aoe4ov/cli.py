"""Command-line entry point: `aoe4ov <command>`."""

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
        print("AoE4 not found. Is the game running (borderless/windowed)?")
        return 1
    print(f"Window: {win.title!r}")
    print(f"Game area: {win.width}x{win.height} at ({win.left}, {win.top})")
    return 0


def cmd_snap(args) -> int:
    """Save screenshots of the game area — raw material for templates and fixtures."""
    import mss
    import mss.tools

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with mss.MSS() as sct:
        for i in range(args.count):
            win = find_game_window()
            if win is None:
                print("AoE4 not found.")
                return 1
            while not win.foreground:
                print("  waiting for AoE4 to be in the foreground...", end="\r")
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
    """Open the labeler; captures that are already fixtures are skipped.

    A folder (e.g. sessions/ or one session) contributes its doubt_read_*.png
    images, searched recursively: they are frames where the panel was visible
    and some field was read with low confidence.
    """
    import json

    from .glyphs import FIXTURES
    from .label import run

    found: list[Path] = []
    for arg in args.images:
        p = Path(arg)
        if p.is_dir():
            found += sorted(p.rglob("doubt_read_*.png"))
        elif p.suffix == ".png":
            found.append(p)
    if not found:
        print("No images found (a folder contributes its doubt_read_*.png images).")
        return 0
    done = {json.loads(j.read_text(encoding="utf-8")).get("source") for j in FIXTURES.glob("*.json")}
    paths = [p for p in found if p.stem not in done]
    if not paths:
        print(f"Nothing new to label: all {len(found)} images are already fixtures.")
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
    """Read the game live and print one line per reading (engine in live.py).

    Each match is also written to sessions/<start>/log.jsonl and, when a
    field fails, the image of the captured regions goes to fail_*.png.
    """
    from .live import LiveReader

    live = LiveReader(args.every)
    print("Ctrl+C to quit.")
    try:
        while True:
            t0 = time.perf_counter()
            s = live.step()
            for e in s.events:
                print(f"[match] {e}".ljust(100))
            if s.status == "no_game":
                print("  waiting for AoE4 in the foreground...".ljust(100), end="\r")
            elif s.status == "waiting":
                print(f"  waiting for a match (panel not found, score {s.match.score:.2f})...".ljust(100), end="\r")
            elif s.status == "hidden":
                print(f"  menu/pause (panel hidden or veiled: shape {s.shape:.2f}, contrast {s.contrast:.2f})...".ljust(100), end="\r")
            else:
                v = s.frame.values
                pop = f"{v['pop'][0]}/{v['pop'][1]}" if v["pop"] else "?"
                res = "  ".join(f"{k[0].upper()} {v[k]}({v['vil_' + k]})" for k in ("food", "wood", "gold", "stone"))
                tc = "TC producing" if v["producing_villager"] else "TC IDLE"
                warn = f"  ?? {','.join(s.bad)}" if s.bad else ""
                alerts = f"  ! {' | '.join(a.text for a in s.alerts)}" if s.alerts else ""
                print(f"{_fmt_clock(v['clock'])} | pop {pop} | idle {v['idle']} | {res} | {tc} | "
                      f"{s.grab_ms + s.read_ms:.0f} ms (capture {s.grab_ms:.0f}){warn}{alerts}")
            time.sleep(max(0.0, args.every - (time.perf_counter() - t0)))
    except KeyboardInterrupt:
        events: list[str] = []
        live.close(events)
        for e in events:
            print(f"[match] {e}".ljust(100))
        return 0


def cmd_overlay(args) -> int:
    """Overlay on top of the game: alerts only, or the full debug view."""
    from .overlay import run

    print(f"{'Debug' if args.debug else 'Clean'} overlay active. Ctrl+C here to quit.")
    try:
        run(args.every, args.debug, args.mute)
    except KeyboardInterrupt:
        pass
    return 0


def cmd_replay(args) -> int:
    """Runs the state tracker and alert rules over a recorded session."""
    from .replay import replay

    for line in replay(Path(args.log)):
        print(line)
    return 0


def cmd_sounds(args) -> int:
    """Lists the sound library and which sound each severity uses; previews one."""
    from .rules import SEVERITIES, load_config
    from .sound import LIBRARY, library, play_file

    if args.play:
        path = LIBRARY / f"{args.play}.wav"
        if not path.exists():
            print(f"unknown sound: {args.play}")
            return 1
        play_file(path, wait=True)
        return 0
    cfg = load_config().get("sound", {})
    used = {cfg.get(s): s for s in SEVERITIES if cfg.get(s)}
    for name in library():
        print(f"{name:20s} {used.get(name, '')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="aoe4ov")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("window", help="show the detected AoE4 window and its resolution")

    s = sub.add_parser("snap", help="take screenshots of the game area")
    s.add_argument("--count", type=int, default=1)
    s.add_argument("--every", type=float, default=10.0, help="seconds between screenshots")
    s.add_argument("--out", default="captures")

    i = sub.add_parser("inspect", help="generate <image>.inspect.html with every stage of the reading")
    i.add_argument("images", nargs="+")

    lb = sub.add_parser("label", help="labeler: confirm/correct readings and generate fixtures")
    lb.add_argument("images", nargs="+")

    sub.add_parser("glyphs", help="rebuild assets/glyphs/ from the labeled fixtures")

    w = sub.add_parser("watch", help="read the game live and print the values")
    w.add_argument("--every", type=float, default=2.0, help="seconds between readings (default 2)")

    o = sub.add_parser("overlay", help="overlay on top of the game: alerts (default) or --debug view")
    o.add_argument("--debug", action="store_true", help="show detection, values, confidence, timings, RAM/CPU")
    o.add_argument("--mute", action="store_true", help="no alert sounds")
    o.add_argument("--every", type=float, default=2.0, help="seconds between readings (default 2)")

    rp = sub.add_parser("replay", help="replay a recorded session through the alert rules")
    rp.add_argument("log", help="path to sessions/<start>/log.jsonl")

    so = sub.add_parser("sounds", help="list the alert sound library or preview a sound")
    so.add_argument("--play", metavar="NAME", help="play a sound from the library")

    args = p.parse_args(argv)
    cmds = {
        "window": cmd_window, "snap": cmd_snap, "inspect": cmd_inspect,
        "label": cmd_label, "glyphs": cmd_glyphs, "watch": cmd_watch, "overlay": cmd_overlay, "replay": cmd_replay, "sounds": cmd_sounds,
    }
    return cmds[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
