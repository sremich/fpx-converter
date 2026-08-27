# Building the standalone executable

One file, nothing to install: `dist/fpx-converter-<version>.exe` is the whole desktop
application, Python and Qt included. The audience does not use a terminal and
must not have to think about a virtual environment.

## Once

The GUI needs its own environment. Keep it at a **short** path — Windows
long-path support is disabled on the dev machine and deep paths corrupt
installs.

```sh
py -3.14 -m venv C:\venvs\fpxgui
C:\venvs\fpxgui\Scripts\python.exe -m pip install -r requirements-gui.txt
```

`requirements-gui.txt` pulls in `requirements-dev.txt`, so this environment
runs the whole test suite as well as the build. The converter's own venv
(`C:\venvs\fpx`) stays free of Qt on purpose: the pipeline that runs over the
archive must not depend on a GUI toolkit.

## Every time

```sh
C:\venvs\fpxgui\Scripts\python.exe -m PyInstaller --noconfirm packaging/fpx-converter.spec
```

Output: `dist/fpx-converter-<version>.exe` -- named for `VERSION`, which the spec reads -- about 67 MB. `build/` and `dist/` are
gitignored; the `.spec` is not, because it is the build definition rather than
build output.

## Checking it

The exe wears two hats, and both need trying:

```sh
# the command line hat -- the one a conversion actually runs through
dist\fpx-converter-<version>.exe --run-cli --version
dist\fpx-converter-<version>.exe --run-cli scan --source tests\fixtures --manifest %TEMP%\fpx\manifest.json
dist\fpx-converter-<version>.exe --run-cli convert --manifest %TEMP%\fpx\manifest.json --dest %TEMP%\fpx --limit 2 --progress

# the window
dist\fpx-converter-<version>.exe
```

The convert above is the real check: it exercises the bundled `pyexiv2`
extension and the Pillow plugins, which are the two things a missing hidden
import breaks. If `--version` prints `unknown`, `VERSION` did not make it into
the bundle.

## What is not in the box

**ExifTool.** It is a separate program with its own licence, not a Python
package, and it is installed with
`winget install --id OliverBetz.ExifTool` — see `DECISIONS.md`. The exe runs
without it, and conversions then fail their metadata write. Anyone installing
this on a fresh machine needs ExifTool too.

## Notes on the spec

- **Entry script is `packaging/entry.py`**, not `fpx_gui/__main__.py`.
  PyInstaller runs the entry as a top-level script, and `__main__.py` uses
  relative imports that need a package around them.
- **`pyexiv2` is collected whole** (`collect_all`). It is a compiled
  extension with a data directory beside it; a hidden import alone produces an
  exe that imports and then cannot read a tag.
- **`VERSION` is bundled at the root.** `fpx_converter.__init__` reads it from
  beside the package, which inside the bundle is the bundle root. Shipping the
  file keeps the single source of truth single — a literal in the spec would
  be a second copy of it.
- **Qt is trimmed by exclusion.** WebEngine, QML/Quick, 3D, Multimedia,
  Charts and the rest are named in `excludes`. Everything in that list has
  been removed and the result launched; anything that turns out to be needed
  belongs back in the list, not behind a wider net.
- **`console=False`.** The window has no terminal behind it. The CLI child is
  launched with its own hidden console and its output read through a pipe —
  see `fpx_gui/runner.py`, which also explains why the cancel path needs that
  console to exist.
