"""Signal analysis: levels, delay, harmonic distortion, transfer function,
coherence and correlation.

Everything here is pure numpy/scipy and independent of the audio hardware,
so it can be unit-tested with synthetic signals.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import signal as sps
from scipy.optimize import minimize_scalar

EPS = 1e-20


# --------------------------------------------------------------------------
# Levels
# --------------------------------------------------------------------------

def rms_dbfs(x: np.ndarray) -> float:
    """RMS level in dBFS (AES17: full-scale sine = 0 dBFS)."""
    rms = np.sqrt(np.mean(np.asarray(x, dtype=float) ** 2))
    return float(20 * np.log10(rms * np.sqrt(2) + EPS))


def peak_dbfs(x: np.ndarray) -> float:
    return float(20 * np.log10(np.max(np.abs(x)) + EPS))


# --------------------------------------------------------------------------
# Delay / latency
# --------------------------------------------------------------------------

def _parabolic(y: np.ndarray, i: int) -> float:
    """Sub-sample peak position by fitting a parabola through 3 points."""
    if i <= 0 or i >= len(y) - 1:
        return float(i)
    a, b, c = y[i - 1], y[i], y[i + 1]
    denom = a - 2 * b + c
    if denom == 0:
        return float(i)
    return i + 0.5 * (a - c) / denom


def estimate_delay(ref: np.ndarray, sig: np.ndarray, fs: int,
                   max_delay_s: float | None = 1.0,
                   upsample: int = 16) -> tuple[float, float]:
    """Delay of ``sig`` relative to ``ref`` in samples (positive = sig is late).

    Uses band-limited GCC-PHAT (generalised cross-correlation with phase
    transform), which gives a sharp peak even through EQ and colouration.
    The correlation is upsampled in the frequency domain for sub-sample
    accuracy.

    Returns ``(delay_samples, peak_strength)`` where peak_strength is in
    0..1 (close to 1 means an unambiguous detection).
    """
    ref = np.asarray(ref, dtype=float)
    sig = np.asarray(sig, dtype=float)
    n = int(2 ** np.ceil(np.log2(len(ref) + len(sig))))
    R = np.fft.rfft(ref, n)
    S = np.fft.rfft(sig, n)
    cross = S * np.conj(R)
    mag = np.abs(cross)
    # Only trust bins where the reference actually has energy.
    ref_pow = np.abs(R) ** 2
    mask = ref_pow > ref_pow.max() * 1e-6
    weighted = np.where(mask, cross / (mag + EPS), 0.0)
    cc = np.fft.irfft(weighted, n * upsample) * upsample
    max_lag = (n // 2) * upsample if max_delay_s is None else int(max_delay_s * fs * upsample)
    max_lag = min(max_lag, (n * upsample) // 2 - 1)
    lags_pos = cc[: max_lag + 1]
    lags_neg = cc[-max_lag:] if max_lag > 0 else np.empty(0)
    # Use |cc| so a polarity-inverted path (negative peak) is found too.
    window = np.abs(np.concatenate([lags_neg, lags_pos]))
    i = int(np.argmax(window))
    peak = _parabolic(window, i)
    lag = (peak - len(lags_neg)) / upsample
    # Polish: evaluate the band-limited correlation exactly (no interpolation
    # error) around the coarse peak. Phase at 20 kHz is sensitive to even
    # 0.01-sample errors.
    k = np.arange(len(weighted))
    sign = np.sign(cc[int(round(lag * upsample)) % len(cc)]) or 1.0

    def neg_cc(tau):
        return -sign * np.real(np.sum(weighted * np.exp(2j * np.pi * k * tau / n)))

    opt = minimize_scalar(neg_cc, bounds=(lag - 1.0 / upsample, lag + 1.0 / upsample),
                          method="bounded", options={"xatol": 1e-5})
    lag = float(opt.x)
    # A perfect match gives a peak of 2*m/n for m unit-magnitude bins.
    strength = float(np.clip(window[i] * n / (2 * max(np.count_nonzero(mask), 1)), 0.0, 1.0))
    return float(lag), strength


def fractional_shift(x: np.ndarray, delay: float) -> np.ndarray:
    """Delay ``x`` by ``delay`` samples (can be fractional/negative), same length.

    Circular FFT shift - pad the signal first if wrap-around matters.
    """
    n = len(x)
    X = np.fft.rfft(x)
    k = np.fft.rfftfreq(n)
    return np.fft.irfft(X * np.exp(-2j * np.pi * k * delay), n)


def align(ref: np.ndarray, sig: np.ndarray, delay: float) -> tuple[np.ndarray, np.ndarray]:
    """Shift ``sig`` back by ``delay`` samples and trim both to equal length."""
    n = max(len(ref), len(sig))
    pad = int(np.ceil(abs(delay))) + 16
    r = np.pad(ref, (0, n - len(ref) + pad))
    s = np.pad(sig, (0, n - len(sig) + pad))
    s = fractional_shift(s, -delay)
    return r[:n], s[:n]


# --------------------------------------------------------------------------
# Harmonic distortion
# --------------------------------------------------------------------------

@dataclass
class HarmonicResult:
    fundamental_hz: float
    fundamental_dbfs: float
    thd_percent: float | None   # None when no harmonic falls in band
    thd_db: float | None
    thdn_percent: float
    thdn_db: float
    harmonics_dbc: list[float] = field(default_factory=list)   # H2, H3, ...
    spectrum_freq: np.ndarray | None = None
    spectrum_dbfs: np.ndarray | None = None

    def to_dict(self, include_spectrum: bool = False) -> dict:
        d = {
            "fundamental_hz": self.fundamental_hz,
            "fundamental_dbfs": self.fundamental_dbfs,
            "thd_percent": self.thd_percent,
            "thd_db": self.thd_db,
            "thdn_percent": self.thdn_percent,
            "thdn_db": self.thdn_db,
            "harmonics_dbc": self.harmonics_dbc,
        }
        if include_spectrum and self.spectrum_freq is not None:
            d["spectrum_freq"] = self.spectrum_freq.tolist()
            d["spectrum_dbfs"] = self.spectrum_dbfs.tolist()
        return d


def harmonic_analysis(x: np.ndarray, fs: int, f0: float, n_harmonics: int = 9,
                      f_low: float = 20.0, f_high: float = 20000.0,
                      lobe_bins: int = 5) -> HarmonicResult:
    """THD and THD+N of a steady-state sine recording.

    THD   = sqrt(sum of harmonic powers H2..Hn) / fundamental
    THD+N = everything in [f_low, f_high] except the fundamental / fundamental

    A 4-term Blackman-Harris window keeps leakage below -92 dB.
    """
    x = np.asarray(x, dtype=float)
    x = x - np.mean(x)
    n = len(x)
    w = sps.windows.blackmanharris(n)
    X = np.fft.rfft(x * w)
    # Mean-square power per bin, one-sided, calibrated so that summing
    # the bins of a sine's main lobe gives A^2/2.
    p = 2.0 * np.abs(X) ** 2 / (n * np.sum(w ** 2))
    p[0] /= 2.0
    freqs = np.fft.rfftfreq(n, 1 / fs)
    df = fs / n

    def band_power(fc: float, search: int = 3) -> tuple[float, float]:
        k = int(round(fc / df))
        lo, hi = max(k - search, 0), min(k + search + 1, len(p))
        if lo >= hi:
            return 0.0, fc
        k = lo + int(np.argmax(p[lo:hi]))
        a, b = max(k - lobe_bins, 0), min(k + lobe_bins + 1, len(p))
        return float(np.sum(p[a:b])), float(freqs[k])

    # Fundamental: search within +-2% to tolerate sample-rate mismatch.
    p1, f1 = band_power(f0, search=max(3, int(0.02 * f0 / df)))
    harm_powers = []
    for h in range(2, n_harmonics + 1):
        fh = h * f1
        if fh >= min(f_high, fs / 2 - lobe_bins * df):
            break
        ph, _ = band_power(fh)
        harm_powers.append(ph)

    band = (freqs >= f_low) & (freqs <= f_high)
    k1 = int(round(f1 / df))
    notch = (np.arange(len(p)) >= k1 - lobe_bins) & (np.arange(len(p)) <= k1 + lobe_bins)
    pn = float(np.sum(p[band & ~notch]))

    thdn = np.sqrt(pn) / np.sqrt(p1 + EPS)
    if harm_powers:
        thd = np.sqrt(np.sum(harm_powers)) / np.sqrt(p1 + EPS)
        thd_pct, thd_db = float(100 * thd), float(20 * np.log10(thd + EPS))
    else:  # no harmonic falls inside the analysis band (e.g. f0 > 10 kHz)
        thd_pct = thd_db = None
    return HarmonicResult(
        fundamental_hz=f1,
        fundamental_dbfs=float(10 * np.log10(2 * p1 + EPS)),
        thd_percent=thd_pct,
        thd_db=thd_db,
        thdn_percent=float(100 * thdn),
        thdn_db=float(20 * np.log10(thdn + EPS)),
        harmonics_dbc=[float(10 * np.log10(ph / (p1 + EPS) + EPS)) for ph in harm_powers],
        spectrum_freq=freqs,
        spectrum_dbfs=10 * np.log10(2 * p + EPS),
    )


# --------------------------------------------------------------------------
# Transfer function (frequency response, phase, group delay)
# --------------------------------------------------------------------------

@dataclass
class TransferResult:
    freq: np.ndarray            # log-spaced analysis frequencies (Hz)
    magnitude_db: np.ndarray    # gain vs frequency (dB)
    phase_deg: np.ndarray       # phase with bulk delay removed (deg)
    group_delay_ms: np.ndarray  # excess group delay (ms)
    delay_samples: float        # bulk delay that was removed
    fs: int

    def value_at(self, f: float) -> tuple[float, float]:
        """Interpolated (magnitude_db, phase_deg) at frequency f."""
        lf = np.log10(self.freq)
        return (float(np.interp(np.log10(f), lf, self.magnitude_db)),
                float(np.interp(np.log10(f), lf, self.phase_deg)))

    def to_dict(self) -> dict:
        return {
            "freq": self.freq.tolist(),
            "magnitude_db": self.magnitude_db.tolist(),
            "phase_deg": self.phase_deg.tolist(),
            "group_delay_ms": self.group_delay_ms.tolist(),
            "delay_samples": self.delay_samples,
            "delay_ms": 1000 * self.delay_samples / self.fs,
        }


def log_frequencies(f1: float, f2: float, per_octave: int = 24) -> np.ndarray:
    n = int(np.ceil(np.log2(f2 / f1) * per_octave)) + 1
    return f1 * 2.0 ** (np.arange(n) / per_octave)


def smooth_complex(f: np.ndarray, H: np.ndarray, centres: np.ndarray,
                   fraction: int = 24) -> np.ndarray:
    """Fractional-octave complex smoothing of H onto ``centres``.

    Averaging the complex response (rather than magnitude only) keeps
    magnitude and phase consistent with each other.
    """
    half = 2.0 ** (1.0 / (2 * fraction))
    out = np.empty(len(centres), dtype=complex)
    csum = np.concatenate([[0], np.cumsum(H)])
    for i, fc in enumerate(centres):
        a = np.searchsorted(f, fc / half)
        b = np.searchsorted(f, fc * half, side="right")
        if b <= a:
            out[i] = np.interp(fc, f, H.real) + 1j * np.interp(fc, f, H.imag)
        else:
            out[i] = (csum[b] - csum[a]) / (b - a)
    return out


def transfer_function(ref: np.ndarray, sig: np.ndarray, fs: int,
                      f1: float = 20.0, f2: float = 20000.0,
                      fraction: int = 24, delay: float | None = None) -> TransferResult:
    """Frequency response of ``sig`` relative to ``ref`` (dual-channel FFT).

    ``ref`` is either the digital stimulus or a loopback recording of it;
    in the latter case the soundcard's own response cancels out.

    The bulk (latency) delay is removed before computing phase so the phase
    plot shows the EQ/filter phase shift, not a linear phase ramp.
    """
    ref = np.asarray(ref, dtype=float)
    sig = np.asarray(sig, dtype=float)
    n = int(2 ** np.ceil(np.log2(max(len(ref), len(sig)))))
    R = np.fft.rfft(ref, n)
    S = np.fft.rfft(sig, n)
    rp = np.abs(R) ** 2
    H = S * np.conj(R) / (rp + rp.max() * 1e-8)
    f = np.fft.rfftfreq(n, 1 / fs)

    if delay is None:
        delay, _ = estimate_delay(ref, sig, fs)
    H = H * np.exp(2j * np.pi * f * delay / fs)

    centres = log_frequencies(f1, min(f2, 0.45 * fs), fraction)
    Hs = smooth_complex(f, H, centres, fraction)
    mag = 20 * np.log10(np.abs(Hs) + EPS)
    phase = np.unwrap(np.angle(Hs))
    # Pin the unwrap so the mid-band phase sits within +-180 deg.
    k_mid = int(np.argmin(np.abs(centres - 1000.0)))
    phase -= 2 * np.pi * np.round(phase[k_mid] / (2 * np.pi))
    omega = 2 * np.pi * centres
    gd = -np.gradient(phase, omega)
    # Differentiating amplifies ripple; smooth over ~1/3 octave.
    k = max(1, fraction // 3)
    gd = np.convolve(np.pad(gd, k, mode="edge"), np.ones(2 * k + 1) / (2 * k + 1), "valid")
    return TransferResult(
        freq=centres,
        magnitude_db=mag,
        phase_deg=np.degrees(phase),
        group_delay_ms=1000 * gd,
        delay_samples=float(delay),
        fs=fs,
    )


# --------------------------------------------------------------------------
# Correlation and coherence
# --------------------------------------------------------------------------

@dataclass
class CorrelationResult:
    correlation: float          # Pearson coefficient after time alignment (-1..+1)
    polarity: str               # "normal" or "inverted"
    delay_samples: float
    freq: np.ndarray
    coherence: np.ndarray       # magnitude-squared coherence 0..1
    phase_deg: np.ndarray       # H1 phase (deg), delay removed
    mean_coherence: float       # averaged over 100 Hz - 10 kHz

    def to_dict(self) -> dict:
        return {
            "correlation": self.correlation,
            "polarity": self.polarity,
            "delay_samples": self.delay_samples,
            "freq": self.freq.tolist(),
            "coherence": self.coherence.tolist(),
            "phase_deg": self.phase_deg.tolist(),
            "mean_coherence": self.mean_coherence,
        }


def correlation_analysis(ref: np.ndarray, sig: np.ndarray, fs: int,
                         delay: float | None = None,
                         nperseg: int = 8192) -> CorrelationResult:
    """How faithfully ``sig`` follows ``ref``.

    * correlation: time-aligned Pearson coefficient, like a phase-correlation
      meter (+1 identical shape, 0 unrelated, -1 polarity inverted).
    * coherence: per-frequency linearity (1 = output fully explained by the
      input; drops with noise, distortion, or time-variant processing).
    """
    if delay is None:
        delay, _ = estimate_delay(ref, sig, fs)
    r, s = align(ref, sig, delay)
    active = np.abs(r) > np.max(np.abs(r)) * 1e-3
    idx = np.flatnonzero(active)
    if len(idx):
        r, s = r[idx[0]: idx[-1] + 1], s[idx[0]: idx[-1] + 1]
    rr, ss = r - r.mean(), s - s.mean()
    corr = float(np.sum(rr * ss) / (np.sqrt(np.sum(rr ** 2) * np.sum(ss ** 2)) + EPS))

    nperseg = min(nperseg, len(r))
    f, coh = sps.coherence(r, s, fs=fs, nperseg=nperseg)
    _, pxy = sps.csd(r, s, fs=fs, nperseg=nperseg)
    phase = np.degrees(np.angle(pxy))
    band = (f >= 100) & (f <= 10000)
    return CorrelationResult(
        correlation=corr,
        polarity="inverted" if corr < 0 else "normal",
        delay_samples=float(delay),
        freq=f[1:],
        coherence=coh[1:],
        phase_deg=phase[1:],
        mean_coherence=float(np.mean(coh[band])) if np.any(band) else float("nan"),
    )
