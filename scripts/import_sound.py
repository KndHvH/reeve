"""Imports an audio file as an alert sound of a theme.

    uv run python scripts/import_sound.py <file> <theme> <warn|critical> [--source URL] [--license TEXT]

Any format ffmpeg reads (mp3, ogg, wav, ...) is converted to 44.1 kHz,
16-bit mono WAV, which winsound plays without extra dependencies. Leading
silence is trimmed so the sound starts with the alert, the length is capped
(with a short fade-out) so it never plays over the game for long, and the
level is normalized so every theme plays at the same loudness. The source
and license are recorded in assets/sounds/<theme>/SOURCE.md.
"""

from __future__ import annotations

import argparse
import subprocess
import wave
from pathlib import Path

import numpy as np

RATE = 44100
MAX_S = 1.5          # longer sounds are cut, with a fade-out
FADE_S = 0.08
SILENCE = 0.02       # leading samples below this (relative to the peak) are trimmed
TARGET_RMS_DB = -26  # loudness target for the voiced part (similar to the default theme)
PEAK_LIMIT = 0.5     # never above -6 dBFS
SOUNDS = Path(__file__).resolve().parents[1] / "assets" / "sounds"


def decode(path: Path) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(raw, "<f4").astype(np.float64)


def prepare(x: np.ndarray) -> np.ndarray:
    peak = np.abs(x).max()
    if peak == 0:
        raise SystemExit("the file is silent")
    start = int(np.argmax(np.abs(x) > SILENCE * peak))
    x = x[max(0, start - int(0.002 * RATE)):]
    if len(x) > MAX_S * RATE:
        x = x[:int(MAX_S * RATE)]
    fade = min(len(x) // 4, int(FADE_S * RATE))
    x[-fade:] *= np.linspace(1, 0, fade)
    voiced = x[np.abs(x) > 0.1 * np.abs(x).max()]
    rms = np.sqrt(np.mean(voiced ** 2))
    x = x * (10 ** (TARGET_RMS_DB / 20) / rms)
    if np.abs(x).max() > PEAK_LIMIT:
        x = x * (PEAK_LIMIT / np.abs(x).max())
    return x


def write(x: np.ndarray, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dst), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(np.clip(x * 32767, -32768, 32767).astype("<i2").tobytes())


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("file", type=Path)
    p.add_argument("theme")
    p.add_argument("severity", choices=["warn", "critical"])
    p.add_argument("--source", default="", help="where the file came from (URL)")
    p.add_argument("--license", default="", help="license of the file")
    args = p.parse_args()

    x = prepare(decode(args.file))
    dst = SOUNDS / args.theme / f"{args.severity}.wav"
    write(x, dst)
    note = SOUNDS / args.theme / "SOURCE.md"
    lines = note.read_text(encoding="utf-8").splitlines() if note.exists() else [f"# Sound theme: {args.theme}", ""]
    lines = [l for l in lines if not l.startswith(f"- {args.severity}.wav")]
    lines.append(f"- {args.severity}.wav: from `{args.file.name}`"
                 + (f", source {args.source}" if args.source else "")
                 + (f", license: {args.license}" if args.license else ""))
    note.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{dst}  ({len(x) / RATE:.2f} s, peak {20 * np.log10(np.abs(x).max()):.1f} dBFS)")


if __name__ == "__main__":
    main()
