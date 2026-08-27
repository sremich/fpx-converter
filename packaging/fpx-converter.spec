# PyInstaller build definition: one Windows .exe, nothing to install.
#
# The owner's requirement, in their words: "an entirely standalone executable,
# I don't want the user to have to worry about installing python dependencies
# etc." So: one file, no interpreter, no Qt install, no pip.
#
# Build it with `pyinstaller packaging/fpx-converter.spec` -- see
# packaging/build.md. ExifTool is NOT bundled and cannot be: it is a separate
# program with its own licence, installed with winget. See DECISIONS.md.
#
# The exe wears two hats. Launched normally it is the window; launched with
# `--run-cli` in front of its arguments it is `fpx_converter`, which is how
# the window runs a conversion (`fpx_gui.invoke`). One binary, both jobs.

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

REPO_ROOT = Path(SPECPATH).parent  # noqa: F821 -- PyInstaller injects SPECPATH

# Read, never typed. `VERSION` is the only source of truth for it, and the
# built file is named for it so two downloads a year apart are not two files
# called the same thing. `fpx_gui.invoke` re-executes `sys.executable`, so
# the name is free to change.
VERSION = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()

# pyexiv2 is a compiled extension (exiv2api.pyd) beside a data directory of
# its own. `collect_all` takes the binaries and the data with it; a
# hiddenimport alone produces an exe that imports and then cannot read a tag.
pyexiv2_datas, pyexiv2_binaries, pyexiv2_hidden = collect_all("pyexiv2")

hiddenimports = [
    # Pillow resolves its format plugins by name at runtime, so the analyser
    # cannot see them. TIFF and JPEG are what this project writes; the rest
    # come along because the decoder and the thumbnail extractor read
    # whatever a 2001 camera happened to embed.
    *collect_submodules("PIL"),
    # Both packages are entered through `__main__`, which the analyser follows
    # by import; the CLI's subcommand modules are reached through `cli` and are
    # named here so a refactor cannot quietly drop one from the bundle.
    *collect_submodules("fpx_converter"),
    *collect_submodules("fpx_gui"),
    *pyexiv2_hidden,
]

datas = [
    # The stylesheet, read through importlib.resources at startup.
    (str(REPO_ROOT / "fpx_gui" / "style.qss"), "fpx_gui"),
    # The single source of truth for the version. `fpx_converter.__init__`
    # reads it from beside the package, which inside the bundle is the bundle
    # root -- so `--version` tells the truth instead of saying "unknown".
    # Shipping the file is not a second copy of the version; hardcoding a
    # string here would be.
    (str(REPO_ROOT / "VERSION"), "."),
    *pyexiv2_datas,
]

# Qt is large and most of it is irrelevant to five widgets and a progress bar.
# Everything here has been removed and the result launched; anything that
# turns out to be needed belongs back in this list, not in a wider net.
excludes = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtGraphs",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtLocation",
    "PySide6.QtSerialPort",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSpatialAudio",
    "PySide6.QtStateMachine",
    "PySide6.QtTextToSpeech",
    "PySide6.QtUiTools",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    # Nothing in this project draws a Tk window or talks to a database.
    "tkinter",
    "sqlite3",
    # Test-only, and pytest would otherwise drag a great deal in behind it.
    "pytest",
    "pytest_qt",
]

analysis = Analysis(  # noqa: F821 -- PyInstaller injects these names
    [str(REPO_ROOT / "packaging" / "entry.py")],
    pathex=[str(REPO_ROOT)],
    binaries=[*pyexiv2_binaries],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name=f"fpx-converter-{VERSION}",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # One file, per the requirement. It costs a few seconds of unpacking on
    # every launch, including every CLI child the window starts, and buys a
    # deliverable that is a single thing to copy onto a machine.
    upx=False,
    runtime_tmpdir=None,
    # No console window. The CLI child is launched by the window with
    # CREATE_NO_WINDOW and its output read through a pipe, so nothing here
    # needs a terminal -- see `fpx_gui.runner`.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
