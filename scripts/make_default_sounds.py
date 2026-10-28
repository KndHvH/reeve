"""Synthesizes two alert sounds into the sound library (assets/sounds/library/).

synth_bell.wav: a soft two-note bell chime. synth_triple_bell.wav: an
insistent three-pulse bell. Bell timbre = slightly inharmonic partials, each decaying at its own
rate (higher partials die faster), a smooth attack, overlapping notes and a
light reverb tail, at 44.1 kHz / 16-bit, then a gentle low-pass.

Levels are deliberately low (peak around -14 dBFS) and the spectrum stays
below ~4 kHz: louder or brighter versions made laptop speakers and headsets
distort. The overlay's `sound.volume` setting scales them further.

Run: uv run python scripts/make_default_sounds.py
"""

import wave
from pathlib import Path

import numpy as np

RATE = 44100
OUT = Path(__file__).resolve().parents[1] / "assets" / "sounds" / "library"

# (frequency ratio, amplitude, decay time in s) of a soft bell
BELL = [(1.0, 1.0, 0.55), (2.0, 0.35, 0.28), (3.01, 0.12, 0.15)]


def bell(freq: float, dur: float, partials=BELL, brightness: float = 1.0) -> np.ndarray:
    t = np.arange(int(RATE * dur)) / RATE
    out = np.zeros_like(t)
    for ratio, amp, decay in partials:
        f = freq * ratio
        if f >= RATE / 2:
            continue
        out += amp * (brightness if ratio > 1 else 1.0) * np.sin(2 * np.pi * f * t) * np.exp(-t / decay)
    attack = int(RATE * 0.004)
    out[:attack] *= 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, attack))  # raised-cosine attack, no click
    return out


def place(track: np.ndarray, sound: np.ndarray, at: float) -> None:
    i = int(RATE * at)
    end = min(len(track), i + len(sound))
    track[i:end] += sound[:end - i]


def reverb(x: np.ndarray, mix: float = 0.18) -> np.ndarray:
    """Small Schroeder-style reverb: parallel feedback combs, then a soft blend."""
    wet = np.zeros_like(x)
    for delay_ms, gain in [(29.7, 0.72), (37.1, 0.70), (41.1, 0.68), (43.7, 0.66)]:
        d = int(RATE * delay_ms / 1000)
        y = np.copy(x)
        for i in range(d, len(y), d):  # block-wise feedback: y[n] += g * y[n - d]
            y[i:i + d] += gain * y[i - d:i - d + len(y[i:i + d])]
        wet += y
    wet /= 4
    return (1 - mix) * x + mix * wet


def lowpass(x: np.ndarray, cutoff: float = 4000.0) -> np.ndarray:
    """One-pole low-pass, applied forward and backward (no phase shift)."""
    a = np.exp(-2 * np.pi * cutoff / RATE)
    for _ in range(2):
        y = np.empty_like(x)
        acc = 0.0
        for i, v in enumerate(x):
            acc = (1 - a) * v + a * acc
            y[i] = acc
        x = y[::-1]
    return x


def finish(x: np.ndarray, peak: float) -> np.ndarray:
    fade = int(RATE * 0.08)
    x[-fade:] *= np.linspace(1, 0, fade)
    return x / np.abs(x).max() * peak


def write(name: str, signal: np.ndarray) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    dither = (np.random.default_rng(0).random(len(signal)) - 0.5) / 32767
    pcm = np.clip((signal + dither) * 32767, -32768, 32767).astype("<i2")
    with wave.open(str(OUT / name), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())


if __name__ == "__main__":
    warn = np.zeros(int(RATE * 1.1))
    place(warn, 0.8 * bell(659.25, 1.0), 0.00)    # E5
    place(warn, 1.0 * bell(880.00, 0.95), 0.13)   # A5, overlapping the first note
    write("synth_bell.wav", finish(lowpass(reverb(warn)), peak=0.2))

    critical = np.zeros(int(RATE * 1.0))
    for at in (0.0, 0.16, 0.32):
        place(critical, bell(880.00, 0.55), at)          # A5
        place(critical, 0.5 * bell(440.00, 0.55), at)    # A4 body
    write("synth_triple_bell.wav", finish(lowpass(reverb(critical, mix=0.12)), peak=0.24))
    print(f"written to {OUT}")
