# Release history

One entry per release, added as part of the `/release` checklist. Each entry
says what the release contains and — more usefully — **what it is safe to be
trusted for**, because until 1.0.0 every release is a pre-release that has
not been verified against the full dataset.

See [`CHANGELOG.md`](../../CHANGELOG.md) for the itemised change list.

## Verification status

| Tier | What it proves | Passing as of |
|---|---|---|
| 1. Unit | Parsers, reassembly, timestamp and naming logic, metadata extraction, pixel decoding, metadata round-trip validation | 0.4.0 — 252 tests covering all code paths that exist |
| 2. e2e | Full pipeline over the committed non-personal fixtures | 0.4.0 — scan through convert, including pixel decoding, metadata embedding, and pyexiv2 read-back validation on both TIFF and JPEG |
| 3. Sample batch | 48 real files spanning all 16 albums, 7 declared image sizes, both colour spaces, all three transform classes, and embedded film scans | 0.4.0 — 48/48 converted, 0 failures, independent pyexiv2 pass over both containers found 0 violations |
| 4. Full dataset | Unattended run over the whole corpus, plus an eyeball pass | *not yet reached — gates 1.0.0* |

## Releases

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
- Complete batch conversion of 48-file sample spanning all albums and variants
  (tier-3 verification passed)
- Accurate metadata extraction and preservation into standard EXIF/XMP/IPTC tags
- Verified image reconstruction (checked against the embedded-thumbnail
  correlation oracle and an independent Pillow decode) with correct
  per-file colour space (NIF RGB and PhotoYCC) and viewing transforms
  (90° CCW rotation)
- Defensible date assignment: capture dates only from day-precise folder names
  or embedded film scans; import stamp on `DateTimeDigitized` universally
- Correct handling of viewing-transform crops: full frame preserved in archive
  TIFF, cropped JPEG in sharing directory

**What does NOT work:** The batch engine with resume-by-hash and audit
reporting (0.5.0), and the QA gallery with per-group date entry (0.6.0).
Full-dataset verification (1.0.0) has not been run.

**Known limitations:**
- Batch processing requires manual per-command invocation. There is no
  resume-by-hash or unattended batch run.
- The dating strategy requires a manual owner review pass for undated folders.
  The QA gallery interface for this (0.6.0) is not yet built.
- Only tier-3 (48-file sample) verification exists; tier-4 (full corpus) has
  not been run.

**Verification:** Tiers 1, 2, and 3 passing (252 tests, 48-file sample batch);
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
