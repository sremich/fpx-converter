# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are always
three-part X.Y.Z (bugfix +0.0.1, minor +0.1.0, major +1.0.0). On release,
move the Unreleased entries into a new version section, bump `VERSION`,
commit, then tag.

## [Unreleased]

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
- Four Kodak stock fixtures under `tests/fixtures/` (no person appears in
  any of them) plus tier-2 tests covering real FlashPix structure, resume,
  corrupted-copy replacement, and duplicate collapse.
- 65 tests: 55 tier-1 (no photos, no filesystem beyond `tmp_path`) and 10
  tier-2 over the committed fixtures.
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
