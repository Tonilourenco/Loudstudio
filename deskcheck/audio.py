"""Audio back-ends: a real soundcard (via PortAudio/sounddevice) and a
simulated desk for testing without hardware.

Signal routing for a measurement::

    soundcard OUT (dut_out) ──► desk input ──► desk output ──► soundcard IN (dut_in)
    soundcard OUT (ref_out) ─────────── loopback cable ──────► soundcard IN (ref_in)

The optional loopback reference is strongly recommended: it records the
stimulus through the same converters, so the soundcard's own latency,
level calibration and frequency response cancel out of the results.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import signal as sps

from .analysis import fractional_shift


@dataclass
class Routing:
    dut_out: int = 1            # 1-based soundcard output feeding the desk
    dut_in: int = 1             # 1-based soundcard input fed by the desk
    ref_out: int | None = None  # 1-based output for loopback reference
    ref_in: int | None = None   # 1-based input for loopback reference

    @property
    def has_reference(self) -> bool:
        return self.ref_out is not None and self.ref_in is not None


class Backend:
    fs: int
    routing: Routing

    def playrec(self, stimulus: np.ndarray) -> tuple[np.ndarray, np.ndarray | None]:
        """Play ``stimulus`` and return ``(dut_recording, ref_recording)``.

        ``ref_recording`` is None when no loopback reference is configured.
        """
        raise NotImplementedError


def _import_sounddevice():
    try:
        import sounddevice as sd
    except OSError as exc:  # PortAudio shared library missing
        raise RuntimeError(
            "PortAudio library not found. Reinstall the sounddevice package (macOS/Windows), "
            "or on Debian/Ubuntu run `sudo apt install libportaudio2`, or use --simulate."
        ) from exc
    return sd


def list_devices() -> str:
    sd = _import_sounddevice()
    return str(sd.query_devices())


class SoundcardBackend(Backend):
    def __init__(self, fs: int = 48000, routing: Routing | None = None,
                 device: str | int | None = None, blocksize: int = 0,
                 latency: str | float = "high"):
        self.sd = _import_sounddevice()
        self.fs = fs
        self.routing = routing or Routing()
        self.device = device
        self.blocksize = blocksize
        self.latency = latency

    def playrec(self, stimulus):
        r = self.routing
        outs = [r.dut_out] + ([r.ref_out] if r.has_reference and r.ref_out != r.dut_out else [])
        ins = [r.dut_in] + ([r.ref_in] if r.has_reference else [])
        data = np.tile(np.asarray(stimulus, dtype=np.float32)[:, None], (1, len(outs)))
        rec = self.sd.playrec(
            data, samplerate=self.fs, output_mapping=outs, input_mapping=ins,
            device=self.device, blocking=True, dtype="float32",
            blocksize=self.blocksize, latency=self.latency,
        )
        rec = np.asarray(rec, dtype=float)
        dut = rec[:, 0]
        ref = rec[:, 1] if r.has_reference else None
        if np.max(np.abs(dut)) >= 0.999:
            print("WARNING: input clipping on the desk return channel - reduce desk output level")
        return dut, ref


# --------------------------------------------------------------------------
# Simulation
# --------------------------------------------------------------------------

def peaking_eq(f0: float, gain_db: float, q: float, fs: int) -> tuple[np.ndarray, np.ndarray]:
    """RBJ cookbook peaking EQ biquad."""
    a = 10 ** (gain_db / 40)
    w0 = 2 * np.pi * f0 / fs
    alpha = np.sin(w0) / (2 * q)
    b = np.array([1 + alpha * a, -2 * np.cos(w0), 1 - alpha * a])
    den = np.array([1 + alpha / a, -2 * np.cos(w0), 1 - alpha / a])
    return b / den[0], den / den[0]


@dataclass
class SimulatedDesk:
    """A crude model of a desk channel: gain, EQ, soft saturation, latency, noise."""
    gain_db: float = 0.0
    eq: list[tuple[float, float, float]] = field(default_factory=list)  # (f0, gain_db, Q)
    drive: float = 0.5          # higher = more harmonic distortion (0 = perfectly linear)
    latency_ms: float = 1.0
    noise_dbfs: float = -100.0
    invert: bool = False
    hpf_hz: float | None = None
    clip_dbfs: float | None = None  # hard clip of the desk output stage ("rails")

    def process(self, x: np.ndarray, fs: int, rng: np.random.Generator) -> np.ndarray:
        y = x * 10 ** (self.gain_db / 20)
        if self.hpf_hz:
            b, a = sps.butter(2, self.hpf_hz / (fs / 2), "highpass")
            y = sps.lfilter(b, a, y)
        for f0, g, q in self.eq:
            b, a = peaking_eq(f0, g, q, fs)
            y = sps.lfilter(b, a, y)
        if self.drive > 0:
            # Asymmetric soft clip -> both even and odd harmonics. The
            # asymmetry is scaled by drive so every harmonic grows with it
            # (an unscaled y**2 term would add a fixed H2 at any drive).
            y = (np.tanh(self.drive * (y + 0.05 * self.drive * y ** 2))) / self.drive
        if self.clip_dbfs is not None:
            rail = 10 ** (self.clip_dbfs / 20)
            y = np.clip(y, -rail, rail)
        if self.invert:
            y = -y
        y = fractional_shift(np.pad(y, (0, 64)), self.latency_ms * fs / 1000)[: len(y)]
        noise_rms = 10 ** (self.noise_dbfs / 20) / np.sqrt(2)
        return y + rng.standard_normal(len(y)) * noise_rms


class SimulatedBackend(Backend):
    """Soundcard + desk simulation, for trying the tool without hardware."""

    def __init__(self, fs: int = 48000, desk: SimulatedDesk | None = None,
                 card_latency_ms: float = 4.3, use_reference: bool = True, seed: int = 0):
        self.fs = fs
        self.desk = desk or SimulatedDesk()
        self.card_latency_ms = card_latency_ms
        self.routing = Routing(1, 1, 2, 2) if use_reference else Routing(1, 1)
        self.rng = np.random.default_rng(seed)

    def _card(self, x):
        d = self.card_latency_ms * self.fs / 1000
        y = fractional_shift(np.pad(x, (0, 64)), d)[: len(x)]
        y = y + self.rng.standard_normal(len(y)) * 10 ** (-115 / 20)
        return np.clip(y, -1.0, 1.0)  # converters clip at full scale

    def playrec(self, stimulus):
        x = np.asarray(stimulus, dtype=float)
        dut = self._card(self.desk.process(x, self.fs, self.rng))
        ref = self._card(x) if self.routing.has_reference else None
        return dut, ref
