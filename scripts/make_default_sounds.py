"""Synthesizes the default alert sound theme into assets/sounds/default/.

warn.wav: a soft two-note bell chime. critical.wav: a brighter, insistent
three-pulse bell. Bell timbre = slightly inharmonic partials, each decaying at
its own rate (higher partials die faster), a smooth attack, overlapping notes
and a light reverb tail, at 44.1 kHz / 16-bit. Kept short and below full
scale so they stay noticeable without masking the game's own sounds.

Run: uv run python scripts/make_default_sounds.py
"""

import wave
from pathlib import Path

import numpy as np

RATE = 44100
OUT = Path(__file__).resolve().parents[1] / "assets" / "sounds" / "default"

# (frequency ratio, amplitude, decay time in s) of a soft bell
BELL = [(1.0, 1.0, 0.55), (2.0, 0.45, 0.30), (3.01, 0.22, 0.18), (4.17, 0.12, 0.10), (5.43, 0.06, 0.06)]


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
    place(warn, 0.8 * bell(880.00, 1.0), 0.00)    # A5
    place(warn, 1.0 * bell(1318.51, 0.95), 0.13)  # E6, overlapping the first note
    write("warn.wav", finish(reverb(warn), peak=0.42))

    critical = np.zeros(int(RATE * 1.0))
    for k, at in enumerate((0.0, 0.16, 0.32)):
        place(critical, bell(1174.66, 0.55, brightness=1.4), at)        # D6, brighter
        place(critical, 0.5 * bell(587.33, 0.55), at)                   # D5 body
    write("critical.wav", finish(reverb(critical, mix=0.12), peak=0.55))
    print(f"written to {OUT}")
