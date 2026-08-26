# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are always
three-part X.Y.Z (bugfix +0.0.1, minor +0.1.0, major +1.0.0). On release,
move the Unreleased entries into a new version section, bump `VERSION`,
commit, then tag.

## [Unreleased]

### Fixed
- **PhotoYCC files were being colour-converted twice and shipped solidly
  green.** The tile path called `convert("RGB")`, which runs the JFIF
  YCbCr-to-RGB transform, and then applied the PhotoYCC transform on top of
  the already-converted image; separately, both chroma axes were centred on
  156 when C1 is neutral at 156 and C2 at 137. The 2 PhotoYCC files in the
  corpus came out with channel means around `[60, 200, 20]` against a
  thumbnail averaging `[110, 105, 122]`, and **42% and 44% of their pixels
  clipped to zero** — past every automated check in the project, because the
  geometry was perfect and the thumbnail oracle folds both images to
  greyscale before correlating. Found by a new pixel-statistics pass in tier
  3. The two files now correlate 0.86–0.95 per channel with 0% clipping.
  A per-channel correlation against the same embedded DIB thumbnail is now
  part of tier 3, and *is* a colour oracle; the greyscale one never was.
- **`DateTimeOriginal` is no longer invented from a coarse folder name.** Any
  folder that parsed produced a capture date, using the first day of the
  range and the hour, minute and second of the Kodak import batch. Over the
  687 distinct files that meant 219 folder-derived capture dates, of which
  **151 had no day-precise evidence** (97 a bare year, 34 a year span, 20 a
  season) — 22% of the archive carrying a fabricated moment, precise to the
  second, in the field reserved for defensible dates. Only a day-precise
  folder name qualifies now, and it lands at midnight; 70 files carry
  `DateTimeOriginal` (68 folder days plus the 2 embedded scan dates).
  Coarse dates are kept as an explicit ordering key that drives the mtime
  and the filename prefix, where unknown components are written as zeros
  (`2001-00-00_000000_`) rather than as a plausible-looking 1 January.
- **Two photos in one album can no longer resolve to the same output file.**
  The output path had no collision handling, and files in an album usually
  share a date prefix, so the second silently overwrote the first while the
  run reported both converted. Stems are now assigned across the batch from
  the manifest, resume-stably, with a writer-level guard behind them.
- **Viewing transforms are classified instead of pattern-matched.** Only the
  90° CCW rotation was recognised; everything else fell through to an
  unrotated image, as did a `Transform` stream that failed to parse. **70 files
  resolve to a crop** (56 axis-aligned, 14 rotated-and-cropped) that was being
  discarded or incorrectly applied. `has_transform` was `True` for all 687
  files because it compared the ROI against `[0, 0, 1, 1]` instead of the
  declared aspect. The owner decision on the crops landed later this cycle —
  see Added below.
- **CI runs the ExifTool tests instead of skipping them green.** They were
  gated on a tool GitHub's Windows runners do not ship, so the "validate
  with a different tool than the one that wrote" rule ran nowhere while the
  suite reported green — and one convert test had no guard at all, so every
  commit on the 0.4.0 branch had in fact been failing CI. The workflow now
  installs ExifTool and sets `FPX_REQUIRE_EXIFTOOL`, which makes a missing
  tool a failure; a tier-1 test asserts the workflow keeps doing both.
- **14 rotated-and-cropped files were shipping rotated but uncropped.** The
  crop derivation used a closed form that was only valid for axis-aligned
  matrices; rotated matrices have the scale on the off-diagonal and the formula
  read zeros, so the code took the "this is a rotation, not a crop" branch. All
  14 are now correctly output with the crop applied, and the sidecar correctly
  records `crop_box` instead of `null`.
- **A corrupt Transform stream was read as "no transform".** `propset.parse_propset`
  reports malformed input by returning a property set carrying `errors`, not by
  raising. A caller that guarded only with `try/except` therefore treated corrupt
  input as valid-but-empty, producing byte-identical output and audit records to
  a file that genuinely had no transform. The parse error is now checked and
  raised as `DecoderError`.
- **The TIFF dimension validator was checking the wrong size.** It compared each
  TIFF against the raw declared size, which would have failed all 22 correctly
  rotated files (their TIFF is 864×1152 while the file declares 1152×864). The
  validator now checks the post-rotation size, derived from the metadata.
- **CI now requires ExifTool in the release workflow as well as the push
  workflow.** The `release.yml` verify job installs it and sets `FPX_REQUIRE_EXIFTOOL`,
  so a release is never cut on a weaker suite than an ordinary push.
- Checks that could not fail: JPEG 4:4:4 validation was skipped when the
  sampling table was unreadable, and `check-dates` always exited 0 without
  consulting its own report (it now has `--strict`).
- The sidecar dropped every binary payload — including the embedded
  thumbnail DIB and the external JPEG tables — while describing itself as a
  complete raw property dump. Payloads up to 64 KiB are now base64 with a
  SHA-256 beside them.
- `VT_LPSTR` was decoded as latin-1 regardless of the section's `CODEPAGE`,
  which the parser read and ignored. No string in the corpus currently
  contains a byte in the range where this matters, so nothing is repaired
  today; a future one will not arrive in XMP as control characters.
- The ExifTool fallback no longer points at a hardcoded home directory, and
  `FPX_EXIFTOOL` is now read from `.env` as well as the environment.
- Album-name timezone overrides moved out of `timestamps.py` into
  `FPX_TZ_OVERRIDES` in `.env`. Album names are personal content and do not
  belong in a committed source file.
- `get_timezone_offset` raises on a zone it does not know instead of
  silently returning US Central, and no longer resolves `Pacific/Honolulu`
  to US Pacific time.
- Folder-date parsing: `2001-07-04` was read as the span 2001–2007;
  `1999-00` became 1900; winter ended on 28 February in leap years.
- Filesystem mtime no longer falls back to the moment of conversion, which
  is indistinguishable from a real date once written.
- Both outputs are tagged sRGB with an ICC profile.

### Added
- **Dual output generation engine (milestone 0.4.0).**
  - Dual writer (`fpx_converter.writer`) producing archival Deflate TIFFs
    (`archive/<album>/<name>.tif`) and shareable quality-95 4:4:4 JPEGs
    (`sharing/<album>/<name>.jpg`).
  - **Viewing-transform crops are now applied — to the shareable JPEG only.**
    Owner decision on the 70 files that resolve to a crop (56 axis-aligned,
    14 rotated-and-cropped): the archival TIFF keeps the full frame the camera
    captured, and the shareable JPEG gets the composition somebody framed in
    Kodak's software in 2002. Deriving the crop box needs `ResultAspectRatio`
    (`0x10000000`) as well as the matrix — without it the box appears to fall
    outside the image; see `DECISIONS.md` for the geometry. The crop box is in
    the *output* image's coordinates (after rotation) and is recorded in the
    `.fpx.json` sidecar, independent of the writer, so an audit can check what
    was cut without re-deriving it.
  - Strict preservation layout: copies original `.fpx` files and `.fpx.json`
    sidecars alongside the `.tif` in `archive/<album>/`.
  - Comprehensive metadata embedding via ExifTool subprocess: writes EXIF, XMP,
    and IPTC tags (`Make`, `Model`, `Software`, `CreateDate`/`DateTimeDigitized`,
    `OffsetTimeDigitized`, `DateTimeOriginal` [defensible dates only],
    `OffsetTimeOriginal`, `Keywords`/`Subject`, and human-authored `Title`/`Description`).
  - Independent validation engine (`fpx_converter.validator`): reads back every
    written TIFF and JPEG with `pyexiv2` to prove tag survival, matching dimensions,
    TIFF Deflate compression, JPEG 4:4:4 chroma, and strict absence of
    `DateTimeOriginal` on undated photos.
  - Correct filesystem `mtime` setting: updates modified timestamps of all 4 files
    to the local `DateTimeOriginal` (or import timestamp) for automatic file-manager
    chronological sorting.
  - Standard naming scheme: `<album>/<YYYY-MM-DD_HHMMSS>_<preferred_name>.<ext>`,
    with flagged `0000-00-00_000000_` prefix for undated files.
  - CLI subcommand `convert` supporting `--manifest`, `--store`, `--dest`,
    `--limit`, and `--dry-run` with write-outside-source containment guard.
  - 15 new tests across tier-1 unit tests, tier-2 e2e fixture generation and
    pyexiv2 readback, and CLI convert tests for the initial dual-output
    engine (182 → 197), plus further tests added alongside the audit fixes
    above and the crop-application work below. The suite now stands at
    **280 tests**, all of which run in CI (locally, one skips: the guard
    that fails when `FPX_REQUIRE_EXIFTOOL` is set without ExifTool present).
  - Tier 3 is now a committed script (`scripts/tier3_sample.py`) rather than
    a run performed by hand, and it exits non-zero on any failure. Run
    against the released commit: a 50-file sample spanning **all 16 albums,
    all 7 declared sizes, both colour spaces and all four transform
    outcomes** — the corpus divides 609 untouched / 8 rotation only / 14
    rotation-plus-crop / 56 crop. 50/50 converted with 0 warnings, and an
    independent pyexiv2 pass over both containers found 0 violations —
    dimensions, Deflate, 4:4:4, ICC, tags, mtime, and no `DateTimeOriginal`
    on any file the filename marks undated. Crop geometry: 9 of 9 cropped
    files in the sample improved against the greyscale thumbnail oracle, and
    70 of 70 across the whole corpus (mean +0.56, min +0.18, worst post-crop
    correlation 0.981). Colour: worst per-channel correlation with the
    embedded thumbnail 0.860, no image clipped further than its own
    thumbnail, none near-flat.
- **Pixel decoder engine (milestone 0.3.0).**
  - Pure-Python FlashPix multi-resolution tile decoder (`fpx_converter.decoder`)
    bypassing Pillow's crash-prone `FpxImagePlugin`.
  - Reconstructs resolution pyramids tile-by-tile, supporting all 3 tile types:
    abbreviated JPEG with external table splicing (`table[:-2] + tile[2:]`),
    raw 12,288-byte uncompressed RGB ($64 \times 64 \times 3$), and 0-byte
    single-colour fill tiles from subtype colour payloads.
  - Correctly implements the **+28-byte preamble offset rule** for
    `Subimage 0000 Data` streams.
  - Per-file colour space detection and conversion: NIF RGB (standard sRGB) and
    PhotoYCC (using FlashPix/PhotoCD transformation matrix).
  - Spatial orientation transform (`0x10000003`): the 90° counter-clockwise
    rotation is applied to all 22 rotated files. The crop/zoom form of the
    same property is classified and reported; whether to apply it was an
    open owner decision at the time — see Added below for how it was
    resolved this cycle.
  - Boundary padding crop to declared subimage width and height.
  - Embedded DIB thumbnail extractor (`fpx_converter.thumbnail`) decoding 24-bit
    CF_DIB data from root `\x05SummaryInformation` PID 17 as an independent
    orientation and correctness oracle.
  - Image Pearson correlation oracle function (`compute_image_correlation`)
    operating on normalized greyscale vectors.
  - CLI subcommand `thumbnail` to extract embedded thumbnails as PNGs with
    containment enforcement.
  - 23 new tests (182 total) covering tile header parsing, JPEG splicing,
    raw/fill tiles, 90° CCW rotation, PhotoYCC conversion, thumbnail extraction,
    e2e decode across all 4 committed Kodak fixtures, and an out-of-process
    Pillow oracle comparison.
- **Metadata extraction engine (milestone 0.2.0).**
  - Custom OLE property-set parser (`fpx_converter.propset`) decoding all 10
    FlashPix property sets, extension storages (`viewprmlog` edit log and Kodak
    pedigree), and composite types (`VT_VARIANT`, `VT_VECTOR`, `VT_CF`,
    `VT_BLOB`, `VT_FILETIME`, strings, and numerics) with typed error reporting.
  - Closed the `VT_VARIANT` parser gap for `ImageInfo` PID `0x29000000` (film
    extension composite on film scan files).
  - High-level metadata extractor (`fpx_converter.metadata`) deriving declared
    image dimensions across resolution pyramids, colour spaces (NIF RGB vs
    PhotoYCC), viewing transforms (orientation matrix, aspect ratio, ROI,
    90° CCW rotation detection), camera identity, scanner acquisition data,
    IPTC keywords, and human-authored captions.
  - Complete raw JSON sidecar writer emitting `.fpx.json` sidecar dumps for
    every manifest entry, preserving every property, ID, type, raw value, and
    decoded value.
  - Timestamp resolution (`fpx_converter.timestamps`) strictly following dating
    rules: import-batch stamp (`PIDSI_CREATE_DTM`) maps to `DateTimeDigitized`
    only (never `DateTimeOriginal`); FILETIMEs treated as local wall-clock
    time without UTC conversion; timezone offsets (`OffsetTime*`) selected via
    offline US DST calculation with per-album overrides.
  - Defensible `DateTimeOriginal` populated only from folder ground truth,
    embedded scan date, or owner review, with date provenance recorded per file.
  - Automated album folder ground-truth date comparison gate
    (`fpx_converter.timestamps.check_manifest_ground_truth` and `check-dates`
    CLI command) reporting pass/fail/marginal status per album without silently
    modifying date sources.
  - CLI commands `metadata` (dump sidecars with containment guard) and
    `check-dates` (ground-truth date report).
  - 48 new tests (159 total): tier-1 property-set unit tests over hand-built
    bytes, timestamp/DST/gate tests, metadata schema tests, and tier-2 e2e
    fixture tests over all 4 committed Kodak stock sample files.

## [0.1.0] - 2026-08-26

### Added
- **Source ingestion.** `fpx_converter` package with a CLI:
  `python -m fpx_converter scan | ingest | verify`.
  - `scan` walks the source archive read-only, hashes every `.fpx`
    (case-insensitively), inventories each file's OLE2 streams, and writes
    `source-files/manifest.json` keyed on whole-file SHA-256. It records
    every source path, album, and tree a given file appeared under, so
    collapsing duplicates loses nothing.
  - `ingest` copies one file per distinct hash into `source-files/fpx/`,
    re-hashing each copy against the manifest and skipping work already
    done, so an interrupted run resumes for free.
  - `verify` re-hashes the whole store against the manifest.
- The read-only promise is **proven** rather than asserted: `scan` snapshots
  size and mtime before opening anything, re-compares afterwards, and
  re-hashes a random sample — the check that would catch a write which
  restored both.
- Filename selection preserves the only human-authored content in the
  archive. When several paths share a hash, the human-authored name wins
  over a camera-generated one; ties break deterministically so traversal
  order never decides which caption survives.
- Four Kodak stock fixtures under `tests/fixtures/` (no identifiable
  person appears in any of them) plus tier-2 tests covering real FlashPix structure, resume,
  corrupted-copy replacement, and duplicate collapse.
- 111 tests: 101 tier-1 (no photos, no filesystem beyond `tmp_path`) and 10
  tier-2 over the committed fixtures.
- Writes are refused anywhere inside the source root. `--manifest` and
  `--dest` are both checked, in the CLI and again at the one function that
  copies file content, so a mistyped flag cannot target the archive.
- `scan` records its verification result *in* the manifest, and `ingest`
  refuses a manifest whose scan could not prove the source unchanged
  (`--allow-unverified` overrides deliberately).
- `workflow_dispatch` on the CI workflow, so a run can be triggered against
  an existing commit.

- Project scaffolding from `project-scaffold`.
- `DECISIONS.md`: milestone-0 inventory findings from a read-only spike over
  the full source corpus — FlashPix tile layout, external JPEG table
  splicing, colour space, viewing-transform orientation, embedded thumbnail
  format, deduplication analysis, and the environment constraints.
- `requirements.txt` / `requirements-dev.txt`: exact pins for the runtime
  (olefile, numpy, Pillow, pyexiv2) and the dev toolchain (pytest, ruff).
  Every pin publishes a cp314 Windows wheel.
- `pyproject.toml`: pytest and ruff configuration, with the package version
  declared dynamic so it is read from `VERSION` rather than duplicated.
- `tests/test_environment.py`: tier-1 guards — `VERSION` is three-part, no
  second source of truth for it, the runtime dependencies import (pyexiv2 is
  a compiled extension), installed versions match the pins, and no personal
  media is tracked in git.
- `CLAUDE.md`: working notes — commands, the four testing tiers, the
  approved milestone plan, and the binding project rules the inventory paid
  for.
- `docs/REQUIREMENTS.md`: public-safe copy of the initial prompt, with every
  starting hypothesis marked confirmed, partial, or refuted.
- `docs/wiki/Home.md` and `docs/wiki/Release-History.md`: in-repo wiki
  (the repo is private, so GitHub's wiki section is not used).
### Fixed
- The read-only proof no longer samples the same files forever. It used a
  fixed seed over a sorted list, so every run re-hashed an identical ~2% of
  the archive while looking like sampling; the sample is now unseeded and
  the files it checked are recorded in the manifest.
- The read-only proof now re-walks the whole tree, so a file *added* to the
  archive is caught. Previously only files present at snapshot time were
  compared, and creating a file is a write.
- Two distinct SHA-256 values could be assigned the same store filename when
  a source file was itself named `<stem>_<8 hex>.fpx`, which would have let
  `ingest` overwrite one photo with another. Names now disambiguate until
  genuinely free.
- Camera-name detection no longer guesses at prefixes this archive does not
  contain (`IMG`, `DSC`, `PICT`, ...). Only `DCP` and `P` forms occur here,
  and a false positive discards a human-authored caption permanently.
- `--source` no longer requires a populated `.env`.
- `--resample 0` no longer reports the source verified while re-hashing
  nothing; negative values are rejected rather than raising a traceback.
- `--version` no longer falls back to a hardcoded `0.0.0` for an installed
  copy with no `VERSION` file beside it.

### Changed
- CI now runs on `windows-latest` with Python 3.14, installs the pinned
  dependencies, and runs ruff plus the tier-1 test suite. It was previously
  an ubuntu job that only warned when no test command was configured.
- `release.yml` mirrors that toolchain in its verify job.
- `.env.example`: the project's real variables (source root, output root,
  ExifTool path, default time zone and per-album overrides, log level,
  worker count) with placeholder values only.
- `.claude/settings.json`: allowlist matched to the actual toolchain.

### Removed
- `Dockerfile` and `docker-compose.yml`, and the GHCR build/push/smoke-pull
  jobs from `release.yml`. This project ships no container — the scaffold's
  container path is deleted rather than left as a dead stub, so
  `release.yml` now goes verify → GitHub release.
- The consumed scaffold pieces: `templates/` (the skeletons now live as the
  filled root `CLAUDE.md`, `DECISIONS.md`, and `HANDOVER.md`),
  `initial-prompt-template.md` (its content lives on as the gitignored
  `source-files/initial-prompt.md` and the public-safe
  `docs/REQUIREMENTS.md`), and the single-use `/milestone-0` skill. All
  three still carried the scaffold marker that `release.yml` refuses to
  release past.
