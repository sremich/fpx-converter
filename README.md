# fpx-converter

A 64-bit Python CLI that batch-converts Kodak DC200/DC210 `.fpx`
(FlashPix) photos from a 2000–2002 family archive into archival TIFFs
and shareable JPEGs, preserving every recoverable property into standard
EXIF/XMP/IPTC tags and a complete raw-property JSON sidecar.

It exists because nothing modern opens `.fpx`, and every off-the-shelf
converter either renders black, needs a 32-bit environment, watermarks
the output, or silently discards the metadata — and the metadata carries
the family timeline.

## Status

**Version 0.6.0 (pre-release).** The full conversion pipeline with QA gallery is built
and tested on 40 committed person-free fixtures. Source ingestion, metadata extraction,
pixel decoding, dual-output generation, unattended batch processing with resume-by-hash,
and an HTML review page with per-album date input all work. Full-dataset verification (tier 4)
is the remaining gate for 1.0.0.

What exists:
- **The `fpx_converter` package** with eight commands:
  - `scan` (walk the source archive read-only and write the manifest)
  - `ingest` (copy one file per distinct SHA-256 into the local store)
  - `verify` (re-hash the store against the manifest)
  - `metadata` (extract and dump raw property sidecars as `.fpx.json`)
  - `check-dates` (ground-truth date comparison; supports `--strict` flag)
  - `thumbnail` (extract embedded DIB thumbnails as PNG)
  - `convert` (batch conversion with resume-by-hash, audit reporting, and
    independent format/framing control)
  - `gallery` (build a QA review HTML page with album-date input)
- **Batch engine:** unattended run over the entire corpus, never aborts on
  one bad file, resumes by source SHA-256 across sessions, produces `conversion.log`
  (append-only, flushed per line), `audit_report.json` (describes the output tree),
  and `run-state.json` (keyed on source hash for resume). Ctrl-C still writes state
  and report before returning.
- **QA gallery:** `report/index.html` from any finished run — every photograph as a
  thumbnail from its embedded DIB, filterable by album and audit status, all in one
  self-contained file with no server or build step. Where capture dates are missing,
  the gallery offers a date-entry interface; dates you type come back out as
  `album-dates.json`, which `convert` reads and writes to EXIF `DateTimeOriginal`.
- **603 tests:** tier-1 unit tests (no photos or external tools), tier-2 e2e
  over 40 committed person-free fixtures covering both colour spaces, one
  viewing-transform crop, and six of seven declared sizes, including mutation
  tests for the colour oracle.
- **CI passing on Windows** (python 3.14, `windows-latest`; ExifTool installed).

### First ingestion run (full corpus)

The measured results from the initial production run over the entire
source tree:

- **1,265 files scanned** (read-only), **494.9 MB** total
- **687 distinct SHA-256**, **263.3 MB** of unique data
- **Zero non-OLE2 or corrupt files**
- **Dedup structure:** 114 singletons, 568 pairs, 5 triples
- **Source tree verified** byte-identical after ingest by full
  re-scan producing an identical manifest

### Usage

Most commands require a `.env` file copied from `.env.example`
(set `FPX_SOURCE_ROOT`, `FPX_OUTPUT_ROOT`, `FPX_EXIFTOOL`, and time zone).
Alternatively, `scan` accepts `--source` to override the source location.

```powershell
# Create a venv at a short path (Windows long-path is disabled)
py -3.14 -m venv C:\venvs\fpx
C:\venvs\fpx\Scripts\python.exe -m pip install -r requirements-dev.txt

# Scan the source archive (read-only) and write the manifest
C:\venvs\fpx\Scripts\python.exe -m fpx_converter scan

# Scan with explicit source path (does not require .env)
C:\venvs\fpx\Scripts\python.exe -m fpx_converter scan --source "C:\path\to\archive"

# Copy one file per distinct hash to the local store
C:\venvs\fpx\Scripts\python.exe -m fpx_converter ingest

# Re-hash the store against the manifest
C:\venvs\fpx\Scripts\python.exe -m fpx_converter verify

# Extract raw property sidecars as .fpx.json
C:\venvs\fpx\Scripts\python.exe -m fpx_converter metadata

# Check album folder names against parsed dates
C:\venvs\fpx\Scripts\python.exe -m fpx_converter check-dates

# Extract embedded thumbnails
C:\venvs\fpx\Scripts\python.exe -m fpx_converter thumbnail

# Generate archival TIFF and shareable JPEG with metadata (batch run, resumes on restart)
C:\venvs\fpx\Scripts\python.exe -m fpx_converter convert

# Convert with independent format and framing control
C:\venvs\fpx\Scripts\python.exe -m fpx_converter convert --archive-format tiff --archive-framing full --sharing-format jpeg --sharing-framing cropped

# Generate only a full-frame TIFF (largest uncropped image)
C:\venvs\fpx\Scripts\python.exe -m fpx_converter convert --no-sharing

# Full-frame JPEG in everyday format (for clients who don't open TIFF)
C:\venvs\fpx\Scripts\python.exe -m fpx_converter convert --no-archive --sharing-format jpeg --sharing-framing full

# Convert with a fresh start (ignore prior run's state)
C:\venvs\fpx\Scripts\python.exe -m fpx_converter convert --no-resume

# Build the QA gallery from a completed run (writes <output-root>/report/index.html)
C:\venvs\fpx\Scripts\python.exe -m fpx_converter gallery

# Open the gallery page, fill in missing dates, save as album-dates.json, re-run convert
C:\venvs\fpx\Scripts\python.exe -m fpx_converter convert
```

## Install and test

### Prerequisites

- **Python 3.14** (exactly; the dependency pins target cp314 wheels)
- **Windows 11** (CI runs on `windows-latest`; development is Windows-only)
- **ExifTool** (external binary, not a Python package)

### Quick start

1. Clone the repo.

2. Create a venv at a SHORT path (Windows long-path support is
   disabled on the dev machine):

   ```powershell
   py -3.14 -m venv C:\venvs\fpx
   C:\venvs\fpx\Scripts\python.exe -m pip install -r requirements-dev.txt
   ```

3. Install ExifTool (one-time):

   ```powershell
   winget install --id OliverBetz.ExifTool
   ```

4. Copy `.env.example` to `.env` and fill in the placeholders:

   ```powershell
   copy .env.example .env
   # Edit .env with your source archive path, output root, time zone
   ```

### Run the gates

The tier-1 and tier-2 gates:

```powershell
# Lint
C:\venvs\fpx\Scripts\python.exe -m ruff check .

# Unit and e2e tests (tier 1 + tier 2: 603 tests, no real photos, no source archive)
# Note: some tier-2 tests require ExifTool for metadata round-trip validation
C:\venvs\fpx\Scripts\python.exe -m pytest
```

These gates run on every push to CI. CI installs ExifTool and sets
`FPX_REQUIRE_EXIFTOOL` to enforce the "validate with a different tool than the
one that wrote" rule: ExifTool writes, pyexiv2 reads back.

### Batch conversion artifacts and the gallery workflow

The `convert` command produces three state/audit files alongside the output images:

- **`conversion.log`**: append-only text log, flushed after every file. Each line
  records what happened to one source file: status (converted/failed/resumed),
  any errors, warnings, and the time taken. Survives crashes and interrupts.
- **`audit_report.json`**: JSON report describing the **output tree**, not the
  invocation. Covers all files from all sessions that contributed to the tree.
  Keys are source SHA-256 values; values are the complete record for each file.
  The 1.0.0 gate reads `unexplained_failures`. Roughly 146 pixel-identical output
  pairs are expected and listed as `"expected_duplicate"`, not flagged as failures.
- **`run-state.json`**: internal resume state, keyed on source SHA-256. Persists
  between sessions; discarded if the output specs (`--archive-format`, etc.)
  change or if `--no-resume` is passed. A killed run costs only the file in
  flight, not the batch.

### The QA gallery and album-dates workflow

After running `convert`, build an HTML review page with `gallery`:

```powershell
C:\venvs\fpx\Scripts\python.exe -m fpx_converter gallery
# writes <output-root>/report/index.html (output/report/index.html by default)
```

The gallery shows:
- Every converted photograph as a thumbnail decoded from its embedded DIB
  (roughly 96 px on the long edge; the exact size varies per file)
- Filterable by album and audit status (failed, warnings, no capture date,
  has a capture date); pixel-identical duplicate pairs are called out in the
  page header as a count, not as a separate filter
- Failed files outlined in red so they stand out
- Albums holding undated photographs with a date-entry box beside each one

Open `output/report/index.html` in a browser, enter dates you know in YYYY-MM-DD format,
and save the JSON it generates as `album-dates.json` (placed beside the manifest by default).
Then re-run `convert`:

```powershell
C:\venvs\fpx\Scripts\python.exe -m fpx_converter convert
```

The `convert` command reads `album-dates.json` and writes every date you supplied
to `DateTimeOriginal` with `date_source: owner-supplied`. A date you enter only
reaches EXIF if it is a single day in YYYY-MM-DD format; anything coarser is
refused so a date claim is either defensible or not written at all.

## Test fixtures and coverage

The test suite runs on 40 committed person-free `.fpx` files (4 Kodak stock
samples plus 36 adopted from the archive, all confirmed person-free by eye
and renamed to neutral stems). The fixtures cover:

- Both colour spaces (NIF RGB and PhotoYCC)
- Six of the seven declared image sizes
- One viewing-transform crop (axis-aligned; the only archive-derived one to be committed)
- Nine nearly-identical time-lapse frames (dedup key exercise)
- Fine detail and saturated colours (chroma oracle exercise)
- Camera-generated filenames (naming collision handling)

**Coverage gaps:** Rotation has no fixture — all 22 rotated files in the
archive contain people and cannot be committed. Tier 3 (the real corpus) is
the only automated cover for this branch, which matters because rotation was
the branch that carried the 0.4.0 defect where rotated-and-cropped files
dropped their crop. See `tests/fixtures/README.md` for the screening rule and
detailed breakdown.

## What the milestone-0 inventory found

The inventory swept all 1,265 files in the source archive before any
decoder code was written. Every starting hypothesis was checked and
several refuted. These are now settled facts; see `DECISIONS.md` for
the full reasoning and evidence.

### Capture dates: none in the corpus

The FlashPix per-picture camera-settings group (`0x25xxxxxx`, including
the spec's capture-date property `0x25000000`) is **absent from all
1,265 files**. The authoring application never wrote it. The only
timestamp present is `PIDSI_CREATE_DTM` — an **import-batch stamp**,
not a shutter time. The 1,265 files carry only 26 distinct calendar
dates; single events of ~100 photos share a single sub-hour window.

When checked against dated-folder ground truth, the import stamp fails
7 of 9 dated albums, with errors ranging from +2 days to +3 months.
One folder's contents land in the **wrong calendar year**.

**Implication:** Capture dates come from folder names plus an owner
review pass in the QA gallery, not from the file. The import stamp
goes to `DateTimeDigitized` / `xmp:CreateDate`. `DateTimeOriginal`
is written only where a date is independently defensible.

### Timestamps are local wall-clock time

The OLE FILETIMEs in the corpus hold **local wall-clock time**, not
UTC. Converting them would move ~20% of the files (those stamped
between 00:00 and 04:59) onto the **previous calendar day**.

**Implication:** Treat stored values as already-local. The home time
zone is `America/Chicago`, with per-album overrides where a folder name
implies elsewhere; that map selects the `OffsetTimeOriginal` /
`OffsetTimeDigitized` values written, and applies no conversion.

### Colour space: mostly NIF RGB, not PhotoYCC

**1,261 of 1,265 subimages are NIF RGB** (channel ids `0x00030000/1/2`).
Only 4 files in the corpus are PhotoYCC. No ICC profile exists anywhere.

**Implication:** The expensive YCC-to-sRGB colour-science step the
initial spec anticipated is not needed for the bulk of the corpus. The
handful of PhotoYCC files still need it; decoding them as RGB yields
25–28 levels of error. Detect per file; never assume corpus-wide.

### Pillow's FpxImagePlugin is broken

Run over all 1,265 files, Pillow's built-in FlashPix plugin opened
**39** and raised on **1,224**. Two files **hard-crashed the CPython
process** (access violation; heap corruption). The plugin's failures
stem from prepending the external JPEG table *including* its trailing
EOI marker, and it has no decoder for zero-length single-colour tiles.

**Implication:** The custom decoder is primary, not a fallback. The 39
successes are useful only as an out-of-process correctness oracle —
and they match the custom reconstruction exactly (0.0 mean absolute
difference).

### Viewing transforms: 22 files need 90° rotation; 70 files are cropped

Every file has a Transform stream with a spatial orientation matrix
(`0x10000003`). By the *shape of the matrix*, the corpus divides 612 identity
/ 22 rotation / 53 scale-and-translate crop. By what that resolves to — which
is a different question, because a rotation can carry a crop and a matrix
inside the classifier's 2% identity tolerance can too — it divides **609
untouched / 8 rotation only / 14 rotation-plus-crop / 56 crop**, for **70
files that resolve to a crop**.

**Implication:** A naive tile decoder will emit the rotated images sideways.
The crop is a composition somebody framed in the Kodak software; the matrix
is authoritative and present in every file.

### File quality: zero corruption

All 1,265 files are valid OLE2 compound documents with correct magic.
Zero zero-length, zero truncated, zero unreadable streams. Zero files
were cloud-storage online-only placeholders.

**Implication:** The conversion target is genuinely 100%. Any decode
failure is a pipeline bug, not media decay.

### Deduplication: 541 distinct photos in 1,265 files

The 1,265 files reduce to 687 distinct SHA-256, and 541 distinct pixel
payloads. The two source trees are not independent: by pixel hash one
is a strict superset of the other. Keying deduplication on whole-file
SHA-256 (as the approved plan specifies) will convert ~27% more output
files than strictly necessary, emitting ~146 pixel-identical output
pairs that differ only by a ~14-byte timestamp in a property stream.
This is expected and must not be reported as a fault by the audit.

## Milestone plan

The approved plan for building the converter, ticked as milestones ship.
This survives context loss; conversation memory doesn't. Current status:
0.6.0 shipped; 1.0.0–1.1.0 not yet built.

- [x] **0.1.0** — Scaffold + ingestion. Read-only source walk, hash
      cascade, `manifest.json`, copy `.fpx` into `source-files/`.
      Non-personal FPX fixtures committed.
- [x] **0.2.0** — Metadata engine. Custom property-set parser for all
      10 property sets plus 2 extension storages. Full raw sidecar dump.
      Timestamp resolution per the approved dating strategy. Folder-name
      ground-truth check as an automated gate.
- [x] **0.3.0** — Pixel decoder. Tile table at +28, per-tile JPEG
      splice / raw / single-colour fill, stitch, crop to declared size,
      per-file colour space, `0x10000003` transform (90° CCW rotation and
      crops). Thumbnail extractor as correctness and orientation oracle.
- [x] **0.4.0** — Dual output. Deflate TIFF + q95 4:4:4 JPEG, ExifTool
      writes, pyexiv2 read-back validation, filesystem mtime, naming
      scheme. Crop handling for all 70 affected files, photo-identical output
      deduplication reporting, and 36 new person-free CI fixtures for PhotoYCC
      and crop coverage.
- [x] **0.5.0 + 0.6.0** — Built and audited as one unit, shipped as 0.6.0.
      Batch engine with resume-by-hash, `conversion.log`, `audit_report.json`,
      `run-state.json`; never aborts on one bad file. Format and framing
      decoupled for independent control. QA gallery (`report/index.html`),
      thumbnails from embedded DIBs, filters by album and audit status,
      per-album date-entry interface yielding `album-dates.json` which `convert`
      reads and writes to `DateTimeOriginal`.
- [ ] **1.0.0** — Full dataset run (tier-4 unattended batch conversion) plus
      tier-4 eyeball verification for colour correctness on the PhotoYCC files.
- [ ] **1.1.0** — Desktop app (later). A GUI wrapping the CLI. Ships as a
      single Windows executable alongside it. Folded with PyInstaller
      packaging work.

## Key user-facing behaviours

### Dates: defensible only, with coarse-grained prefixes

There is no capture date in this corpus. The only timestamp is a Kodak
import-batch stamp, which lands in `DateTimeDigitized` / `xmp:CreateDate` on
all files. `DateTimeOriginal` is written **only** where a date is independently
defensible:

- **Day-precise folder names** (e.g. `2001-07-04/`): written as local
  midnight on that day (`OffsetTimeOriginal` carries the album's time zone;
  stored/written times are never converted to UTC — see `DECISIONS.md`).
- **Embedded film-scan dates** (2 files in the corpus): written as recorded.
- **Owner review pass** (via the QA gallery `album-dates.json` interface):
  dates you supply for whole albums are written to every photograph in them.

Coarser folder dates (a bare year, a span, a season, a month) don't populate
`DateTimeOriginal` but are still used as an ordering key. They drive the
output filename prefix and the filesystem mtime, where unknown components are
written as zeros: `2001-00-00_000000_` for a year-only folder, or
`0000-00-00_000000_` for a folder with no dateable content. This allows
chronological sorting without false precision.

The `FPX_COARSE_ALBUMS` environment variable (a JSON list of album names in
`.env`, e.g. `["christmas 1994", "summer trip"]`) demotes an album whose
folder name looks day-precise (e.g. a holiday name that could be mistaken for
a date) to its bare year only. One-way: it can remove a date claim, never add
one.

### Output tree layout: source folder names

The output directory structure follows the source archive's folder names, not
timestamps. A descriptive folder name keeps its name as the album, nested under
the year if the folder name gives one (`2001/<that folder's name>/`), and sitting
beside the year folders if it does not. Only a folder whose name says nothing —
tool-generated or placeholder names in the source — is replaced by
`<year>/<year> <Month>`, and that year-month comes from the import stamp, which
is not trusted as a capture date.

A file in multiple albums is filed under the most descriptive one, which usually
gives it the best date evidence.

### Crops: full frame in archive/, cropped JPEG in sharing/

70 files carry a viewing transform that resolves to a crop — 56 axis-aligned
crops and 14 files that combine a 90° rotation with a crop. The archival TIFF
(`archive/<folder>/<name>.tif`) preserves the full frame the camera captured.
The shareable JPEG (`sharing/<folder>/<name>.jpg`) applies the crop. Either way,
the original `.fpx` file and the `.fpx.json` sidecar are copied alongside the
TIFF for reference.

The `convert` command names every file affected by a crop in its output, so you
can review them if needed.

## Documentation

| Document | Purpose |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Working notes: commands, testing tiers, milestone plan, binding project rules |
| [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) | Full requirements, with every starting hypothesis marked confirmed, partial, or refuted |
| [`DECISIONS.md`](DECISIONS.md) | Append-only decisions and hard-won lessons |
| [`docs/wiki/Home.md`](docs/wiki/Home.md) | In-repo wiki index (repo is private, so GitHub's wiki section is not used) |
| [`CHANGELOG.md`](CHANGELOG.md) | Keep-a-Changelog history |

## Release model

- The version lives only in `VERSION` (always X.Y.Z).
- Push a `vX.Y.Z` tag to trigger CI. CI verifies tag == VERSION, lints,
  tests, and creates the GitHub release — automatically a pre-release
  while 0.x.
- Releases stay pre-releases until **tier-4 full-dataset verification
  passes at 1.0.0**.
- This project publishes **no container image** and talks to **no
  external system**.

---

For more detail on the inventory findings, testing strategy, and project
rules, see [`CLAUDE.md`](CLAUDE.md) and [`DECISIONS.md`](DECISIONS.md).
