"""Entry point for the bundled Desk Check.app.

``--selftest`` checks that everything the app needs made it into the
bundle (PortAudio, scipy, matplotlib, Tk) and exits; the build uses it
to verify each app before publishing it.
"""

import sys


def selftest() -> int:
    import tempfile
    import tkinter as tk
    from pathlib import Path

    import sounddevice as sd  # loads the bundled PortAudio library

    from deskcheck import report
    from deskcheck.audio import SimulatedBackend
    from deskcheck.gui import App
    from deskcheck.measure import Measurer

    print("PortAudio:", sd.get_portaudio_version()[1])
    print("Audio devices:", len(sd.query_devices()))
    res = Measurer(SimulatedBackend()).run(
        "selftest", ("latency", "gain", "response"), progress=lambda m: None)
    assert abs(res["gain"]["gain_db"]) < 0.1, res["gain"]
    with tempfile.TemporaryDirectory() as d:
        png = report.plot([res], Path(d) / "selftest.png")
        assert png.stat().st_size > 10000
    root = tk.Tk()
    App(root)
    root.update()
    print("Window title:", root.title())
    root.destroy()
    print("Desk Check self-test OK")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    from deskcheck.gui import main

    main()
