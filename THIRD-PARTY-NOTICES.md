# Third-party notices

FPX Converter is published under the Apache License, Version 2.0 (see
[`LICENSE`](LICENSE)). It is built from the components below, each of which
keeps its own licence. Nothing in this file changes any of them, and nothing
here places any part of them under the Apache License.

Two questions decide what a component obliges you to do, and they are not the
same question:

- **Does it ship inside the published Windows executable?** If it does, its
  terms travel with every copy of that executable.
- **Is it only present while the project is being developed or tested?** Then
  its terms bind contributors and CI, and reach nobody who downloads a
  release.

The table records both. Full texts of the copyleft licences are in
[`LICENSES/`](LICENSES/).

## Components

| Component | Version | Licence | In the `.exe`? | What it does here | Obligation |
|---|---|---|---|---|---|
| [PySide6-Essentials](https://pypi.org/project/PySide6-Essentials/6.11.2/) (Qt for Python) | 6.11.2 | LGPL-3.0-only | **Yes** | The desktop window's toolkit | LGPLv3 §4 — see [LGPL compliance](#lgpl-compliance) below |
| [shiboken6](https://pypi.org/project/shiboken6/6.11.2/) | 6.11.2 | LGPL-3.0-only | **Yes** | The C++/Python binding layer under PySide6 | LGPLv3 §4 — see [LGPL compliance](#lgpl-compliance) below |
| [Pillow](https://pypi.org/project/pillow/12.3.0/) | 12.3.0 | MIT-CMU | **Yes** | Decodes the JPEG tiles; writes the TIFF and JPEG outputs; reads metadata back for validation | Retain copyright and permission notice |
| [NumPy](https://pypi.org/project/numpy/2.5.2/) | 2.5.2 | BSD-3-Clause (bundled components under further permissive licences) | **Yes** | The pixel arithmetic — tile stitching, the PhotoYCC transform, the correctness oracles | Retain copyright notice and disclaimer |
| [olefile](https://pypi.org/project/olefile/0.47/) | 0.47 | BSD-2-Clause | **Yes** | Opens the OLE compound-document container that a `.fpx` file is, and reads its streams | Retain copyright notice and disclaimer |
| [defusedxml](https://pypi.org/project/defusedxml/0.7.1/) | 0.7.1 | PSF-2.0 | **Yes** | Parses the XMP packet during metadata read-back. Pillow's `Image.getxmp()` returns an empty dict without it, which would turn every XMP check into a check that cannot fail | Retain PSF licence and notice |
| [PyInstaller](https://pypi.org/project/pyinstaller/6.22.2/) runtime hooks | 6.22.2 | Apache-2.0 (the rthooks copied into a frozen app) | **Yes** (the hooks only) | Bootstrap code PyInstaller copies into the frozen application | Retain notice; see note below |
| [PyInstaller](https://pypi.org/project/pyinstaller/6.22.2/) (the build tool) | 6.22.2 | GPL-2.0-or-later with the bootloader exception | No — build-time only | Builds the single-file Windows executable | None on redistributors of the built app; the exception exists for exactly this |
| [pyinstaller-hooks-contrib](https://pypi.org/project/pyinstaller-hooks-contrib/2026.7/) | 2026.7 | Apache-2.0 / GPL-2.0-or-later (per hook) | No — build-time only | Supplies the hooks that decide which binaries and data files land in the bundle | None on redistributors of the built app |
| [pyexiv2](https://pypi.org/project/pyexiv2/2.16.0/) | 2.16.0 | GPL-3.0-or-later (bundles `exiv2.dll`, GPL-2.0-or-later) | **No — deliberately excluded** | A dev-only third opinion in the tests: ExifTool writes, Pillow reads back, exiv2 re-reads the same files with its own parser | Dev/test only. It must never be imported by `fpx_converter`; see [Why pyexiv2 is not in the executable](#why-pyexiv2-is-not-in-the-executable) |
| [pytest](https://pypi.org/project/pytest/9.1.1/) | 9.1.1 | MIT | No — dev only | Test runner | Dev only |
| [pytest-qt](https://pypi.org/project/pytest-qt/4.5.0/) | 4.5.0 | MIT | No — dev only | Widget-test plumbing | Dev only |
| [ruff](https://pypi.org/project/ruff/0.16.4/) | 0.16.4 | MIT | No — dev only | Linter | Dev only |
| [ExifTool](https://exiftool.org/), by Phil Harvey | user-installed | Perl Artistic **or** GPL-1.0-or-later, at your option | **No — cannot be** | Writes the EXIF/XMP/IPTC tags onto the converted images | None on this project; see [ExifTool](#exiftool) |

Versions come from the pin files: `requirements.txt` (runtime),
`requirements-dev.txt` (dev and test), `requirements-gui.txt` (the desktop
front end and the packaging toolchain). Every dependency is pinned exactly —
this pipeline runs once over an irreplaceable archive, so a silent upstream
change in a decoder or a metadata writer is a correctness risk rather than a
convenience one.

### A note on the PyInstaller entries

PyInstaller appears twice on purpose, because two different things with two
different licences are involved. The **program** that performs the build is
GPL-2.0-or-later; it is a tool that this project runs and does not
redistribute, so its copyleft does not reach the built application. The
**runtime hooks** PyInstaller copies *into* the frozen application are
separately licensed Apache-2.0 by the PyInstaller Development Team precisely
so that a frozen application may be distributed under the terms of its own
author's choosing. The bootloader carries an explicit exception to the same
effect.

### ExifTool

ExifTool is **not bundled and cannot be bundled**. It is a separate program
with its own licence, installed by the user (`winget install --id
OliverBetz.ExifTool`) and invoked by this project as a separate process with
command-line arguments. No part of it is contained in this project's source
or in its published executable, no part of it is linked into anything here,
and none of its terms reach this program. If you redistribute ExifTool
yourself, its terms are between you and its author.

## LGPL compliance

This section is the notice that the GNU Lesser General Public License,
version 3, section 4 requires to accompany each copy of the published Windows
executable. The full text of the LGPLv3 is at
[`LICENSES/LGPL-3.0.txt`](LICENSES/LGPL-3.0.txt), and the full text of the
GPLv3 that it is written on top of is at
[`LICENSES/GPL-3.0.txt`](LICENSES/GPL-3.0.txt). **Both are required**: LGPLv3
§4(d) is satisfied only by supplying the LGPL together with the GPL it
incorporates by reference, and the LGPL text on its own is incomplete.

The same notice is also readable from inside the application itself, under
**Help → Licences**, because a downloaded `.exe` arrives with no folder of
licence files beside it and a notice that only exists in a source repository
does not reach the person running the program.

### The libraries

| Library | Version | Copyright | Licence |
|---|---|---|---|
| PySide6-Essentials (Qt for Python) | 6.11.2 | © The Qt Company Ltd. | LGPL-3.0-only |
| shiboken6 | 6.11.2 | © The Qt Company Ltd. | LGPL-3.0-only |

**Both libraries are used UNMODIFIED.** No patch, no fork, no vendored change
of any kind has been applied to either of them. They are installed from the
official published wheels at the exact pinned version above and linked
dynamically; the published executable contains those wheels' binaries as
built and shipped by The Qt Company.

Only the LGPL-licensed `PySide6-Essentials` is used. The `PySide6-Addons`
distribution — some of whose modules are GPLv3-only — is not installed and
not bundled, and `packaging/licence_guard.py` fails the build if it is
present in the build environment or appears in the bundle, because a
mislicensed executable does not look any different from a correct one.

### Complete corresponding source

The complete corresponding source for the LGPL libraries, in the exact
versions this application was built against, is published at:

- **PySide6-Essentials 6.11.2** —
  <https://pypi.org/project/PySide6-Essentials/6.11.2/#files>
- **shiboken6 6.11.2** — <https://pypi.org/project/shiboken6/6.11.2/#files>
- **PySide6/shiboken6 source repository**, tag `v6.11.2` —
  <https://code.qt.io/cgit/pyside/pyside-setup.git>
- **Qt 6.11 sources**, which the above binds to —
  <https://download.qt.io/archive/qt/6.11/>

### Your right to relink (LGPLv3 §4(d)(0))

You may modify PySide6-Essentials or shiboken6 and run this application
against your modified version. The application is built from source with a
published build definition, so the route is the ordinary one:

1. Clone this repository:
   `git clone https://github.com/sremich/fpx-converter`
2. Create a virtual environment and install the build requirements:
   `python -m pip install -r requirements-gui.txt`
3. Install your modified `PySide6-Essentials` (and/or `shiboken6`) over the
   pinned one, at the same version.
4. Rebuild: `pyinstaller packaging/fpx-converter.spec`

The resulting executable is the same application running against your build
of the libraries. Nothing in the build is obfuscated, and no key, signature
or licence check stands between the rebuilt executable and running it.

### Written offer

For a period of **three years** from the date you received a copy of the
published Windows executable, the copyright holder will provide, on request,
a machine-readable copy of the complete corresponding source for the
LGPL-licensed libraries listed above — at the exact versions that copy was
built against — on a physical medium customarily used for software
interchange, for a charge no more than the cost of physically performing the
distribution.

**Request it by opening an issue at
<https://github.com/sremich/fpx-converter/issues>.** That is the only channel
for such requests. No email address is published for this project.

## Why pyexiv2 is not in the executable

`pyexiv2` is GPL-3.0-or-later and bundles an `exiv2.dll` that is
GPL-2.0-or-later. Importing it from `fpx_converter` would make the
PyInstaller-built executable a derivative of GPL code and would relicense a
project that ships Apache-2.0. It was a runtime dependency until the
read-back validator moved to Pillow; it is now dev-only, and it remains
valuable there — ExifTool writes the tags, `fpx_converter.validator` reads
them back with Pillow, and the tier-2 and tier-3 tests re-read the same files
with exiv2's own parser. Three independent parsers agreeing is worth more
than two, but only at test time.

Two guards keep it out rather than one, because an exclusion that is merely
written down is an exclusion that can quietly stop being true:

- A tier-1 test fails if `fpx_converter` ever imports `pyexiv2`.
- `packaging/licence_guard.py` runs inside the PyInstaller build, refuses to
  build in an environment where the GPL-only distributions are installed, and
  inspects the finished bundle for their files.

## Test fixtures

The `.fpx` files in `tests/fixtures/` are **not** covered by the Apache
License that covers this software, and they are not third-party dependencies
either. See [`tests/fixtures/LICENSE.md`](tests/fixtures/LICENSE.md) for what
they are, where each came from, and the terms each group carries.

## Corrections

If anything in this file is wrong, incomplete, or names the wrong licence for
a component, please open an issue at
<https://github.com/sremich/fpx-converter/issues>. Getting attribution right
matters more than being seen to have got it right the first time.
