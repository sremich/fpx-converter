# Release history

One entry per release, added as part of the `/release` checklist. Each entry
says what the release contains and — more usefully — **what it is safe to be
trusted for**, because until 1.0.0 every release is a pre-release that has
not been verified against the full dataset.

See [`CHANGELOG.md`](../../CHANGELOG.md) for the itemised change list.

## Verification status

| Tier | What it proves | Passing as of |
|---|---|---|
| 1. Unit | Parsers, reassembly, timestamp and naming logic, batch engine, resume state, audit reporting, output control, mutation tests for colour oracle | 0.6.0 — 603 tests covering all code paths that exist |
| 2. e2e | Full pipeline over 40 committed person-free fixtures covering both colour spaces, the crop path, and six of seven declared sizes | 0.6.0 — scan through convert on both archive and sharing trees, pixel decoding with PhotoYCC coverage, metadata embedding, pyexiv2 read-back validation on both TIFF and JPEG, colour oracle mutation tests |
| 3. Sample batch | 50 real files spanning all 16 albums, all 7 declared sizes, both colour spaces, all four transform outcomes, and both embedded film scans | 0.4.0 — 50/50 converted, 0 failures, independent pyexiv2 pass over both containers found 0 violations |
| 4. Full dataset | Unattended batch run over the whole corpus with audit report, plus an eyeball pass for colour on the PhotoYCC files | *not yet reached — gates 1.0.0* |

## Releases

### 0.6.0 (pre-release)

**What it contains:** Combines two milestones built and audited as one unit:
the **0.5.0 batch engine** with resume-by-hash and audit reporting, and the
**0.6.0 QA gallery** with per-album date-entry interface. Unattended batch
conversion of the full manifest with automatic resumption from mid-run after
a crash or kill; never stops on one bad file. Output format and framing are
independent settings for the first time, enabling any combination (full-frame
JPEG, cropped TIFF, etc.). The HTML gallery shows every photograph as an
embedded thumbnail, filterable by album and audit status; missing capture dates
are collected via a form and persisted in `album-dates.json`, which `convert`
reads and writes to EXIF. Output tree now follows source folder names rather
than deriving album structure from timestamps.

**What it is safe to trust for:**
- Unattended batch conversion with automatic resumption if a run is killed or
  crashes (resumption keyed on source SHA-256; only the file in flight is retried)
- Proper handling of 146 expected pixel-identical output pairs (dedup keys on
  the whole file, so byte-different sources with identical pixels are both kept)
- Independent control of archive and sharing tree format and framing, with
  defaults unchanged (archive full-frame Deflate TIFF, sharing cropped JPEG)
- Complete audit reporting: `audit_report.json` describes the output tree across
  multiple sessions; the 1.0.0 gate reads `unexplained_failures`
- Correct folder-name-based album organization, preferring the most descriptive
  folder a file belongs to (this fixes a regression affecting 52 photos across
  multiple albums in the real corpus)
- Per-album date entry in an HTML gallery with JSON export; dates land in EXIF
  only if they are day-precise
- Tier-1/2 CI coverage of the PhotoYCC colour path and its mutation tests
- Complete conversion of a 50-file sample spanning all 16 albums, all 7 declared
  sizes, both colour spaces, and all four transform outcomes (tier-3 verification
  passed, from `scripts/tier3_sample.py`)

**What does NOT work:** Full-dataset verification (1.0.0). Full-corpus conversion
has not been run.

**Verification:** Tiers 1, 2, and 3 passing (603 tests, 40 person-free
fixtures, 50-file sample batch); tier 4 not yet reached. This is a pre-release.

### 0.4.0 (pre-release)

**What it contains:** The full conversion pipeline. Metadata extraction engine
(custom OLE property-set parser for all 10 property sets), pixel decoder
(pure-Python tile reassembly with JPEG splicing, raw RGB, and single-colour
fill support), and dual-output writer (archival Deflate TIFF + quality-95
4:4:4 JPEG, both tagged sRGB). Metadata embedding via ExifTool subprocess with
independent validation via pyexiv2. Correct filesystem mtime setting. Standard
naming scheme with date prefix and collision handling. Complete raw JSON
sidecars. Embedded DIB thumbnail extraction. Ground-truth date checking against
folder names.

**What it is safe to trust for:**
- Complete batch conversion of a 50-file sample spanning all 16 albums, all 7
  declared sizes, both colour spaces and all four transform outcomes
  (tier-3 verification passed, from `scripts/tier3_sample.py`)
- Accurate metadata extraction and preservation into standard EXIF/XMP/IPTC tags
- Verified image geometry (checked against the embedded-thumbnail correlation
  oracle, which compares greyscale only, and an independent Pillow decode)
  for the 90° CCW rotation, including the 14 rotated-and-cropped files. Per-file
  colour-space detection (NIF RGB vs PhotoYCC) is implemented and applied, but
  the 2 PhotoYCC files have not been human-verified for colour correctness —
  that eyeball check is part of the tier-4 pass at 1.0.0, not before it
- Defensible date assignment: capture dates only from day-precise folder names
  or embedded film scans; import stamp on `DateTimeDigitized` universally
- Correct handling of viewing-transform crops on all 70 affected files
  (56 axis-aligned, 14 rotated-and-cropped): full frame preserved in archive
  TIFF, cropped JPEG in sharing directory. Crops verified against embedded DIB
  thumbnail oracle (70 of 70 improved, worst correlation 0.981)

**What does NOT work:** The batch engine with resume-by-hash and audit
reporting (0.5.0), and the QA gallery with per-group date entry (0.6.0).
Full-dataset verification (1.0.0) has not been run.

**Known limitations:**
- Batch processing requires manual per-command invocation. There is no
  resume-by-hash or unattended batch run.
- The dating strategy requires a manual owner review pass for undated folders.
  The QA gallery interface for this (0.6.0) is not yet built.
- Only tier-3 (50-file sample) verification exists; tier-4 (full corpus) has
  not been run.

**Verification:** Tiers 1, 2, and 3 passing (287 tests, 50-file sample batch);
tier 4 not yet reached. This is a pre-release.

### 0.1.0 (pre-release)

**What it contains:** Source ingestion complete. A read-only scan of the
source archive walks every `.fpx` file, builds a SHA-256-keyed manifest,
and copies one file per distinct hash to a local deduplicated store with
verification. Filename selection preserves human-authored content.

**What it is safe to trust for:**
- Building and verifying a deduplicated manifest of the source archive
- Confirming zero corruption or bit rot in the corpus (1,265 files
  scanned, all valid OLE2 documents)
- Producing a local read-only copy for safe offline archival storage

**What does NOT work:** Pixel decoding, metadata extraction, TIFF/JPEG
output, the batch engine, the QA gallery, and the dating UI. Those
arrive at 0.2.0–0.6.0.

**Verification:** Tier 1 and tier 2 passing; tiers 3 and 4 not yet
reached. This is a pre-release.
