"""Imports an audio file into the alert sound library.

    uv run python scripts/import_sound.py <file> <name> [--source URL] [--license TEXT]

Any format ffmpeg reads (mp3, ogg, wav, ...) is decoded and given the same
treatment as sounds added in the hub (aoe4ov.sound_import: silence trimmed,
length capped, loudness normalized, 16-bit mono WAV). The result goes to assets/sounds/library/<name>.wav and
its source and license are recorded in assets/sounds/library/SOURCE.md. Which sound each severity uses
is chosen in config/rules.json ("sound").
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import numpy as np

from aoe4ov.sound_import import RATE, prepare, write

LIBRARY = Path(__file__).resolve().parents[1] / "assets" / "sounds" / "library"


def decode(path: Path) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(raw, "<f4").astype(np.float64)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("file", type=Path)
    p.add_argument("name", help="library name, e.g. chime_high")
    p.add_argument("--source", default="", help="where the file came from (URL)")
    p.add_argument("--license", default="", help="license of the file")
    args = p.parse_args()

    try:
        x = prepare(decode(args.file))
    except ValueError as e:
        raise SystemExit(str(e))
    dst = LIBRARY / f"{args.name}.wav"
    write(x, dst)
    note = LIBRARY / "SOURCE.md"
    lines = note.read_text(encoding="utf-8").splitlines() if note.exists() else ["# Alert sound library", ""]
    lines = [l for l in lines if not l.startswith(f"- `{args.name}.wav`")]
    lines.append(f"- `{args.name}.wav`: from `{args.file.name}`"
                 + (f", source {args.source}" if args.source else "")
                 + (f", license: {args.license}" if args.license else ""))
    note.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{dst}  ({len(x) / RATE:.2f} s, peak {20 * np.log10(np.abs(x).max()):.1f} dBFS)")


if __name__ == "__main__":
    main()
