# FPX Converter

[![CI](https://github.com/sremich/fpx-converter/actions/workflows/ci.yml/badge.svg)](https://github.com/sremich/fpx-converter/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/sremich/fpx-converter)](https://github.com/sremich/fpx-converter/releases/latest)
[![Licence: Apache-2.0](https://img.shields.io/badge/licence-Apache--2.0-blue.svg)](LICENSE)

Converts Kodak `.fpx` (FlashPix) photographs — the format the DC200 and DC210
wrote around 2000 — into archival TIFFs and shareable JPEGs, carrying the
metadata across instead of throwing it away.

![The FPX Converter window](docs/images/main-window.png)

## What it does

- **Decodes `.fpx` files that nothing modern opens.** Its own decoder, not a
  wrapper round a broken one.
- **Writes two useful things:** a lossless TIFF with every pixel the camera
  captured, and a JPEG that opens anywhere.
- **Keeps the metadata** as standard EXIF, XMP and IPTC — and is careful about
  dates, because a wrong date is worse than none.
- **Never writes to your originals.** The folder you point it at is only ever
  read from. Nothing under it is written, moved, renamed or deleted, and a
  destination inside it is refused with an explanation.
- **Runs unattended over thousands of files,** never stopping the batch for one
  bad file, and picking up where it left off if it is interrupted.

## Download and run (Windows)

### 1. Download the app

Get `fpx-converter-<version>.exe` from
**[the latest release](https://github.com/sremich/fpx-converter/releases/latest)**.
One file. Nothing to install, no Python needed.

### 2. Windows will warn you. This is expected

The app is **not code-signed**, so Windows treats it as an unknown program.
Code-signing certificates cost money every year and this is a free tool, so it
ships unsigned. You will see up to three warnings, in this order:

1. **Your browser** says the file "isn't commonly downloaded" or similar.
   Choose **Keep** — in Chrome and Edge this is behind the **…** menu next to
   the download, then **Keep anyway**.
2. **A blue full-screen box:** *"Windows protected your PC"*. The only button
   you can see is **Don't run**. Click the small **More info** link above it,
   then the **Run anyway** button that appears.
3. **Possibly your antivirus.** One-file bundles built with PyInstaller are a
   well-known false-positive trigger for heuristic scanners. If yours objects,
   the honest answer is to check the source and build it yourself — see
   [docs/BUILD.md](docs/BUILD.md).

None of that is a judgement about the file. It is what Windows shows for every
program that has not paid for a certificate.

### 3. Install ExifTool

ExifTool writes the metadata. It is a separate program with its own licence, so
it is not bundled and has to be installed once.

Open a terminal — press <kbd>Win</kbd>, type `powershell`, press
<kbd>Enter</kbd> — and run:

```powershell
winget install --id OliverBetz.ExifTool
```

Check it worked by closing that window, opening a new one, and running:

```powershell
exiftool -ver
```

A version number means you are done. If `winget` is not recognised (older
Windows 10), download the Windows package from
[exiftool.org](https://exiftool.org/) instead, unzip it, and point the app at
`exiftool.exe` with the `FPX_EXIFTOOL` setting or the `--exiftool` flag.

Without ExifTool, `convert` refuses to start and tells you so. It does not
write a run's worth of images and then report every one of them failed.

### 4. Pick folders and press Convert

Choose the folder holding your `.fpx` photos, choose where the converted
photos should go, pick one of the three output choices, and press **Convert**.

**Full walkthrough, in plain language: [docs/GUIDE.md](docs/GUIDE.md).**

## What you get

```
<destination>/
  archive/2002/Summer 2002/2002-07-04_143210_Backyard.tif
  sharing/2002/Summer 2002/2002-07-04_143210_Backyard.jpg
  conversion.log
  audit_report.json
  run-state.json
```

The command line writes both trees by default. **The desktop app writes one
image per photograph** — whichever of its three choices you picked — and the
tree it lands in follows the framing, so a whole-frame image goes to `archive/`
and a cropped one to `sharing/`.

- **`archive/`** keeps the **full frame**, lossless — every pixel the camera
  captured. **`sharing/`** gets the **crop**, where somebody framed one in the
  Kodak software at the time.
- **Folders** keep your own folder names by default, nested under the year; you
  can also file by year, by year and month, all in one folder, or by a pattern.
- **Filenames** are `{year}-{month}-{day}_{time}_{name}` by default, with any
  part the evidence does not support written as zeros. `{name}` is required in
  any pattern you write: in this kind of archive the filename is the only thing
  a person actually typed, and a pattern without it discards that for good.

## About the dates

**There is no capture date in these files.** The FlashPix capture-date property
is absent from every one of them; the only timestamp present is an
import-batch stamp, recording when the photographs reached a computer.

So that stamp goes to `DateTimeDigitized`, never to `DateTimeOriginal`.
`DateTimeOriginal` is written only where a date is defensible as a **single
day** — a day-precise folder name, an embedded film-scan date, or a date you
supply yourself through the review page. A folder naming a year or a season
gives an ordering key and a filename prefix, not a claim. That is why many of
your filenames will read `0000-00-00_000000_`: the archive being honest.

**[docs/DATES.md](docs/DATES.md)** explains all of it, including how to supply
the dates you know.

## Something went wrong

**[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)** — SmartScreen, missing
ExifTool, filenames full of zeros, wrong time zones, and the rest.

---

## Run from source

The command line is the whole converter; the window is a front end over it.

```sh
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt   # Windows
# .venv/bin/python -m pip install -r requirements-dev.txt          # POSIX

python -m ruff check .
python -m pytest
```

Install `-r requirements-gui.txt` instead if you are working on the desktop
front end, building the executable, or running its tests — it pulls in
`requirements-dev.txt` as well as Qt.

Then, at its shortest, a conversion is two commands:

```sh
python -m fpx_converter scan ./photos --manifest ./work/manifest.json
python -m fpx_converter convert --manifest ./work/manifest.json --dest ./converted
```

**Every command and flag: [docs/CLI.md](docs/CLI.md).**
ExifTool is a separate install; see step 3 above.

## How it works

- A `.fpx` file is an **OLE2 compound document** holding a resolution pyramid
  of JPEG-compressed tiles, with the JPEG tables stored apart from the tiles.
- The decoder reads the tile table, splices the tables back onto each tile,
  stitches, crops to the declared size, and applies the file's own viewing
  transform — a 90° rotation, a crop, or both.
- Colour space is read **per file** — NIF RGB or PhotoYCC. A file that declares
  neither is decoded as RGB and says so, in the log and the audit report.
- **ExifTool writes** the tags and **Pillow reads them back**, with
  `defusedxml` for the XMP packet. Validating with the tool that wrote proves
  much less than it appears to.
- Pillow's own `FpxImagePlugin` is never used in the conversion path: on the
  reference corpus it opened 39 of 1,265 files and hard-crashed CPython on two.

**[docs/FORMAT.md](docs/FORMAT.md)** is the full format write-up;
**[ARCHITECTURE.md](ARCHITECTURE.md)** is why the pipeline is shaped this way.

## Status and limitations

- **Windows is the tested platform.** CI runs on `windows-latest` with Python
  3.14. The CLI has no Windows-only dependencies and should run on macOS and
  Linux, but it is not tested there — treat that as unverified, not supported.
  The desktop app is Windows-only, shipped as a single `.exe`.
- **Python 3.14.** `pyproject.toml` declares `>=3.14`; 3.14 is what CI runs and
  what the exact dependency pins are verified against.
- **Rotation and rotation-plus-crop have no fixture cover.** Every rotated file
  in the corpus this was built from contains people and cannot be published, so
  the only automated cover for that branch is a local run over a real archive —
  and it is the branch that once carried a defect where rotated-and-cropped
  files silently lost their crop. See
  [`tests/fixtures/README.md`](tests/fixtures/README.md) and
  [docs/TESTING.md](docs/TESTING.md).
- Colour and orientation need **eyes at least once per variant**. "It decoded"
  is not "it decoded correctly", and this project has the scars to prove it —
  see [docs/PROJECT-HISTORY.md](docs/PROJECT-HISTORY.md).

## Documentation

| Document | Purpose |
|---|---|
| [docs/GUIDE.md](docs/GUIDE.md) | Using the desktop app, start to finish, no jargon |
| [docs/CLI.md](docs/CLI.md) | Every command, every flag, the run artifacts |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | When something goes wrong |
| [docs/DATES.md](docs/DATES.md) | Why the dates work the way they do |
| [docs/FORMAT.md](docs/FORMAT.md) | What a `.fpx` file actually is |
| [ARCHITECTURE.md](ARCHITECTURE.md) | The pipeline, and the rules behind it |
| [docs/TESTING.md](docs/TESTING.md) | The test tiers and what they cover |
| [docs/BUILD.md](docs/BUILD.md) | Building the Windows executable |
| [docs/PROJECT-HISTORY.md](docs/PROJECT-HISTORY.md) | How it got here, and what was refuted on the way |
| [CHANGELOG.md](CHANGELOG.md) | Release history |

## Contributing

Bug reports, questions and pull requests go to
[the issue tracker](https://github.com/sremich/fpx-converter/issues). Read
[CONTRIBUTING.md](CONTRIBUTING.md) first — it lists the rules that are not
negotiable, chief among them that the source archive is read-only and that
nothing personal goes in the repository. Security reports:
[SECURITY.md](SECURITY.md).

## Licence

Apache License 2.0. Copyright Stevie Remich. See [LICENSE](LICENSE) and
[NOTICE](NOTICE). Third-party components keep their own licences, listed in
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) with the full copyleft texts
in [LICENSES/](LICENSES); the same notice is inside the application, under
**Help → Licences**. The test fixtures are **not** covered by the Apache
licence — see [tests/fixtures/LICENSE.md](tests/fixtures/LICENSE.md).

## Trademarks

Kodak, FlashPix, DC200 and DC210 are trademarks of Eastman Kodak Company; this
project is independent and unaffiliated.

## Acknowledgements

[ExifTool](https://exiftool.org/) by Phil Harvey writes every tag this tool
produces. [Qt for Python (PySide6)](https://doc.qt.io/qtforpython/) by The Qt
Company, used unmodified and linked dynamically, is the window. Pillow, NumPy,
olefile and defusedxml do the rest of the heavy lifting.
