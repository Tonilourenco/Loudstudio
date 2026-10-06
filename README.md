# Loudstudio

A small analyser for measuring and comparing mixing desks (analogue or
digital) with an ordinary multi-channel soundcard.

It measures:

| Measurement | Stimulus | What you get |
|---|---|---|
| **Gain** | 1 kHz sine | gain in dB (and dBu levels if calibrated) |
| **Harmonic distortion** | sines at chosen frequencies and levels | THD, THD+N, individual harmonics H2…H9 in dBc, spectrum |
| **Frequency & phase response** | exponential sine sweep | magnitude, phase (latency removed), excess group delay, for EQ curves and EQ phase shift |
| **Correlation & coherence** | pink noise | time-aligned correlation coefficient (+1 identical, −1 polarity inverted), polarity, coherence vs frequency |
| **Round-trip latency** | sweep + GCC-PHAT cross-correlation | total and desk-only latency to sub-sample accuracy, jitter across runs |

Every run is saved as JSON plus a PNG plot, and any number of runs can be
overlaid in a comparison table and plot.

## Install

```bash
# PortAudio is needed for soundcard access
#   macOS:  brew install portaudio
#   Debian/Ubuntu: sudo apt install libportaudio2
#   Windows: included with the sounddevice wheel
pip install -e .
```

You can try everything without hardware by adding `--simulate`:

```bash
loudstudio run --name "demo" --simulate --sim-eq 1000:6:1.4 --sim-latency 2.5
```

## GUI

```bash
loudstudio gui        # or: loudstudio-gui
```

The settings column on the left holds the soundcard device, channel routing,
the loopback reference, the stimulus level, calibration and the measurement
name. Click **Run all measurements**, or run a single measurement with the
Latency, Gain, THD, Response or Correlation buttons. Single measurements with
the same name are merged into one result.

Each result is added to the **Results** list. Select several (Ctrl/Shift-click)
to overlay them and see them side by side in the **Summary** table. Tick *Plot
relative to first selected* to see the differences. **Save**, **Load** and
**Export PNG** use the same JSON files as the command line.

To measure EQ phase shift, first run the desk with EQ bypassed. Then choose
that result under *Align phase to* before measuring with the EQ on.

Tick *Use simulated desk* to try everything without hardware. It is on
automatically when no soundcard is available. The GUI uses Tkinter, which
ships with Python on Windows and macOS. On Linux, install `python3-tk`.

## Wiring

```
 soundcard OUT 1 ──────► desk channel input
 desk output (direct out / bus / main) ──────► soundcard IN 1

 soundcard OUT 2 ──── loopback cable ────► soundcard IN 2    (recommended)
```

The **loopback reference** (OUT 2 → IN 2) records the same stimulus through
the soundcard only. Every measurement is then made *relative* to it, so the
soundcard's own latency, converter levels and frequency response cancel out,
and you measure only the desk. Tell Loudstudio about it with
`--ref-out 2 --ref-in 2`.

With digital desks you can also connect over MADI/Dante/USB. Pick the
matching device with `--device`, and the channels with `--out` and `--in`.

Find device names and channel counts with:

```bash
loudstudio devices
```

## Typical workflow

```bash
COMMON="--device 'Fireface' --out 1 --in 1 --ref-out 2 --ref-in 2 --level -18"

# 1. Desk A, channel flat (EQ bypassed, fader & trim at a known setting)
loudstudio run --name "Desk A flat" $COMMON

# 2. Desk A with an EQ setting, phase measured against the flat latency
loudstudio run --name "Desk A EQ 3k -6dB Q2" $COMMON --align-to results/desk-a-flat.json

# 3. Same for desk B ...
loudstudio run --name "Desk B flat" $COMMON
loudstudio run --name "Desk B EQ 3k -6dB Q2" $COMMON --align-to results/desk-b-flat.json

# 4. Compare (table in the terminal + results/compare.png)
loudstudio compare results/desk-a-flat.json results/desk-b-flat.json
loudstudio compare results/desk-a-eq-3k-6db-q2.json results/desk-b-eq-3k-6db-q2.json -o results/eq.png

# Differences relative to the first file (e.g. how EQ changed the response)
loudstudio compare results/desk-a-flat.json results/desk-a-eq-3k-6db-q2.json --relative -o results/a-eq-delta.png
```

Single measurements are also available: `latency`, `gain`, `thd`,
`response` and `correlation`. Run `loudstudio <command> -h` for the options
of each, for example:

```bash
loudstudio latency $COMMON --repeats 10
loudstudio thd $COMMON --freqs 100,1000,10000 --levels=-30,-18,-6,0
```

Note: negative lists need `=`, as in `--levels=-30,-18`.

## Levels and calibration

* `--level` is the stimulus level in dBFS (AES17: a full-scale sine is
  0 dBFS). −18 dBFS is a safe default. Raise it, or use `thd --levels=...`,
  to find where each desk starts to distort.
* With a loopback reference, **gain** is measured as desk return minus
  loopback, so no calibration is needed. This assumes IN 1 and IN 2 have the
  same input trim on the soundcard.
* Without a loopback, give the converter calibration so dBFS can be turned
  into dBu:
  * `--cal-out`: dBu at the soundcard output for a 0 dBFS sine (e.g. `+18`).
  * `--cal-in`: dBu at the soundcard input that reads 0 dBFS (e.g. `+18`).

  With these set, results also include the desk input and output levels in
  dBu.
* Avoid clipping. Results are flagged when the return channel hits full
  scale.

## How the measurements work

* **Latency**: GCC-PHAT (phase-transform cross-correlation) between the
  stimulus and the recording, polished to ~0.001-sample precision. It is
  robust to EQ and to polarity inversion. With a loopback, the soundcard's
  own round trip is subtracted to give desk latency.
* **Distortion**: a 4-term Blackman-Harris windowed FFT of a steady-state,
  bin-centred sine. THD is the sum of H2…H9. THD+N is everything from
  20 Hz to 20 kHz except the fundamental. Harmonics above 20 kHz are not
  counted, so THD for tones above 10 kHz reads "–".
* **Frequency/phase response**: dual-channel FFT transfer function
  (desk ÷ reference) of an exponential sweep, 1/24-octave complex smoothing.
  The bulk latency is removed before phase is shown, so the phase plot shows
  the EQ/filter phase shift only. By default the delay comes from the
  correlation peak. Use `--align-to FLAT.json` for exact EQ phase
  comparisons, so that the latency of the bypassed desk is used.
* **Correlation**: Pearson correlation of the time-aligned input and output
  (like a phase-correlation meter). Values below 1 come from EQ, noise,
  distortion or non-linear processing. **Coherence** shows that per
  frequency: 1 means the output is fully explained by the input.

## Development

```bash
pip install -e '.[test]'
pytest
```

The analysis is tested against synthetic signals with known delay,
harmonics and EQ (`tests/`). The `--simulate` back-end (`SimulatedDesk`)
models gain, peaking EQ, saturation, latency, noise and polarity.
