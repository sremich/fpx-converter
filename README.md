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

**Version 0.1.0.** Source ingestion works. Nothing converts anything
yet — no pixel decoder, no metadata engine, no output writer. Those
arrive at 0.2.0–0.4.0.

What exists:
- **The `fpx_converter` package** with three commands: `scan`
  (walk the source archive read-only), `ingest` (copy one file per
  distinct SHA-256), and `verify` (re-hash the store against the
  manifest).
- **111 tests:** 101 tier-1 (unit tests, no photos or external tools)
  and 10 tier-2 over four committed Kodak stock fixtures.
- **CI passing on Windows** (python 3.14, `windows-latest`).

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

The three commands require a `.env` file copied from `.env.example`
(edit it to set `FPX_SOURCE_ROOT`, `FPX_OUTPUT_ROOT`, and time zone).
Alternatively, `scan` accepts `--source` to override the tree location:

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

The tier-1 gates that exist right now:

```powershell
# Lint
C:\venvs\fpx\Scripts\python.exe -m ruff check .

# Unit tests (tier 1: no real photos, no ExifTool, no source archive)
C:\venvs\fpx\Scripts\python.exe -m pytest
```

These gates run on every push to CI.

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

### Viewing transforms: 45 files need 90° rotation

Every file has a Transform stream with a spatial orientation matrix
(`0x10000003`). Across the corpus it is identity on most files,
scale+translate (crop) on ~100, and a **pure 90° counter-clockwise
rotation on 45 instances** covering 24 distinct images.

**Implication:** A naive tile decoder will emit those images sideways.
The matrix is authoritative and present in every file.

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
0.1.0 (ingestion complete).

- [x] **0.1.0** — Scaffold + ingestion. Read-only source walk, hash
      cascade, `manifest.json`, copy `.fpx` into `source-files/`.
      Non-personal FPX fixtures committed.
- [ ] **0.2.0** — Metadata engine. Custom property-set parser for all
      10 property sets plus 2 extension storages. Full raw sidecar dump.
      Timestamp resolution per the approved dating strategy. Folder-name
      ground-truth check as an automated gate.
- [ ] **0.3.0** — Pixel decoder. Tile table at +28, per-tile JPEG
      splice / raw / single-colour fill, stitch, crop to declared size,
      per-file colour space, `0x10000003` transform (90° CCW rotation and
      crops). Thumbnail extractor as correctness and orientation oracle.
- [ ] **0.4.0** — Dual output. Deflate TIFF + q95 4:4:4 JPEG, ExifTool
      writes, pyexiv2 read-back validation, filesystem mtime, naming
      scheme.
- [ ] **0.5.0** — Batch engine + audit. CLI with resume-by-hash,
      `conversion.log`, `audit_report.json`; never aborts on one bad
      file.
- [ ] **0.6.0** — QA gallery. `report/index.html`, thumbnails free from
      the embedded DIBs, filters by album and audit status, **plus the
      per-group date-entry affordance the dating strategy requires**.
- [ ] **1.0.0** — Full dataset run plus tier-4 eyeball verification.
- [ ] *later* — PyInstaller exe; re-verify 3.14 wheel support first,
      then add the build-and-attach job to `release.yml`.

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
