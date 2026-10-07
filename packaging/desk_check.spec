# PyInstaller spec for Desk Check.app.
# Build (on a Mac):  pyinstaller --noconfirm packaging/desk_check.spec
import os

from deskcheck import __version__

HERE = SPECPATH  # noqa: F821 - defined by PyInstaller
ICON = os.path.join(HERE, "build", "icon.png")

a = Analysis(  # noqa: F821
    [os.path.join(HERE, "desk_check_app.py")],
    # backend_tkagg is imported lazily; PIL._tkinter_finder is needed for
    # the plot toolbar icons (the app crashes on start without it).
    hiddenimports=["matplotlib.backends.backend_tkagg", "PIL._tkinter_finder"],
    excludes=["pytest", "IPython", "PyQt5", "PyQt6", "PySide2", "PySide6", "wx"],
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Desk Check",
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Desk Check")  # noqa: F821
app = BUNDLE(  # noqa: F821
    coll,
    name="Desk Check.app",
    icon=ICON if os.path.exists(ICON) else None,
    bundle_identifier="com.tonilourenco.deskcheck",
    version=__version__,
    info_plist={
        "CFBundleDisplayName": "Desk Check",
        "CFBundleName": "Desk Check",
        "CFBundleShortVersionString": __version__,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        # Required: without it macOS silently blocks recording from the
        # audio interface's inputs.
        "NSMicrophoneUsageDescription":
            "Desk Check records your audio interface's inputs to measure the mixing desk.",
    },
)
