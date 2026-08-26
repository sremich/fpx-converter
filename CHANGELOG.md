# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are always
three-part X.Y.Z (bugfix +0.0.1, minor +0.1.0, major +1.0.0). On release,
move the Unreleased entries into a new version section, bump `VERSION`,
commit, then tag.

## [Unreleased]

### Added
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
  - Accurate spatial orientation transform (`0x10000003`) applying 90°
    counter-clockwise rotation to all 45 rotated instances.
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
