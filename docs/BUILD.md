# Building the Windows executable

`dist/fpx-converter-<version>.exe` is the whole desktop application — Python,
Qt and the converter in one file. The audience does not use a terminal and must
not have to think about a virtual environment.

Windows only. There is no Mac or Linux build of the window.

You do not need to build this yourself to use the app; downloads are on
[the releases page](https://github.com/sremich/fpx-converter/releases/latest).
Build it if you want to verify what you are running, or if you are working on
the front end.

## Set up, once

The GUI needs its own environment. Qt stays out of the converter's own
environment on purpose: the pipeline that runs over an irreplaceable archive
must not depend on a GUI toolkit.

```sh
python -m venv .venv-gui
.venv-gui/Scripts/python.exe -m pip install -r requirements-gui.txt
```

`requirements-gui.txt` pulls in `requirements-dev.txt`, so this environment
runs the whole test suite as well as the build.

> **If Windows long-path support is disabled on your machine** — it is off by
> default — deep paths corrupt installs and writes. Put the virtual
> environment somewhere short, such as a top-level `C:\venvs\`, rather than
> inside a deeply nested project folder.

## Build

```sh
.venv-gui/Scripts/python.exe -m PyInstaller --noconfirm packaging/fpx-converter.spec
```

Output: `dist/fpx-converter-<version>.exe`, named for `VERSION`, which the spec
reads. `build/` and `dist/` are gitignored; the `.spec` is not, because it is
the build definition rather than build output.

The build fails **loudly, and before the exe exists**, if anything copyleft
reaches the bundle. See [Licences](#licences) below; that is not a warning to
work around.

## Check it

The exe wears two hats, and both need trying.

```powershell
# the command-line hat -- the one a conversion actually runs through
dist\fpx-converter-<version>.exe --run-cli --version
dist\fpx-converter-<version>.exe --run-cli scan tests\fixtures --manifest %TEMP%\fpx\manifest.json
dist\fpx-converter-<version>.exe --run-cli convert --manifest %TEMP%\fpx\manifest.json --dest %TEMP%\fpx --limit 2 --progress

# the window
dist\fpx-converter-<version>.exe
```

The `convert` above is the real check: it exercises the decoder and the Pillow
plugins, which is what a missing hidden import breaks. A `--version` call
cannot see any of that. If `--version` prints `unknown`, `VERSION` did not make
it into the bundle.

Open **Help → Licences** in the window as well. It reads two text files out of
the bundle, so it doubles as the check that `fpx_gui/licences/` was packaged; a
dialog that will not open means a notice that does not ship.

The release workflow does all of this before it publishes: it builds the exe,
converts two fixtures *through it*, and only then creates the release. A build
that fails must not leave a published release with nothing in it.

## What is not in the box

**ExifTool.** A separate program with its own licence, not a Python package,
installed with `winget install --id OliverBetz.ExifTool`. The exe runs without
it, and conversions then refuse to start. Anyone installing this on a fresh
machine needs ExifTool too. See [NOTICE](../NOTICE).

**The GPL-3.0 metadata library used in development.** `requirements-dev.txt`
installs a second, independent metadata reader that the tier-2 and tier-3 tests
use as a third opinion on written files. It is GPL-3.0 and carries a
GPL-2.0-or-later native library with it, so bundling it would relicense the
whole executable, which this project publishes under Apache-2.0. It is a
test-time dependency and is never packaged. The shipped read-back path uses
Pillow with `defusedxml` for the XMP packet — still a different tool from the
one that wrote, which is the rule that matters. See
[ARCHITECTURE.md](../ARCHITECTURE.md) and
[THIRD-PARTY-NOTICES.md](../THIRD-PARTY-NOTICES.md).

**Qt Addons.** `requirements-gui.txt` installs `PySide6-Essentials`, not the
`PySide6` metapackage, so the GPLv3-only Addons modules are not present on the
build machine at all.

## Licences

Two mechanisms, doing different jobs.

**`packaging/licence_guard.py` fails the build.** It refuses an environment
with `PySide6-Addons` installed, and after PyInstaller's analysis it inspects
every binary, data file and pure module that was actually resolved, raising on
anything that matches the excluded metadata libraries. The spec's `excludes`
list alone is a denylist, and denylists fail open: if a rename or a hook slips
something past it, the build succeeds and the exe looks exactly the same. This
check is the reason that cannot happen quietly. It is unit-tested by
`tests/test_gui_packaging.py` — a spec file cannot be imported, which is why
the logic does not live in one.

**`fpx_gui/notices.py` ships the notice.** The full LGPL-3.0 and GPL-3.0 texts
live in `fpx_gui/licences/` and are bundled as data, read through
`importlib.resources`. A downloaded exe arrives with nothing beside it, so the
notice has to be inside it — which is what **Help → Licences** shows.

The Qt libraries are LGPL-3.0, used unmodified and linked dynamically. The
compliance section of [THIRD-PARTY-NOTICES.md](../THIRD-PARTY-NOTICES.md)
carries the corresponding source and the relink instructions LGPLv3 section 4
requires.

## Notes on the spec

- **The entry script is `packaging/entry.py`**, not `fpx_gui/__main__.py`.
  PyInstaller runs the entry as a top-level script, and `__main__.py` uses
  relative imports that need a package around them.
- **`VERSION` is bundled at the root.** `fpx_converter.__init__` reads it from
  beside the package, which inside the bundle is the bundle root. Shipping the
  file keeps the single source of truth single; a literal in the spec would be
  a second copy of it.
- **Qt is trimmed by what is installed, then by exclusion.** The Addons wheel
  is not installed, so 3D, Charts, Multimedia, WebEngine and the rest are
  absent by construction. `excludes` covers only Essentials modules the window
  does not use. Everything in that list has been removed and the result
  launched; anything that turns out to be needed belongs back in the list,
  rather than behind a wider net.
- **`console=False`.** The window has no terminal behind it. The CLI child is
  launched with its own hidden console and its output read through a pipe — see
  `fpx_gui/runner.py`, which also explains why the cancel path needs that
  console to exist.

## Releasing

CI owns releases. A tag `vX.Y.Z` is pushed; CI verifies the tag matches
`VERSION`, lints, tests, builds the exe, exercises it, and only then creates
the GitHub release. Never create a release or edit a tag by hand — if CI fails,
no partial release exists; fix it and re-tag.

The version lives only in `VERSION`. `pyproject.toml` reads it dynamically, and
a test refuses a second source of truth.
