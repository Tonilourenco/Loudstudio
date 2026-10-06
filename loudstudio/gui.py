"""Simple Tkinter GUI: set up routing, run measurements, compare results.

Start with ``loudstudio-gui`` or ``loudstudio gui``.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from . import report
from .audio import Routing, SimulatedBackend, SimulatedDesk, SoundcardBackend, _import_sounddevice
from .measure import ALL_MEASUREMENTS, Measurer

SAMPLE_RATES = ("44100", "48000", "88200", "96000")
AUTO_ALIGN = "(auto - correlation peak)"


def _device_choices() -> tuple[list[str], str | None]:
    """Device labels like '3: Fireface UCX (in 18 / out 18)', and an error text."""
    try:
        sd = _import_sounddevice()
        labels = [f"{i}: {d['name']} (in {d['max_input_channels']} / out {d['max_output_channels']})"
                  for i, d in enumerate(sd.query_devices())]
        return labels, None
    except Exception as exc:  # noqa: BLE001 - any PortAudio problem
        return [], str(exc)


def _opt_float(s: str) -> float | None:
    s = s.strip()
    return float(s) if s else None


def _floats(s: str) -> list[float]:
    return [float(v) for v in s.replace(";", ",").split(",") if v.strip()]


class App(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master, padding=6)
        self.master = master
        self.results: list[dict] = []
        self.paths: dict[int, Path] = {}      # id(result) -> saved path
        self.queue: queue.Queue = queue.Queue()
        self.busy = False

        master.title("Loudstudio - desk analyser")
        master.geometry("1440x940")
        self.pack(fill="both", expand=True)

        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)
        left = ttk.Frame(paned, padding=(0, 0, 6, 0))
        right = ttk.Frame(paned)
        paned.add(left, weight=0)
        paned.add(right, weight=1)

        self._build_settings(left)
        self._build_plot_and_results(right)
        # Keep the settings column compact so the plots get the space.
        self.after(50, lambda: paned.sashpos(0, 400))
        self.after(100, self._poll)

    # ------------------------------------------------------------------ UI

    def _row(self, parent, r, label, widget, stretch=False):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", pady=1, padx=(0, 6))
        widget.grid(row=r, column=1, sticky="ew" if stretch else "w", pady=1)
        return widget

    def _build_settings(self, parent):
        parent.columnconfigure(0, weight=1)

        # -- audio interface ------------------------------------------------
        box = ttk.LabelFrame(parent, text="Soundcard", padding=6)
        box.grid(row=0, column=0, sticky="ew")
        box.columnconfigure(1, weight=1)
        devices, err = _device_choices()
        self.device = tk.StringVar(value=devices[0] if devices else "")
        dev = ttk.Combobox(box, textvariable=self.device, values=devices, width=30, state="readonly")
        self._row(box, 0, "Device", dev, stretch=True)
        self.fs = tk.StringVar(value="48000")
        self._row(box, 1, "Sample rate", ttk.Combobox(box, textvariable=self.fs, values=SAMPLE_RATES, width=8))

        self.dut_out, self.dut_in = tk.IntVar(value=1), tk.IntVar(value=1)
        self.ref_out, self.ref_in = tk.IntVar(value=2), tk.IntVar(value=2)
        self._row(box, 2, "Out -> desk input", ttk.Spinbox(box, from_=1, to=128, textvariable=self.dut_out, width=6))
        self._row(box, 3, "In <- desk output", ttk.Spinbox(box, from_=1, to=128, textvariable=self.dut_in, width=6))
        self.use_ref = tk.BooleanVar(value=True)
        ttk.Checkbutton(box, text="Loopback reference (recommended)", variable=self.use_ref,
                        command=self._toggle_ref).grid(row=4, column=0, columnspan=2, sticky="w")
        self.ref_out_w = self._row(box, 5, "  Ref out", ttk.Spinbox(box, from_=1, to=128, textvariable=self.ref_out, width=6))
        self.ref_in_w = self._row(box, 6, "  Ref in", ttk.Spinbox(box, from_=1, to=128, textvariable=self.ref_in, width=6))

        self.level = tk.StringVar(value="-18")
        self.cal_out, self.cal_in = tk.StringVar(), tk.StringVar()
        self._row(box, 7, "Level (dBFS)", ttk.Entry(box, textvariable=self.level, width=8))
        self._row(box, 8, "Cal out (dBu @ 0 dBFS)", ttk.Entry(box, textvariable=self.cal_out, width=8))
        self._row(box, 9, "Cal in (dBu @ 0 dBFS)", ttk.Entry(box, textvariable=self.cal_in, width=8))

        # -- simulation ----------------------------------------------------
        sim = ttk.LabelFrame(parent, text="Simulation (no hardware)", padding=6)
        sim.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        sim.columnconfigure(1, weight=1)
        self.simulate = tk.BooleanVar(value=err is not None)
        ttk.Checkbutton(sim, text="Use simulated desk", variable=self.simulate).grid(
            row=0, column=0, columnspan=2, sticky="w")
        if err:
            ttk.Label(sim, text="No soundcard found (is PortAudio installed?)",
                      foreground="#b00").grid(row=1, column=0, columnspan=2, sticky="w")
        self.sim_gain, self.sim_lat = tk.StringVar(value="0"), tk.StringVar(value="1.0")
        self.sim_eq, self.sim_drive = tk.StringVar(value=""), tk.StringVar(value="0.3")
        self.sim_invert = tk.BooleanVar(value=False)
        self.sim_clip = tk.StringVar(value="")
        self._row(sim, 2, "Gain (dB)", ttk.Entry(sim, textvariable=self.sim_gain, width=8))
        self._row(sim, 3, "EQ  f:gain:Q, ...", ttk.Entry(sim, textvariable=self.sim_eq, width=16))
        self._row(sim, 4, "Latency (ms)", ttk.Entry(sim, textvariable=self.sim_lat, width=8))
        self._row(sim, 5, "Saturation", ttk.Entry(sim, textvariable=self.sim_drive, width=8))
        self._row(sim, 6, "Output clip (dBFS)", ttk.Entry(sim, textvariable=self.sim_clip, width=8))
        ttk.Checkbutton(sim, text="Invert polarity", variable=self.sim_invert).grid(
            row=7, column=0, columnspan=2, sticky="w")

        # -- measurement ---------------------------------------------------
        m = ttk.LabelFrame(parent, text="Measurement", padding=6)
        m.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        m.columnconfigure(1, weight=1)
        self.name = tk.StringVar(value="Desk A flat")
        self._row(m, 0, "Name", ttk.Entry(m, textvariable=self.name, width=24), stretch=True)
        self.thd_freqs, self.thd_levels = tk.StringVar(value="100, 1000, 10000"), tk.StringVar()
        self._row(m, 1, "THD freqs (Hz)", ttk.Entry(m, textvariable=self.thd_freqs, width=16))
        self._row(m, 2, "THD levels (dBFS)", ttk.Entry(m, textvariable=self.thd_levels, width=16))
        self.align = tk.StringVar(value=AUTO_ALIGN)
        self.align_box = self._row(m, 3, "Align phase to",
                                   ttk.Combobox(m, textvariable=self.align, values=[AUTO_ALIGN],
                                                state="readonly", width=22), stretch=True)
        ttk.Label(m, text="Pick a flat (EQ bypassed) result of the same\ndesk to measure EQ phase shift exactly.",
                  foreground="#666").grid(row=4, column=0, columnspan=2, sticky="w")

        sw = ttk.Frame(m)
        sw.grid(row=5, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.sw_start, self.sw_stop = tk.StringVar(value="-40"), tk.StringVar(value="0")
        self.sw_step, self.sw_thr = tk.StringVar(value="2"), tk.StringVar(value="1")
        for col, (label, var) in enumerate((("Sweep from", self.sw_start), ("to", self.sw_stop),
                                            ("step", self.sw_step), ("clip at THD+N %", self.sw_thr))):
            ttk.Label(sw, text=label).grid(row=col // 2, column=(col % 2) * 2, sticky="w", padx=(0, 4))
            ttk.Entry(sw, textvariable=var, width=6).grid(row=col // 2, column=(col % 2) * 2 + 1,
                                                          sticky="w", padx=(0, 8))

        btns = ttk.Frame(m)
        btns.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.run_buttons = []
        b = ttk.Button(btns, text="Run all measurements", command=lambda: self._start(ALL_MEASUREMENTS))
        b.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 4))
        self.run_buttons.append(b)
        for i, kind in enumerate(ALL_MEASUREMENTS):
            label = {"thd": "THD"}.get(kind, kind.capitalize())
            b = ttk.Button(btns, text=label, command=lambda k=kind: self._start((k,)))
            b.grid(row=1 + i // 3, column=i % 3, sticky="ew", padx=1, pady=1)
            self.run_buttons.append(b)
        b = ttk.Button(btns, text="Clip sweep", command=lambda: self._start(("sweep",)))
        b.grid(row=2, column=2, sticky="ew", padx=1, pady=1)
        self.run_buttons.append(b)
        for c in range(3):
            btns.columnconfigure(c, weight=1)

        self.status = tk.StringVar(value="Ready")
        ttk.Label(parent, textvariable=self.status, wraplength=320).grid(row=3, column=0, sticky="w", pady=(8, 2))
        self.progress = ttk.Progressbar(parent, mode="indeterminate")
        self.progress.grid(row=4, column=0, sticky="ew")

    def _build_plot_and_results(self, parent):
        vpaned = ttk.PanedWindow(parent, orient="vertical")
        vpaned.pack(fill="both", expand=True)

        plot_frame = ttk.Frame(vpaned)
        self.fig = Figure(figsize=(10, 7), dpi=90)
        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
        NavigationToolbar2Tk(self.canvas, plot_frame).update()
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        vpaned.add(plot_frame, weight=3)

        bottom = ttk.Frame(vpaned, padding=(0, 4, 0, 0))
        vpaned.add(bottom, weight=1)
        bottom.columnconfigure(1, weight=1)
        bottom.rowconfigure(0, weight=1)

        # Result list (select several to compare)
        lf = ttk.LabelFrame(bottom, text="Results (select to compare)", padding=4)
        lf.grid(row=0, column=0, sticky="nsew")
        self.relative = tk.BooleanVar(value=False)
        ttk.Checkbutton(lf, text="Plot relative to first selected", variable=self.relative,
                        command=self._refresh_view).pack(anchor="w")
        self.listbox = tk.Listbox(lf, selectmode="extended", width=26, height=6, exportselection=False)
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", lambda e: self._refresh_view())
        bb = ttk.Frame(lf)
        bb.pack(fill="x", pady=(4, 0))
        for text, cmd in (("Load...", self._load), ("Save...", self._save),
                          ("Remove", self._remove), ("Export PNG...", self._export)):
            ttk.Button(bb, text=text, command=cmd).pack(side="left", padx=1)

        # Comparison table
        tf = ttk.LabelFrame(bottom, text="Summary", padding=4)
        tf.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.table = ttk.Treeview(tf, show="headings")
        ys = ttk.Scrollbar(tf, orient="vertical", command=self.table.yview)
        xs = ttk.Scrollbar(tf, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        tf.rowconfigure(0, weight=1)
        tf.columnconfigure(0, weight=1)

    def _toggle_ref(self):
        state = "normal" if self.use_ref.get() else "disabled"
        self.ref_out_w.configure(state=state)
        self.ref_in_w.configure(state=state)

    # ------------------------------------------------------------ measuring

    def _measurer(self) -> Measurer:
        fs = int(self.fs.get())
        if self.simulate.get():
            eq = [tuple(float(v) for v in band.split(":"))
                  for band in self.sim_eq.get().replace(";", ",").split(",") if band.strip()]
            desk = SimulatedDesk(gain_db=float(self.sim_gain.get()), eq=eq,
                                 drive=float(self.sim_drive.get()),
                                 latency_ms=float(self.sim_lat.get()),
                                 invert=self.sim_invert.get(),
                                 clip_dbfs=_opt_float(self.sim_clip.get()))
            backend = SimulatedBackend(fs, desk, use_reference=self.use_ref.get())
        else:
            if not self.device.get():
                raise ValueError("No audio device selected")
            dev = int(self.device.get().split(":", 1)[0])
            routing = Routing(self.dut_out.get(), self.dut_in.get(),
                              self.ref_out.get() if self.use_ref.get() else None,
                              self.ref_in.get() if self.use_ref.get() else None)
            backend = SoundcardBackend(fs, routing, dev)
        return Measurer(backend, float(self.level.get()),
                        _opt_float(self.cal_out.get()), _opt_float(self.cal_in.get()))

    def _align_delay(self) -> float | None:
        name = self.align.get()
        if name == AUTO_ALIGN:
            return None
        for r in self.results:
            if r.get("name") == name and "response" in r:
                if r.get("settings", {}).get("fs") != int(self.fs.get()):
                    raise ValueError(f"'{name}' was measured at a different sample rate")
                return r["response"]["delay_samples"]
        raise ValueError(f"'{name}' has no response measurement to align to")

    def _start(self, kinds):
        if self.busy:
            return
        try:
            m = self._measurer()
            kwargs = {
                "kinds": kinds,
                "sweep_args": {
                    "start_dbfs": float(self.sw_start.get()), "stop_dbfs": float(self.sw_stop.get()),
                    "step_db": float(self.sw_step.get()), "threshold_percent": float(self.sw_thr.get()),
                },
                "thd_freqs": _floats(self.thd_freqs.get()) or [1000.0],
                "thd_levels": _floats(self.thd_levels.get()) or None,
                "align_delay_samples": self._align_delay() if "response" in kinds else None,
            }
        except (ValueError, RuntimeError) as exc:
            messagebox.showerror("Loudstudio", str(exc))
            return
        if "sweep" in kinds and not self.simulate.get() and not messagebox.askokcancel(
                "Clip sweep",
                f"The sweep plays a 1 kHz tone up to {self.sw_stop.get()} dBFS and drives the desk "
                "into clipping.\n\nMute or disconnect any speakers and headphones on the desk first."):
            return
        name = self.name.get().strip() or "measurement"
        self._set_busy(True)

        def work():
            try:
                res = m.run(name, progress=lambda msg: self.queue.put(("status", msg)), **kwargs)
                self.queue.put(("done", res))
            except Exception as exc:  # noqa: BLE001 - report anything to the user
                self.queue.put(("error", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "status":
                    self.status.set(payload)
                elif kind == "error":
                    self._set_busy(False)
                    self.status.set("Error: " + payload)
                    messagebox.showerror("Loudstudio", payload)
                elif kind == "done":
                    self._set_busy(False)
                    self._add_result(payload, merge=True)
                    self.status.set(f"Finished '{payload['name']}'")
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _set_busy(self, busy: bool):
        self.busy = busy
        for b in self.run_buttons:
            b.configure(state="disabled" if busy else "normal")
        if busy:
            self.progress.configure(mode="indeterminate")
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate", value=0)

    # -------------------------------------------------------------- results

    def _add_result(self, res: dict, merge: bool = False):
        """Add a result; with ``merge`` a result of the same name is updated
        (so single measurements build up one entry)."""
        for i, r in enumerate(self.results):
            if merge and r.get("name") == res.get("name"):
                r.update(res)
                idx = i
                break
        else:
            self.results.append(res)
            idx = len(self.results) - 1
        self._refresh_list(select=idx)

    def _refresh_list(self, select: int | None = None):
        self.listbox.delete(0, "end")
        for r in self.results:
            self.listbox.insert("end", r.get("name", "?"))
        if select is not None:
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(select)
            self.listbox.see(select)
        names = [r.get("name", "?") for r in self.results if "response" in r]
        self.align_box.configure(values=[AUTO_ALIGN] + names)
        if self.align.get() not in names:
            self.align.set(AUTO_ALIGN)
        self._refresh_view()

    def _selected(self) -> list[dict]:
        idx = self.listbox.curselection()
        return [self.results[i] for i in idx] if idx else list(self.results)

    def _refresh_view(self):
        sel = self._selected()
        report.draw(self.fig, sel, self.relative.get(), summary=False)
        self.canvas.draw_idle()

        self.table.delete(*self.table.get_children())
        tables = [dict(report.summary_rows(r)) for r in sel]
        keys: list[str] = []
        for t in tables:
            keys += [k for k in t if k not in keys]
        cols = ["metric"] + [f"r{i}" for i in range(len(sel))]
        self.table.configure(columns=cols)
        self.table.heading("metric", text="")
        self.table.column("metric", width=280, anchor="w", stretch=False)
        for i, r in enumerate(sel):
            self.table.heading(f"r{i}", text=r.get("name", "?"))
            self.table.column(f"r{i}", width=150, anchor="e", stretch=False)
        for k in keys:
            self.table.insert("", "end", values=[k] + [t.get(k, "-") for t in tables])

    def _load(self):
        for p in filedialog.askopenfilenames(title="Load results", filetypes=[("JSON", "*.json")]):
            try:
                res = report.load(p)
            except (OSError, ValueError) as exc:
                messagebox.showerror("Loudstudio", f"{p}: {exc}")
                continue
            self.paths[id(res)] = Path(p)
            self._add_result(res)

    def _save(self):
        for r in self._selected():
            initial = self.paths.get(id(r))
            p = filedialog.asksaveasfilename(
                title=f"Save '{r.get('name')}'", defaultextension=".json",
                initialfile=initial.name if initial else f"{r.get('name', 'result')}.json",
                filetypes=[("JSON", "*.json")])
            if p:
                report.save(r, p)
                self.paths[id(r)] = Path(p)
                self.status.set(f"Saved {p}")

    def _remove(self):
        for i in sorted(self.listbox.curselection(), reverse=True):
            self.paths.pop(id(self.results[i]), None)
            del self.results[i]
        self._refresh_list()

    def _export(self):
        sel = self._selected()
        if not sel:
            return
        p = filedialog.asksaveasfilename(title="Export plot", defaultextension=".png",
                                         filetypes=[("PNG", "*.png"), ("PDF", "*.pdf")])
        if p:
            report.plot(sel, p, self.relative.get())
            self.status.set(f"Exported {p}")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
