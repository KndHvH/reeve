"""Synthesizes the default alert sound theme into assets/sounds/default/.

warn.wav: a soft two-note chime. critical.wav: three short, brighter beeps.
Kept short and moderately quiet so they stay noticeable without masking the
game's own sounds. Run: uv run python scripts/make_default_sounds.py
"""

import wave
from pathlib import Path

import numpy as np

RATE = 22050
OUT = Path(__file__).resolve().parents[1] / "assets" / "sounds" / "default"


def tone(freq: float, dur: float, decay: float, harmonics=(1.0, 0.3, 0.1)) -> np.ndarray:
    t = np.arange(int(RATE * dur)) / RATE
    wave_ = sum(a * np.sin(2 * np.pi * freq * (k + 1) * t) for k, a in enumerate(harmonics))
    attack = np.minimum(1.0, t / 0.005)  # 5 ms attack avoids clicks
    return wave_ * attack * np.exp(-t / decay)


def silence(dur: float) -> np.ndarray:
    return np.zeros(int(RATE * dur))


def write(name: str, signal: np.ndarray, peak: float) -> None:
    signal = signal / np.abs(signal).max() * peak
    OUT.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT / name), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((signal * 32767).astype("<i2").tobytes())


if __name__ == "__main__":
    warn = np.concatenate([tone(659.25, 0.18, 0.09), tone(880.0, 0.32, 0.14)])
    beep = tone(1046.5, 0.11, 0.06, harmonics=(1.0, 0.45, 0.25, 0.1))
    critical = np.concatenate([beep, silence(0.06), beep, silence(0.06), beep])
    write("warn.wav", warn, peak=0.35)
    write("critical.wav", critical, peak=0.45)
    print(f"written to {OUT}")
