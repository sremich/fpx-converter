# PyInstaller build definition: one Windows .exe, nothing to install.
#
# The owner's requirement, in their words: "an entirely standalone executable,
# I don't want the user to have to worry about installing python dependencies
# etc." So: one file, no interpreter, no Qt install, no pip.
#
# Build it with `pyinstaller packaging/fpx-converter.spec` -- see
# packaging/build.md. ExifTool is NOT bundled and cannot be: it is a separate
# program with its own licence, installed with winget. See THIRD-PARTY-NOTICES.md.
#
# The exe wears two hats. Launched normally it is the window; launched with
# `--run-cli` in front of its arguments it is `fpx_converter`, which is how
# the window runs a conversion (`fpx_gui.invoke`). One binary, both jobs.
#
# **The published exe is Apache-2.0 and every byte in it has to allow that.**
# pyexiv2 (GPL-3.0, and `exiv2.dll` with it) used to be collected whole and
# is now excluded; PySide6-Addons, some of whose modules are GPLv3-only, is
# not installed at all. Neither exclusion is trusted -- `packaging/licence_guard.py`
# fails the build if either turns up anyway, because a denylist fails open and
# a mislicensed executable does not look any different from a correct one.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

REPO_ROOT = Path(SPECPATH).parent  # noqa: F821 -- PyInstaller injects SPECPATH

# The guard lives beside this file rather than inside it: a `.spec` is executed
# with injected globals and cannot be imported by a test, and this is the one
# part of the build that must itself be tested.
sys.path.insert(0, str(REPO_ROOT / "packaging"))
import licence_guard  # noqa: E402

# Before anything is analysed. An environment that has the GPL-only packages
# installed can supply them to a hook or a stray import, and finding that out
# after the exe exists is finding it out too late.
licence_guard.check_build_environment()

# Read, never typed. `VERSION` is the only source of truth for it, and the
# built file is named for it so two downloads a year apart are not two files
# called the same thing. `fpx_gui.invoke` re-executes `sys.executable`, so
# the name is free to change.
VERSION = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()

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
]

datas = [
    # The stylesheet, read through importlib.resources at startup.
    (str(REPO_ROOT / "fpx_gui" / "style.qss"), "fpx_gui"),
    # The licence texts behind Help -> Licences, read the same way. They are
    # here because a downloaded exe travels alone: there is no folder of
    # licence files beside it, and LGPLv3 section 4 wants the notice to reach
    # each copy of the work. Dropping these from the bundle is not a cosmetic
    # regression -- `fpx_gui.notices.read_licence` raises and the dialog
    # cannot open.
    (str(REPO_ROOT / "fpx_gui" / "licences"), "fpx_gui/licences"),
    # The single source of truth for the version. `fpx_converter.__init__`
    # reads it from beside the package, which inside the bundle is the bundle
    # root -- so `--version` tells the truth instead of saying "unknown".
    # Shipping the file is not a second copy of the version; hardcoding a
    # string here would be.
    (str(REPO_ROOT / "VERSION"), "."),
]

excludes = [
    # -- licence, not size -------------------------------------------------
    # pyexiv2 is GPL-3.0 and ships `exiv2.dll` (GPL-2.0-or-later). It is a
    # development dependency only: `fpx_converter.validator` imports it to
    # read written metadata back with a different library than the one that
    # wrote it, which is a rule this project keeps and a thing a shipped
    # conversion does not do. Excluded so the analyser cannot follow that
    # import, and checked below so the exclusion cannot fail open.
    "pyexiv2",
    # -- size, not licence -------------------------------------------------
    # PySide6-Addons is not installed (requirements-gui.txt pins
    # PySide6-Essentials and shiboken6), so the GPLv3-only Qt modules are
    # absent by construction rather than by a list of names that has to be
    # kept up to date as Qt grows modules. What remains here is Essentials
    # that this window does not use. Everything in the list has been removed
    # and the result launched; anything that turns out to be needed belongs
    # back in this list, not behind a wider net.
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickTest",
    "PySide6.QtQuickWidgets",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtStateMachine",
    "PySide6.QtUiTools",
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
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

# The check that matters, on what the analysis actually resolved rather than
# on what the excludes above intended. Raises and stops the build.
licence_guard.check_bundle(analysis.binaries, analysis.datas, analysis.pure)

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
    # needs a terminal -- see `fpx_gui/runner.py`.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
