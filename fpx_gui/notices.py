"""What this application is built from, and under what terms.

A downloaded `.exe` arrives on its own. There is no folder of licence files
beside it, no `site-packages` to look in and no README within reach, so a
notice that lives anywhere but inside the binary does not reach the person
running it. LGPLv3 section 4 asks for the notice to travel *with each copy*
of the work, and for the Qt libraries that is not a formality this project
gets to skip.

So the texts are package data, read through `importlib.resources` exactly as
`style.qss` is, and the window shows them in a dialog. Frozen or from a
checkout, the same call finds the same file.

**Deliberately Qt-free.** The notice is text and a couple of file reads; the
dialog that displays it is the only part that needs a toolkit. Keeping them
apart means the contents can be tested with no display, and the test that
checks a pinned version against `requirements.txt` costs nothing to run.

The versions below are written out rather than read from the environment:
inside a frozen exe there is no `dist-info` to ask. `tests/test_gui_packaging.py`
compares each one against the pin it claims to describe, so a bumped
dependency fails a test rather than shipping a notice that names the wrong
version.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources

import fpx_converter

#: Where the full texts live inside the package, and what they are called.
#:
#: Byte-identical copies of the repository's own `LICENSES/` directory, which
#: is the source of truth for them; `tests/test_gui_packaging.py` fails if the
#: two ever differ. They are copied rather than referenced because these have
#: to be *inside the executable* -- `LICENSES/` is a directory in a source
#: checkout, and nobody who downloads an exe has one.
LICENCE_DIR = "licences"
APACHE_2_0 = "Apache-2.0.txt"
LGPL_3_0 = "LGPL-3.0.txt"
GPL_3_0 = "GPL-3.0.txt"
LICENCE_FILES: tuple[str, ...] = (APACHE_2_0, LGPL_3_0, GPL_3_0)

#: This project's own terms.
PROJECT_LICENCE = "Apache-2.0"
PROJECT_URL = "https://github.com/sremich/fpx-converter"
ISSUES_URL = f"{PROJECT_URL}/issues"


@dataclass(frozen=True)
class Component:
    """One thing this application is made of, and the terms it arrives under."""

    name: str
    version: str
    licence: str
    #: The distribution name on PyPI, where there is one. `None` means the
    #: component is not a Python package and is not pinned anywhere -- which
    #: is only true of ExifTool, and is the whole point of saying so.
    pypi: str | None
    #: Which requirements file carries the pin, for the test that checks it.
    pinned_in: str | None
    note: str
    source: str


#: Everything the published executable contains, plus the one thing it needs
#: and does not contain. Order is the order the dialog shows them in: the
#: copyleft ones first, because they are the ones carrying an obligation.
COMPONENTS: tuple[Component, ...] = (
    Component(
        name="PySide6-Essentials (Qt for Python)",
        version="6.11.2",
        licence="LGPL-3.0-only",
        pypi="PySide6-Essentials",
        pinned_in="requirements-gui.txt",
        note=(
            "Copyright (C) The Qt Company Ltd. Used UNMODIFIED and linked "
            "dynamically. You may replace it: rebuild this application from "
            "source against your own copy of the same version, per LGPLv3 "
            "section 4."
        ),
        source=(
            "https://pypi.org/project/PySide6-Essentials/6.11.2/#files  and "
            "https://download.qt.io/official_releases/QtForPython/"
        ),
    ),
    Component(
        name="shiboken6",
        version="6.11.2",
        licence="LGPL-3.0-only",
        pypi="shiboken6",
        pinned_in="requirements-gui.txt",
        note=(
            "Copyright (C) The Qt Company Ltd. The binding layer under "
            "PySide6. Used UNMODIFIED."
        ),
        source="https://pypi.org/project/shiboken6/6.11.2/#files",
    ),
    Component(
        name="Pillow",
        version="12.3.0",
        licence="MIT-CMU",
        pypi="pillow",
        pinned_in="requirements.txt",
        note="Reads and writes the image files.",
        source="https://pypi.org/project/pillow/12.3.0/",
    ),
    Component(
        name="olefile",
        version="0.47",
        licence="BSD-2-Clause",
        pypi="olefile",
        pinned_in="requirements.txt",
        note="Opens the OLE compound-document container a .fpx file is.",
        source="https://pypi.org/project/olefile/0.47/",
    ),
    Component(
        name="NumPy",
        version="2.5.2",
        licence="BSD-3-Clause",
        pypi="numpy",
        pinned_in="requirements.txt",
        note="The pixel arithmetic.",
        source="https://pypi.org/project/numpy/2.5.2/",
    ),
    Component(
        name="defusedxml",
        version="0.7.1",
        licence="PSF-2.0",
        pypi="defusedxml",
        pinned_in="requirements.txt",
        note="Parses the XMP packet when the metadata is read back.",
        source="https://pypi.org/project/defusedxml/0.7.1/",
    ),
    Component(
        name="ExifTool, by Phil Harvey",
        version="",
        licence="Perl Artistic / GPL-1.0-or-later",
        pypi=None,
        pinned_in=None,
        note=(
            "NOT BUNDLED — its licence would permit bundling, but this "
            "project chooses not to: it keeps the process boundary clean, "
            "avoids taking on another project's release cadence and "
            "security updates, and keeps the executable small. It is a "
            "separate program with its own licence, installed by you and "
            "run as a separate process. Nothing of it is inside this "
            "executable and none of its terms reach this program."
        ),
        source="https://exiftool.org/",
    ),
)


def read_licence(name: str) -> str:
    """One full licence text, read as package data so it survives freezing.

    Same call shape as `style.read_template`: `importlib.resources` finds the
    file beside the package in a checkout and inside the bundle in the exe,
    and neither caller has to know which it is looking at.
    """
    if name not in LICENCE_FILES:
        raise KeyError(f"no bundled licence text called {name!r}")
    return (
        resources.files(__package__)
        .joinpath(LICENCE_DIR, name)
        .read_text(encoding="utf-8")
    )


def notice_text() -> str:
    """The notice itself: what this is, what is in it, and where to get it."""
    lines = [
        f"FPX Converter {fpx_converter.__version__}",
        "",
        f"This program is published under the {PROJECT_LICENCE} licence.",
        PROJECT_URL,
        "",
        "It is built from the components below. Each one keeps its own "
        "licence; nothing here changes them.",
        "",
    ]
    for component in COMPONENTS:
        heading = component.name
        if component.version:
            heading = f"{heading} {component.version}"
        lines += [
            f"{heading} — {component.licence}",
            f"    {component.note}",
            f"    Source: {component.source}",
            "",
        ]
    lines += [
        "The corresponding source",
        "",
        "    The LGPL libraries above are used unmodified. Their complete "
        "corresponding source is published at the addresses listed beside "
        "them, in the exact versions this program was built against. Qt's own "
        "sources are at https://download.qt.io/archive/qt/ .",
        "",
        "    This program's own source is at "
        f"{PROJECT_URL} , where THIRD-PARTY-NOTICES.md carries the "
        "same information in full, including the relink instructions "
        "LGPLv3 section 4(d)(0) asks for.",
        "",
        "Questions, requests, and anything you think is wrong here",
        "",
        f"    Please open an issue: {ISSUES_URL}",
        "    That is the only channel; no email address is published.",
        "",
        "The full texts are on the other tabs of this window: the Apache "
        "License 2.0 this program is published under, the LGPLv3 the Qt "
        "libraries are used under, and the GPLv3 that the LGPLv3 is written "
        "on top of and cannot be read without.",
    ]
    return "\n".join(lines)
