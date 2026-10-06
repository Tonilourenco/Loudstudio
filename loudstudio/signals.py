"""Test-signal generators.

All generators return float64 arrays in the range [-1, 1] where 1.0 is
digital full scale.  Levels are given in dBFS using the AES17 convention:
a full-scale sine wave is 0 dBFS.
"""

from __future__ import annotations

import numpy as np


def dbfs_to_amplitude(level_dbfs: float) -> float:
    """Peak amplitude of a sine wave with the given level in dBFS."""
    return float(10.0 ** (level_dbfs / 20.0))


def fade(x: np.ndarray, fs: int, fade_s: float = 0.01) -> np.ndarray:
    """Apply raised-cosine fade in/out to avoid clicks."""
    n = min(int(fade_s * fs), len(x) // 2)
    if n <= 0:
        return x
    ramp = 0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, n))
    y = x.copy()
    y[:n] *= ramp
    y[-n:] *= ramp[::-1]
    return y


def coherent_frequency(freq: float, fs: int, n: int) -> float:
    """Nudge ``freq`` so an integer number of cycles fits in ``n`` samples.

    This puts the fundamental exactly on an FFT bin, which keeps spectral
    leakage out of the harmonic/THD measurement.
    """
    cycles = max(1, round(freq * n / fs))
    return cycles * fs / n


def sine(freq: float, duration: float, fs: int, level_dbfs: float = -18.0,
         fade_s: float = 0.01) -> np.ndarray:
    t = np.arange(int(round(duration * fs))) / fs
    x = dbfs_to_amplitude(level_dbfs) * np.sin(2 * np.pi * freq * t)
    return fade(x, fs, fade_s)


def log_sweep(f1: float, f2: float, duration: float, fs: int,
              level_dbfs: float = -18.0) -> np.ndarray:
    """Exponential (Farina) sine sweep from ``f1`` to ``f2`` Hz."""
    n = int(round(duration * fs))
    t = np.arange(n) / fs
    k = np.log(f2 / f1)
    phase = 2 * np.pi * f1 * duration / k * (np.exp(t * k / duration) - 1.0)
    x = dbfs_to_amplitude(level_dbfs) * np.sin(phase)
    return fade(x, fs, 0.005)


def pink_noise(duration: float, fs: int, level_dbfs: float = -18.0,
               seed: int | None = 1234) -> np.ndarray:
    """Pink (1/f) noise scaled so its RMS equals a sine of ``level_dbfs``.

    Crest factor is limited to about 4 (12 dB) by soft clipping very rare
    peaks so the stimulus never clips the converter.
    """
    rng = np.random.default_rng(seed)
    n = int(round(duration * fs))
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / fs)
    shaping = np.ones_like(f)
    shaping[1:] = 1.0 / np.sqrt(f[1:])
    shaping[0] = 0.0
    shaping[f < 10.0] = 0.0
    x = np.fft.irfft(spec * shaping, n)
    x /= np.sqrt(np.mean(x ** 2))
    x = 4.0 * np.tanh(x / 4.0)
    target_rms = dbfs_to_amplitude(level_dbfs) / np.sqrt(2.0)
    x *= target_rms / np.sqrt(np.mean(x ** 2))
    return fade(x, fs, 0.02)


def pad(x: np.ndarray, fs: int, pre_s: float = 0.1, post_s: float = 0.5) -> np.ndarray:
    """Add silence before and after a stimulus to leave room for latency."""
    return np.concatenate([np.zeros(int(pre_s * fs)), x, np.zeros(int(post_s * fs))])
