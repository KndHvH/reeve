"""Turns any audio into an alert sound: the same treatment for every source.

The samples arrive already decoded (mono float, 44.1 kHz): from ffmpeg in
scripts/import_sound.py, or from the hub, whose page decodes the chosen
file with the browser's Web Audio API, so end users need no ffmpeg. Here
leading silence is trimmed so the sound starts with the alert, the length is
capped (with a short fade-out) so it never plays over the game for long,
and the level is normalized so every sound plays at the same loudness. The
result is a 16-bit mono WAV, which winsound plays without dependencies.
"""

from __future__ import annotations

import re
import wave
from pathlib import Path

import numpy as np

RATE = 44100
MAX_S = 1.5          # longer sounds are cut, with a fade-out
FADE_S = 0.08
SILENCE = 0.02       # leading samples below this (relative to the peak) are trimmed
TARGET_RMS_DB = -14  # loudness target for the voiced part (keeps all sounds at the same level);
                     # the default volume of 50% plays it 12 dB lower, leaving room to turn it up
PEAK_LIMIT = 0.98    # just below full scale


def prepare(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64).copy()
    peak = np.abs(x).max() if len(x) else 0
    if peak == 0:
        raise ValueError("the file is silent")
    start = int(np.argmax(np.abs(x) > SILENCE * peak))
    x = x[max(0, start - int(0.002 * RATE)):]
    if len(x) > MAX_S * RATE:
        x = x[:int(MAX_S * RATE)]
    fade = min(len(x) // 4, int(FADE_S * RATE))
    if fade:
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


def safe_name(filename: str, taken: set[str]) -> str:
    """Library name from a file name: lowercase letters, digits and
    underscores, never clashing with an existing sound."""
    base = re.sub(r"[^a-z0-9]+", "_", Path(filename).stem.lower()).strip("_")[:40] or "sound"
    name, n = base, 2
    while name in taken:
        name, n = f"{base}_{n}", n + 1
    return name
