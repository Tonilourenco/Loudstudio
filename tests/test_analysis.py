import numpy as np
import pytest
from scipy import signal as sps

from deskcheck import analysis as an
from deskcheck import signals as sig
from deskcheck.audio import SimulatedBackend, SimulatedDesk, peaking_eq
from deskcheck.measure import Measurer

FS = 48000


def test_rms_dbfs_full_scale_sine_is_0():
    assert an.rms_dbfs(np.sin(2 * np.pi * 1000 * np.arange(FS) / FS)) == pytest.approx(0, abs=0.01)


@pytest.mark.parametrize("delay", [0.0, 37.0, 123.4, 1000.75])
def test_estimate_delay_subsample(delay):
    x = sig.pad(sig.log_sweep(20, 20000, 0.5, FS), FS)
    y = an.fractional_shift(np.pad(x, (0, 2048)), delay)[: len(x)]
    d, strength = an.estimate_delay(x, y, FS)
    assert d == pytest.approx(delay, abs=0.05)
    assert strength > 0.9


def test_harmonic_analysis_known_distortion():
    n = FS
    f0 = sig.coherent_frequency(1000, FS, n)
    t = np.arange(n) / FS
    x = 0.5 * np.sin(2 * np.pi * f0 * t)
    x += 0.5 * 0.01 * np.sin(2 * np.pi * 2 * f0 * t)     # H2 -40 dBc
    x += 0.5 * 0.001 * np.sin(2 * np.pi * 3 * f0 * t)    # H3 -60 dBc
    h = an.harmonic_analysis(x, FS, 1000)
    assert h.fundamental_dbfs == pytest.approx(20 * np.log10(0.5), abs=0.01)
    assert h.harmonics_dbc[0] == pytest.approx(-40, abs=0.1)
    assert h.harmonics_dbc[1] == pytest.approx(-60, abs=0.1)
    assert h.thd_percent == pytest.approx(100 * np.hypot(0.01, 0.001), rel=0.01)


def test_transfer_function_matches_eq_phase():
    b, a = peaking_eq(1000, 6, 1.0, FS)
    x = sig.pad(sig.log_sweep(10, 23000, 2.0, FS), FS)
    y = an.fractional_shift(np.pad(sps.lfilter(b, a, x), (0, 64)), 50.3)[: len(x)]
    # Automatic alignment: delay found from the correlation peak.
    tf = an.transfer_function(x, y, FS)
    _, h = sps.freqz(b, a, worN=tf.freq, fs=FS)
    sel = (tf.freq > 50) & (tf.freq < 15000)
    assert np.max(np.abs(tf.magnitude_db[sel] - 20 * np.log10(np.abs(h[sel])))) < 0.1
    assert tf.delay_samples == pytest.approx(50.3, abs=0.05)
    lf = sel & (tf.freq < 5000)
    assert np.max(np.abs(tf.phase_deg[lf] - np.degrees(np.angle(h[lf])))) < 1.0

    # Known delay (as with --align-to): phase matches the filter exactly.
    tf = an.transfer_function(x, y, FS, delay=50.3)
    assert np.max(np.abs(tf.phase_deg[sel] - np.degrees(np.angle(h[sel])))) < 0.5


def test_correlation_detects_inversion():
    x = sig.pad(sig.pink_noise(2.0, FS), FS)
    y = -an.fractional_shift(np.pad(x, (0, 512)), 200)[: len(x)]
    c = an.correlation_analysis(x, y, FS)
    assert c.polarity == "inverted"
    assert c.correlation < -0.99
    assert c.mean_coherence > 0.99


@pytest.mark.parametrize("use_ref", [True, False])
def test_simulated_desk_end_to_end(use_ref):
    desk = SimulatedDesk(gain_db=6.0, drive=0.0, latency_ms=2.0)
    m = Measurer(SimulatedBackend(FS, desk, card_latency_ms=4.0, use_reference=use_ref))
    lat = m.latency(repeats=1)
    assert lat["total_roundtrip_ms"] == pytest.approx(6.0, abs=0.01)
    if use_ref:
        assert lat["desk_latency_ms"] == pytest.approx(2.0, abs=0.01)
    assert m.gain()["gain_db"] == pytest.approx(6.0, abs=0.05)
    resp = m.response()
    assert np.ptp(np.array(resp["magnitude_db"])[np.array(resp["freq"]) > 40]) < 0.2
    assert m.correlation()["correlation"] > 0.999
    assert m.thd()[0]["thd_percent"] < 0.01


def test_level_sweep_finds_desk_clip_point():
    # +10 dB gain into an output stage that hard-clips at -6 dBFS:
    # the sine starts clipping at -16 dBFS in, and 1 % THD+N needs a few
    # tenths of a dB more.
    desk = SimulatedDesk(gain_db=10.0, drive=0.0, clip_dbfs=-6.0, noise_dbfs=-80)
    sw = Measurer(SimulatedBackend(FS, desk)).level_sweep(start_dbfs=-60, stop_dbfs=0, step_db=3)
    assert -16.0 < sw["clip_input_dbfs"] < -15.3
    assert sw["clip_output_dbfs"] == pytest.approx(-6.0, abs=0.5)
    assert sw["limited_by"] == "desk"
    # Low-level points are noisy (THD+N > 1 % at -60 dBFS) but must not count as clipping.
    assert sw["points"][0]["thdn_percent"] > 1.0


def test_level_sweep_reports_soundcard_input_limit():
    desk = SimulatedDesk(gain_db=10.0, drive=0.0)  # desk clean, interface input clips at 0 dBFS
    sw = Measurer(SimulatedBackend(FS, desk)).level_sweep(start_dbfs=-20, stop_dbfs=0, step_db=2)
    assert sw["limited_by"] == "soundcard input"
    assert sw["clip_input_dbfs"] == pytest.approx(-10.0, abs=0.5)


def test_level_sweep_clean_desk_not_reached():
    desk = SimulatedDesk(gain_db=-6.0, drive=0.0)
    sw = Measurer(SimulatedBackend(FS, desk)).level_sweep(start_dbfs=-20, stop_dbfs=-2, step_db=6)
    assert sw["clip_input_dbfs"] is None
    assert sw["limited_by"] == "not reached"


def test_simulated_saturation_scales_with_drive():
    # Distortion must come from the drive setting: near-zero drive is near-clean,
    # and more drive means more distortion.
    def thd(drive):
        desk = SimulatedDesk(drive=drive)
        return Measurer(SimulatedBackend(FS, desk)).thd()[0]["thd_percent"]

    low, mid, high = thd(0.05), thd(0.3), thd(1.0)
    assert low < 0.05
    assert low < mid < high
