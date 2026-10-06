"""Saving, printing, plotting and comparing measurement results."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def save(result: dict, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=1, default=float))
    return path


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text())


def _fmt(v, spec=".2f", unit=""):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "-"
    return f"{v:{spec}}{unit}"


def summary_rows(r: dict) -> list[tuple[str, str]]:
    rows = []
    lat, g = r.get("latency", {}), r.get("gain", {})
    if lat:
        rows.append(("Round-trip latency", _fmt(lat.get("total_roundtrip_ms"), ".3f", " ms")))
        if "desk_latency_ms" in lat:
            rows.append(("Desk latency (loopback removed)", _fmt(lat["desk_latency_ms"], ".3f", " ms")))
        rows.append(("Latency jitter", _fmt(lat.get("jitter_ms"), ".4f", " ms")))
    if g:
        rows.append((f"Gain @ {g['frequency_hz']:.0f} Hz", _fmt(g.get("gain_db"), "+.2f", " dB")))
        if "desk_output_dbu" in g:
            rows.append(("Desk output level", _fmt(g["desk_output_dbu"], "+.2f", " dBu")))
    for t in r.get("thd", []):
        label = f"THD / THD+N @ {t['fundamental_hz']:.0f} Hz, {t['stimulus_dbfs']:.0f} dBFS"
        rows.append((label, f"{_fmt(t['thd_percent'], '.4f', '%')} / {_fmt(t['thdn_percent'], '.4f', '%')}"))
    resp = r.get("response")
    if resp:
        f = np.array(resp["freq"])
        for fq in (50, 100, 1000, 10000, 20000):
            if f[0] <= fq <= f[-1]:
                m = np.interp(np.log10(fq), np.log10(f), resp["magnitude_db"])
                p = np.interp(np.log10(fq), np.log10(f), resp["phase_deg"])
                rows.append((f"Response @ {fq} Hz", f"{m:+.2f} dB, {p:+.1f} deg"))
    c = r.get("correlation")
    if c:
        rows.append(("Correlation (in vs out)", f"{c['correlation']:+.4f} ({c['polarity']})"))
        rows.append(("Mean coherence 100 Hz-10 kHz", _fmt(c.get("mean_coherence_100_10k"), ".4f")))
    sw = r.get("level_sweep")
    if sw:
        thr = f"THD+N {sw['threshold_percent']:g}%"
        if sw["clip_input_dbfs"] is None:
            rows.append((f"Clip point ({thr})",
                         f"not reached up to {sw['max_tested_dbfs']:+.1f} dBFS in"
                         + (" (input clipped)" if sw["limited_by"] == "input clipped" else "")))
        else:
            dbu_in = f" ({sw['clip_input_dbu']:+.1f} dBu)" if "clip_input_dbu" in sw else ""
            dbu_out = f" ({sw['clip_output_dbu']:+.1f} dBu)" if "clip_output_dbu" in sw else ""
            rows.append((f"Clip point in ({thr})", f"{sw['clip_input_dbfs']:+.1f} dBFS{dbu_in}"))
            rows.append((f"Clip point out ({thr})", f"{sw['clip_output_dbfs']:+.1f} dBFS{dbu_out}"))
            hint = {"soundcard input": " - pad the desk output or lower the interface input gain",
                    "soundcard output": " - the interface output distorts first"}
            rows.append(("Clip limited by", sw["limited_by"] + hint.get(sw["limited_by"], "")))
        rows.append(("1 dB compression (input)", _fmt(sw.get("compression_1db_input_dbfs"), "+.1f", " dBFS")))
    return rows


def print_summary(r: dict) -> None:
    rows = summary_rows(r)
    width = max(len(k) for k, _ in rows) if rows else 0
    print(f"\n== {r.get('name', 'measurement')} ==")
    for k, v in rows:
        print(f"  {k:<{width}}  {v}")


def print_comparison(results: list[dict]) -> None:
    tables = [dict(summary_rows(r)) for r in results]
    keys = []
    for t in tables:
        keys += [k for k in t if k not in keys]
    names = [r.get("name", f"#{i}") for i, r in enumerate(results)]
    kw = max(len(k) for k in keys)
    cw = max(18, *(len(n) for n in names))
    print(f"{'':<{kw}}  " + "  ".join(f"{n:>{cw}}" for n in names))
    for k in keys:
        print(f"{k:<{kw}}  " + "  ".join(f"{t.get(k, '-'):>{cw}}" for t in tables))


# --------------------------------------------------------------------------
# Plots
# --------------------------------------------------------------------------

def _log_axis(ax, label):
    ax.set_xscale("log")
    ax.set_xlim(20, 20000)
    ax.set_xticks([20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000])
    ax.set_xticklabels(["20", "50", "100", "200", "500", "1k", "2k", "5k", "10k", "20k"])
    ax.set_ylabel(label)
    ax.grid(True, which="both", alpha=0.3)


def plot(results: list[dict], path: str | Path, relative_to_first: bool = False) -> Path:
    """Save the result plot (see :func:`draw`) as an image."""
    from matplotlib.figure import Figure  # no pyplot: safe alongside the GUI

    fig = Figure(figsize=(14, 16))
    draw(fig, results, relative_to_first, summary=True)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110)
    return path


def draw(fig, results: list[dict], relative_to_first: bool = False,
         summary: bool = True) -> None:
    """Draw magnitude, phase, group delay, coherence, THD spectrum and (if
    measured) the level sweep on ``fig``.

    With several results the curves are overlaid; ``relative_to_first``
    plots magnitude/phase as differences to the first result instead.
    ``summary`` adds a text panel with the key numbers.
    """
    fig.clear()
    if not results:
        return
    has_sweep = any("level_sweep" in r for r in results)
    gs = fig.add_gridspec(4 if summary else 3, 2,
                          height_ratios=[1, 1, 1, 1.1] if summary else None)
    ax_mag, ax_ph = fig.add_subplot(gs[0, 0]), fig.add_subplot(gs[0, 1])
    ax_gd, ax_coh = fig.add_subplot(gs[1, 0]), fig.add_subplot(gs[1, 1])
    # The spectrum shares the bottom row with the level sweep if there is one.
    ax_thd = fig.add_subplot(gs[2, 0] if has_sweep else gs[2, :])
    ax_sw = fig.add_subplot(gs[2, 1]) if has_sweep else None
    base = results[0].get("response") if relative_to_first else None

    for r in results:
        name = r.get("name", "?")
        resp = r.get("response")
        if resp:
            f = np.array(resp["freq"])
            mag, ph = np.array(resp["magnitude_db"]), np.array(resp["phase_deg"])
            if base is not None:
                mag = mag - np.interp(f, base["freq"], base["magnitude_db"])
                ph = ph - np.interp(f, base["freq"], base["phase_deg"])
            ax_mag.semilogx(f, mag, label=name)
            ax_ph.semilogx(f, ph, label=name)
            ax_gd.semilogx(f, resp["group_delay_ms"], label=name)
        c = r.get("correlation")
        if c:
            ax_coh.semilogx(c["freq"], c["coherence"],
                            label=f"{name} (r={c['correlation']:+.3f})")
        s = r.get("thd_spectrum")
        if s:
            ax_thd.semilogx(s["freq"], s["dbfs"], lw=0.7, label=name)
        sw = r.get("level_sweep")
        if sw:
            x = [p["input_dbfs"] for p in sw["points"]]
            y = [p["thdn_percent"] for p in sw["points"]]
            (line,) = ax_sw.semilogy(x, y, ".-", label=name)
            if sw["clip_input_dbfs"] is not None:
                ax_sw.axvline(sw["clip_input_dbfs"], color=line.get_color(), ls=":", lw=1)
                ax_sw.plot([sw["clip_input_dbfs"]], [sw["threshold_percent"]], "o",
                           color=line.get_color(), ms=8, mfc="none")

    suffix = " (relative to first)" if base is not None else ""
    _log_axis(ax_mag, "Magnitude (dB)" + suffix)
    ax_mag.set_title("Frequency response")
    _log_axis(ax_ph, "Phase (deg)" + suffix)
    ax_ph.set_title("Phase (latency removed)")
    _log_axis(ax_gd, "Group delay (ms)")
    ax_gd.set_title("Excess group delay")
    _log_axis(ax_coh, "Coherence")
    ax_coh.set_ylim(0, 1.05)
    ax_coh.set_title("Coherence (input vs output)")
    _log_axis(ax_thd, "Level (dBFS)")
    ax_thd.set_ylim(-160, 10)
    ax_thd.set_title("Distortion spectrum (tone nearest 1 kHz)")
    ax_thd.set_xlabel("Frequency (Hz)")
    if ax_sw is not None:
        thr = next(r["level_sweep"]["threshold_percent"] for r in results if "level_sweep" in r)
        ax_sw.axhline(thr, color="0.4", ls="--", lw=1)
        ax_sw.set_title(f"Level sweep - clip point at THD+N {thr:g}% (circles)")
        ax_sw.set_xlabel("Input level (dBFS)")
        ax_sw.set_ylabel("THD+N (%)")
        ax_sw.grid(True, which="both", alpha=0.3)
    for ax in (ax_mag, ax_ph, ax_gd, ax_coh, ax_thd, ax_sw):
        if ax is not None and ax.get_legend_handles_labels()[0]:
            ax.legend(fontsize=8)

    if summary:
        # Results alternate between the two text columns.
        for col in range(2):
            ax_txt = fig.add_subplot(gs[3, col])
            ax_txt.axis("off")
            lines = []
            for r in results[col::2]:
                lines.append(r.get("name", "?"))
                lines += [f"  {k}: {v}" for k, v in summary_rows(r)]
                lines.append("")
            ax_txt.text(0, 1, "\n".join(lines), va="top", family="monospace", fontsize=7)
    fig.tight_layout()
