"""High-level measurements built from a back-end and the analysis functions."""

from __future__ import annotations

import datetime as _dt

import numpy as np

from . import analysis as an
from . import signals as sig
from .audio import Backend

PRE_S = 0.1     # silence before each stimulus
POST_S = 0.6    # silence after (must exceed the longest latency you expect)

ALL_MEASUREMENTS = ("latency", "gain", "thd", "response", "correlation")


class Measurer:
    """Runs measurements against a back-end.

    Calibration (optional, for absolute dBu figures and for gain when no
    loopback reference is used):

    * ``cal_out_dbu``: dBu at the soundcard output for a 0 dBFS sine
      (often +18 or +24 dBu - see your interface's spec or measure it).
    * ``cal_in_dbu``: dBu at the soundcard input that reads 0 dBFS.
    """

    def __init__(self, backend: Backend, level_dbfs: float = -18.0,
                 cal_out_dbu: float | None = None, cal_in_dbu: float | None = None):
        self.b = backend
        self.fs = backend.fs
        self.level = level_dbfs
        self.cal_out = cal_out_dbu
        self.cal_in = cal_in_dbu

    # -- helpers -----------------------------------------------------------

    def _play(self, stimulus: np.ndarray):
        x = sig.pad(stimulus, self.fs, PRE_S, POST_S)
        dut, ref = self.b.playrec(x)
        return x, dut, ref

    def _cal_offset(self) -> float:
        """dB to add to (dut_dbfs - stimulus_dbfs) to obtain analogue gain."""
        return (self.cal_in or 0.0) - (self.cal_out or 0.0)

    def _steady(self, x: np.ndarray, duration: float, n: int) -> np.ndarray:
        """Exactly ``n`` samples from the steady-state middle of a padded tone."""
        start = int((PRE_S + (duration - n / self.fs) / 2) * self.fs)
        return x[start: start + n]

    # -- latency -----------------------------------------------------------

    def latency(self, repeats: int = 3) -> dict:
        """Round-trip latency using a log sweep and GCC-PHAT."""
        stim = sig.log_sweep(20, min(20000, 0.45 * self.fs), 1.0, self.fs, self.level)
        totals, cards, strengths = [], [], []
        for _ in range(repeats):
            x, dut, ref = self._play(stim)
            d, s = an.estimate_delay(x, dut, self.fs)
            totals.append(d)
            strengths.append(s)
            if ref is not None:
                cards.append(an.estimate_delay(x, ref, self.fs)[0])
        ms = lambda v: float(1000 * v / self.fs)  # noqa: E731
        res = {
            "total_roundtrip_ms": ms(np.mean(totals)),
            "total_roundtrip_samples": float(np.mean(totals)),
            "jitter_ms": ms(np.std(totals)),
            "detection_strength": float(np.mean(strengths)),
            "runs_ms": [ms(t) for t in totals],
        }
        if cards:
            desk = np.array(totals) - np.array(cards)
            res.update({
                "soundcard_loopback_ms": ms(np.mean(cards)),
                "desk_latency_ms": ms(np.mean(desk)),
                "desk_latency_samples": float(np.mean(desk)),
            })
        if res["detection_strength"] < 0.2:
            res["warning"] = "weak correlation peak - check routing and levels"
        return res

    # -- gain --------------------------------------------------------------

    def gain(self, freq: float = 1000.0, duration: float = 2.0) -> dict:
        n = int(duration * self.fs * 0.5)
        f = sig.coherent_frequency(freq, self.fs, n)
        stim = sig.sine(f, duration, self.fs, self.level)
        x, dut, ref = self._play(stim)
        seg_dut = self._steady(dut, duration, n)
        h_dut = an.harmonic_analysis(seg_dut, self.fs, f)
        res = {
            "frequency_hz": f,
            "stimulus_dbfs": self.level,
            "output_dbfs": h_dut.fundamental_dbfs,
            "output_rms_dbfs": an.rms_dbfs(seg_dut),
        }
        if ref is not None:
            h_ref = an.harmonic_analysis(self._steady(ref, duration, n), self.fs, f)
            res["reference_dbfs"] = h_ref.fundamental_dbfs
            res["gain_db"] = h_dut.fundamental_dbfs - h_ref.fundamental_dbfs
            res["method"] = "dual-channel (loopback reference)"
        else:
            res["gain_db"] = h_dut.fundamental_dbfs - self.level + self._cal_offset()
            res["method"] = "single-channel (calibration offsets)"
        if self.cal_out is not None:
            res["desk_input_dbu"] = self.level + self.cal_out
        if self.cal_in is not None:
            res["desk_output_dbu"] = h_dut.fundamental_dbfs + self.cal_in
        res["output_clipping"] = bool(np.max(np.abs(dut)) >= 0.999)
        return res

    # -- distortion --------------------------------------------------------

    def thd(self, freqs=(1000.0,), levels=None, duration: float = 2.0) -> list[dict]:
        levels = list(levels) if levels is not None else [self.level]
        self._last_spectrum = None
        n = int(duration * self.fs * 0.5)
        out = []
        for level in levels:
            for freq in freqs:
                f = sig.coherent_frequency(freq, self.fs, n)
                _, dut, ref = self._play(sig.sine(f, duration, self.fs, level))
                h = an.harmonic_analysis(self._steady(dut, duration, n), self.fs, f)
                row = {"stimulus_dbfs": level, **h.to_dict()}
                if ref is not None:
                    hr = an.harmonic_analysis(self._steady(ref, duration, n), self.fs, f)
                    row["soundcard_thd_percent"] = hr.thd_percent
                    row["soundcard_thdn_percent"] = hr.thdn_percent
                out.append(row)
                # Keep the spectrum nearest 1 kHz for plotting.
                prev = getattr(self, "_last_spectrum", None)
                if prev is None or abs(np.log(f / 1000)) <= abs(np.log(prev.fundamental_hz / 1000)):
                    self._last_spectrum = h
        return out

    # -- frequency / phase response -------------------------------------

    def response(self, duration: float = 3.0, fraction: int = 24,
                 delay_samples: float | None = None) -> dict:
        """Magnitude/phase response.

        By default the latency removed before computing phase is the
        correlation peak. For precise EQ phase-shift comparisons pass
        ``delay_samples`` from a flat (EQ bypassed) measurement of the same
        desk, so the EQ's phase is not partly absorbed into the delay.
        """
        f_hi = min(24000.0, 0.48 * self.fs)
        stim = sig.log_sweep(10.0, f_hi, duration, self.fs, self.level)
        x, dut, ref = self._play(stim)
        reference = ref if ref is not None else x
        tf = an.transfer_function(reference, dut, self.fs, 20.0, 20000.0, fraction,
                                  delay=delay_samples)
        if ref is None:
            tf.magnitude_db = tf.magnitude_db + self._cal_offset()
        res = tf.to_dict()
        g1k, p1k = tf.value_at(1000.0)
        res.update({"gain_1k_db": g1k, "phase_1k_deg": p1k,
                    "method": "dual-channel" if ref is not None else "single-channel"})
        return res

    # -- correlation / coherence ------------------------------------------

    def correlation(self, duration: float = 5.0) -> dict:
        stim = sig.pink_noise(duration, self.fs, self.level)
        x, dut, ref = self._play(stim)
        reference = ref if ref is not None else x
        c = an.correlation_analysis(reference, dut, self.fs)
        # Store coherence on a 1/12-octave grid to keep result files small.
        grid = an.log_frequencies(20.0, min(20000.0, 0.45 * self.fs), 12)
        return {
            "correlation": c.correlation,
            "polarity": c.polarity,
            "mean_coherence_100_10k": c.mean_coherence,
            "freq": grid.tolist(),
            "coherence": np.interp(grid, c.freq, c.coherence).tolist(),
        }

    # -- level sweep / clip point -------------------------------------------

    def level_sweep(self, start_dbfs: float = -40.0, stop_dbfs: float = 0.0,
                    step_db: float = 2.0, freq: float = 1000.0,
                    threshold_percent: float = 1.0, duration: float = 0.6,
                    stop_after_db: float = 6.0, refine: int = 4, progress=None) -> dict:
        """Step a sine up in level to find where the desk clips.

        At each step: output level, gain, THD and THD+N. The clip point is
        where THD+N first rises through ``threshold_percent`` (1 % is the
        usual "maximum level" spec), interpolated between steps. Also
        reports the 1 dB gain-compression point.

        The sweep stops early once the soundcard input clips, or once it is
        ``stop_after_db`` past the clip point, to avoid driving the desk
        hard for no reason.
        """
        n = int(duration * self.fs * 0.5)
        f = sig.coherent_frequency(freq, self.fs, n)

        def measure_at(level: float) -> dict:
            if progress:
                progress(f"Level sweep: {level:+.2f} dBFS")
            _, dut, ref = self._play(sig.sine(f, duration, self.fs, level))
            seg = self._steady(dut, duration, n)
            h = an.harmonic_analysis(seg, self.fs, f)
            p = {
                "input_dbfs": level,
                "output_dbfs": h.fundamental_dbfs,
                "thd_percent": h.thd_percent,
                "thdn_percent": h.thdn_percent,
                "input_clipped": bool(np.max(np.abs(seg)) >= 0.999),
            }
            if ref is not None:
                hr = an.harmonic_analysis(self._steady(ref, duration, n), self.fs, f)
                p["gain_db"] = h.fundamental_dbfs - hr.fundamental_dbfs
                p["soundcard_thdn_percent"] = hr.thdn_percent
            else:
                p["gain_db"] = h.fundamental_dbfs - level + self._cal_offset()
            return p

        points = []
        crossed_at = None
        for level in np.arange(start_dbfs, stop_dbfs + 1e-9, step_db):
            points.append(measure_at(float(level)))
            if points[-1]["input_clipped"]:
                break
            if crossed_at is None and self._crossing(points, threshold_percent) is not None:
                crossed_at = level
            if crossed_at is not None and level >= crossed_at + stop_after_db:
                break

        # Bisect between the two steps that straddle the threshold, so a hard
        # clip is located to ~step/2^refine instead of +-step.
        bracket = self._bracket(points, threshold_percent)
        if bracket is not None:
            lo, hi = bracket
            for _ in range(refine):
                mid = (lo + hi) / 2
                p = measure_at(mid)
                points.append(p)
                if p["thdn_percent"] >= threshold_percent or p["input_clipped"]:
                    hi = mid
                else:
                    lo = mid
            points.sort(key=lambda p: p["input_dbfs"])

        res = {"frequency_hz": f, "threshold_percent": threshold_percent,
               "points": points, **self._clip_summary(points, threshold_percent)}
        if self.cal_out is not None and res["clip_input_dbfs"] is not None:
            res["clip_input_dbu"] = res["clip_input_dbfs"] + self.cal_out
        if self.cal_in is not None and res["clip_output_dbfs"] is not None:
            res["clip_output_dbu"] = res["clip_output_dbfs"] + self.cal_in
        return res

    @staticmethod
    def _first_over(points: list[dict], thr: float) -> int | None:
        """Index of the first step whose THD+N reaches ``thr``.

        Only looks above the THD+N minimum: at low levels THD+N is dominated
        by noise and can exceed the threshold without anything clipping.
        """
        thdn = np.array([p["thdn_percent"] for p in points])
        i_min = int(np.argmin(thdn))
        for i in range(i_min + 1, len(points)):
            if thdn[i] >= thr:
                return i
        return None

    @classmethod
    def _bracket(cls, points, thr) -> tuple[float, float] | None:
        i = cls._first_over(points, thr)
        if i is None:
            return None
        return points[i - 1]["input_dbfs"], points[i]["input_dbfs"]

    @classmethod
    def _crossing(cls, points: list[dict], thr: float) -> float | None:
        """Interpolated input level where THD+N rises through ``thr``."""
        i = cls._first_over(points, thr)
        if i is None:
            return None
        a, b = np.log10(points[i - 1]["thdn_percent"]), np.log10(points[i]["thdn_percent"])
        t = (np.log10(thr) - a) / (b - a) if b != a else 1.0
        x0, x1 = points[i - 1]["input_dbfs"], points[i]["input_dbfs"]
        return float(x0 + np.clip(t, 0, 1) * (x1 - x0))

    def _clip_summary(self, points: list[dict], thr: float) -> dict:
        x = np.array([p["input_dbfs"] for p in points])
        out = np.array([p["output_dbfs"] for p in points])
        gain = np.array([p["gain_db"] for p in points])
        clip_in = self._crossing(points, thr)

        # 1 dB compression, relative to the gain at the cleanest step.
        thdn = np.array([p["thdn_percent"] for p in points])
        g_ref = gain[int(np.argmin(thdn))]
        comp = None
        for i in range(1, len(points)):
            if g_ref - gain[i] >= 1.0 and g_ref - gain[i - 1] < 1.0:
                t = (g_ref - gain[i - 1] - 1.0) / (gain[i - 1] - gain[i])
                comp = float(x[i - 1] + t * (x[i] - x[i - 1]))
                break

        if clip_in is None:
            limited_by = "input clipped" if points[-1]["input_clipped"] else "not reached"
            clip_out = None
        else:
            clip_out = float(np.interp(clip_in, x, out))
            i = int(np.searchsorted(x, clip_in))
            p = points[min(i, len(points) - 1)]
            if p["input_clipped"] or clip_out > -0.5:
                limited_by = "soundcard input"
            elif p.get("soundcard_thdn_percent", 0) >= thr:
                limited_by = "soundcard output"
            else:
                limited_by = "desk"
        return {
            "clip_input_dbfs": clip_in,
            "clip_output_dbfs": clip_out,
            "compression_1db_input_dbfs": comp,
            "max_clean_output_dbfs": float(max(
                (p["output_dbfs"] for p in points if p["thdn_percent"] < thr), default=np.nan)),
            "limited_by": limited_by,
            "max_tested_dbfs": float(x[-1]),
        }

    # -- everything --------------------------------------------------------

    def run(self, name: str, kinds=ALL_MEASUREMENTS,
            thd_freqs=(100.0, 1000.0, 10000.0), thd_levels=None,
            align_delay_samples: float | None = None, sweep_args: dict | None = None,
            progress=print) -> dict:
        """Run the selected measurements (any of ``ALL_MEASUREMENTS`` plus
        ``"sweep"``, which is opt-in because it drives the desk into clipping)."""
        res = {
            "name": name,
            "timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
            "settings": {
                "fs": self.fs, "level_dbfs": self.level,
                "cal_out_dbu": self.cal_out, "cal_in_dbu": self.cal_in,
                "loopback_reference": self.b.routing.has_reference,
            },
        }
        if "latency" in kinds:
            progress("Measuring latency...")
            res["latency"] = self.latency()
        if "gain" in kinds:
            progress("Measuring gain...")
            res["gain"] = self.gain()
        if "thd" in kinds:
            progress("Measuring harmonic distortion...")
            res["thd"] = self.thd(thd_freqs, thd_levels)
            if getattr(self, "_last_spectrum", None) is not None:
                res["thd_spectrum"] = self._spectrum_dict(self._last_spectrum)
        if "response" in kinds:
            progress("Measuring frequency & phase response...")
            res["response"] = self.response(delay_samples=align_delay_samples)
        if "correlation" in kinds:
            progress("Measuring correlation & coherence...")
            res["correlation"] = self.correlation()
        if "sweep" in kinds:
            progress("Level sweep...")
            res["level_sweep"] = self.level_sweep(progress=progress, **(sweep_args or {}))
        return res

    def run_all(self, name: str, **kwargs) -> dict:
        return self.run(name, ALL_MEASUREMENTS, **kwargs)

    @staticmethod
    def _spectrum_dict(h: an.HarmonicResult) -> dict:
        keep = (h.spectrum_freq >= 10) & (h.spectrum_freq <= 24000)
        # Max-pool down to ~4000 points so harmonic peaks survive.
        f, db = h.spectrum_freq[keep], h.spectrum_dbfs[keep]
        step = max(1, len(f) // 4000)
        m = len(f) // step * step
        return {
            "fundamental_hz": h.fundamental_hz,
            "freq": f[:m].reshape(-1, step).mean(axis=1).tolist(),
            "dbfs": db[:m].reshape(-1, step).max(axis=1).tolist(),
        }
