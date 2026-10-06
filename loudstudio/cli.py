"""Command-line interface.

Examples::

    loudstudio devices
    loudstudio run --name "Desk A ch1" --out 1 --in 1 --ref-out 2 --ref-in 2
    loudstudio compare results/desk-a-ch1.json results/desk-b-ch1.json
    loudstudio run --name demo --simulate --sim-eq 1000:6:1
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import report
from .audio import Routing, SimulatedBackend, SimulatedDesk, SoundcardBackend, list_devices
from .measure import Measurer


def _floats(s: str) -> list[float]:
    return [float(v) for v in s.split(",") if v.strip()]


def _eq(s: str) -> tuple[float, float, float]:
    f, g, q = (float(v) for v in s.split(":"))
    return f, g, q


def _device(s: str):
    return int(s) if s.isdigit() else s


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-").lower() or "measurement"


def _add_common(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("soundcard")
    g.add_argument("--device", type=_device, help="device index or name (see `loudstudio devices`)")
    g.add_argument("--fs", type=int, default=48000, help="sample rate (default 48000)")
    g.add_argument("--out", dest="dut_out", type=int, default=1, help="output channel to desk input (1-based)")
    g.add_argument("--in", dest="dut_in", type=int, default=1, help="input channel from desk output (1-based)")
    g.add_argument("--ref-out", type=int, help="output channel for loopback reference")
    g.add_argument("--ref-in", type=int, help="input channel for loopback reference")
    g.add_argument("--level", type=float, default=-18.0, help="stimulus level in dBFS (default -18)")
    g.add_argument("--cal-out", type=float, help="dBu at soundcard output for 0 dBFS")
    g.add_argument("--cal-in", type=float, help="dBu at soundcard input that reads 0 dBFS")

    s = p.add_argument_group("simulation (no hardware needed)")
    s.add_argument("--simulate", action="store_true", help="use a simulated desk instead of a soundcard")
    s.add_argument("--sim-gain", type=float, default=0.0, help="simulated desk gain dB")
    s.add_argument("--sim-eq", type=_eq, action="append", default=[], metavar="F:GAIN:Q",
                   help="simulated peaking EQ band, repeatable")
    s.add_argument("--sim-latency", type=float, default=1.0, help="simulated desk latency ms")
    s.add_argument("--sim-drive", type=float, default=0.3, help="simulated saturation (0 = linear)")
    s.add_argument("--sim-invert", action="store_true", help="simulate polarity inversion")
    s.add_argument("--sim-no-ref", action="store_true", help="simulate without loopback reference")


def _measurer(a) -> Measurer:
    if a.simulate:
        desk = SimulatedDesk(gain_db=a.sim_gain, eq=a.sim_eq, drive=a.sim_drive,
                             latency_ms=a.sim_latency, invert=a.sim_invert)
        backend = SimulatedBackend(a.fs, desk, use_reference=not a.sim_no_ref)
    else:
        if (a.ref_out is None) != (a.ref_in is None):
            sys.exit("--ref-out and --ref-in must be given together")
        routing = Routing(a.dut_out, a.dut_in, a.ref_out, a.ref_in)
        backend = SoundcardBackend(a.fs, routing, a.device)
    return Measurer(backend, a.level, a.cal_out, a.cal_in)


def _print_json(d) -> None:
    print(json.dumps(d, indent=1, default=float))


def cmd_devices(a):
    print(list_devices())


def _align_delay(a):
    """Delay (samples) from a previous result, for EQ phase comparisons."""
    if not getattr(a, "align_to", None):
        return None
    prev = report.load(a.align_to)
    if prev.get("settings", {}).get("fs", a.fs) != a.fs:
        sys.exit("--align-to file was measured at a different sample rate")
    return prev["response"]["delay_samples"]


def cmd_run(a):
    m = _measurer(a)
    res = m.run_all(a.name, thd_freqs=a.thd_freqs, thd_levels=a.thd_levels,
                    align_delay_samples=_align_delay(a))
    out = Path(a.output or f"results/{_slug(a.name)}.json")
    report.save(res, out)
    report.print_summary(res)
    png = report.plot([res], out.with_suffix(".png"))
    print(f"\nSaved {out} and {png}")


def cmd_latency(a):
    _print_json(_measurer(a).latency(a.repeats))


def cmd_gain(a):
    _print_json(_measurer(a).gain(a.freq))


def cmd_thd(a):
    rows = _measurer(a).thd(a.freqs, a.levels)
    for r in rows:
        r.pop("spectrum_freq", None)
    _print_json(rows)


def cmd_response(a):
    r = _measurer(a).response(delay_samples=_align_delay(a))
    print(f"Gain @ 1 kHz: {r['gain_1k_db']:+.2f} dB, phase {r['phase_1k_deg']:+.1f} deg, "
          f"delay {r['delay_ms']:.3f} ms")
    if a.output:
        res = {"name": a.name, "settings": {"fs": a.fs}, "response": r}
        report.save(res, a.output)
        print(f"Saved {a.output} and {report.plot([res], Path(a.output).with_suffix('.png'))}")


def cmd_correlation(a):
    r = _measurer(a).correlation()
    print(f"Correlation {r['correlation']:+.4f} ({r['polarity']}), "
          f"mean coherence 100 Hz-10 kHz {r['mean_coherence_100_10k']:.4f}")


def cmd_compare(a):
    results = [report.load(p) for p in a.files]
    report.print_comparison(results)
    png = report.plot(results, a.output, relative_to_first=a.relative)
    print(f"\nSaved {png}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="loudstudio", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("devices", help="list audio devices").set_defaults(func=cmd_devices)

    r = sub.add_parser("run", help="full measurement suite, saved to JSON + PNG")
    r.add_argument("--name", required=True, help="label, e.g. 'Desk A ch1 flat'")
    r.add_argument("-o", "--output", help="JSON path (default results/<name>.json)")
    r.add_argument("--thd-freqs", type=_floats, default=[100.0, 1000.0, 10000.0])
    r.add_argument("--thd-levels", type=_floats, help="comma-separated dBFS levels (default --level)")
    r.add_argument("--align-to", metavar="FLAT.json",
                   help="reuse the latency of a previous (flat/bypassed) result so EQ phase is exact")
    _add_common(r)
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("latency", help="round-trip latency")
    s.add_argument("--repeats", type=int, default=5)
    _add_common(s)
    s.set_defaults(func=cmd_latency)

    s = sub.add_parser("gain", help="gain at one frequency")
    s.add_argument("--freq", type=float, default=1000.0)
    _add_common(s)
    s.set_defaults(func=cmd_gain)

    s = sub.add_parser("thd", help="harmonic distortion (THD, THD+N)")
    s.add_argument("--freqs", type=_floats, default=[1000.0])
    s.add_argument("--levels", type=_floats, help="comma-separated dBFS levels")
    _add_common(s)
    s.set_defaults(func=cmd_thd)

    s = sub.add_parser("response", help="frequency & phase response (e.g. EQ curves)")
    s.add_argument("--name", default="response")
    s.add_argument("-o", "--output", help="save JSON + PNG")
    s.add_argument("--align-to", metavar="FLAT.json",
                   help="reuse the latency of a previous (flat/bypassed) result so EQ phase is exact")
    _add_common(s)
    s.set_defaults(func=cmd_response)

    s = sub.add_parser("correlation", help="input/output correlation and coherence")
    _add_common(s)
    s.set_defaults(func=cmd_correlation)

    c = sub.add_parser("compare", help="compare saved results")
    c.add_argument("files", nargs="+")
    c.add_argument("-o", "--output", default="results/compare.png")
    c.add_argument("--relative", action="store_true",
                   help="plot magnitude/phase as differences to the first file")
    c.set_defaults(func=cmd_compare)
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        a.func(a)
    except RuntimeError as exc:
        sys.exit(f"error: {exc}")


if __name__ == "__main__":
    main()
