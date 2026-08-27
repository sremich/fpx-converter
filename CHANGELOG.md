# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are always
three-part X.Y.Z (bugfix +0.0.1, minor +0.1.0, major +1.0.0). On release,
move the Unreleased entries into a new version section, bump `VERSION`,
commit, then tag.

## [1.1.0] — 2026-08-27

### Added
- **A desktop app, shipped as one standalone Windows executable.** Download
  `fpx-converter.exe` from the release and run it — no Python, no `pip`, no
  terminal. Two folder pickers, per-tree format and framing menus, Convert and
  Cancel, a progress bar that follows the real per-file trail, a log pane, and
  a plain-language summary at the end read back from `audit_report.json`.
  ExifTool remains the one prerequisite that is not bundled.
- **It wraps the CLI; it never reimplements it.** Every conversion the window
  starts is `fpx_converter` running as a child process with the arguments a
  person would have typed. Nothing in `fpx_gui` decodes a pixel, writes a tag
  or decides where a file lands, and the read-only rule reaches it as a *call*
  to `config.ensure_outside_source` rather than a second implementation.
  Replace that call with a local copy of the same check and exactly two tests
  fail — a number measured by mutation rather than asserted.
- **`convert --progress`.** Mirrors each per-file log line onto stdout. The
  trail had only ever gone to `conversion.log`, so anything watching a
  687-file run — a front end, or a person — saw a header, eleven minutes of
  silence, and a summary. Opt-in, so no existing command line changes what it
  prints.
- **`convert --stop-file PATH`.** Stops a run at the next photo boundary and
  still writes the audit report. A marker is honoured only if it is newer than
  the run itself, so one left behind cannot cancel a later run, and one that
  cannot be deleted cannot wedge a destination.
- **`batch.interrupt_on_break()`.** Maps Ctrl+Break onto `KeyboardInterrupt`,
  installed by the entry points. Everything the batch engine does to survive an
  interruption hangs off that exception, and on Windows only `CTRL_C_EVENT`
  raises it by default.
- **CI builds the executable and exercises it.** The release workflow builds
  the exe, checks it carries `VERSION`, and **converts two fixtures through
  it** before the release is created — a `--version` call cannot see a missing
  `pyexiv2` binary or Pillow plugin, and a real conversion can. A second CI
  job installs `requirements-gui.txt` so the widget tests run somewhere
  instead of skipping in every job.

### Fixed
- **`--stop-file` could delete a file inside the read-only source archive.**
  It was the only path argument `convert` accepts that did not go through
  `ensure_outside_source`, and both its uses are deletes. A stop file inside
  the archive destroyed that photograph while the run reported success, and
  `scan`'s `verify_unchanged` could not catch it because that check belongs to
  an earlier command. Found in audit, before any release carried it.
- **A failing progress callback killed the run and lost the audit report.**
  Those log writes sit outside the per-file `except` that turns one bad file
  into a line in the report, so a closed pipe escaped the loop entirely.
  Reachable by killing the window from Task Manager mid-run. A dead reader now
  costs the trail and never the run — and only a terminal failure (`OSError`)
  drops the echo for good, because one filename a console cannot encode should
  not cost the progress display for the remaining 686.
- **The window could report a previous run's audit report as this run's
  success**, announcing a clean finish to the audience least able to check.
- **Cancel froze the window for up to the full grace period.** A window that
  stops repainting reads as a crash, and the remedy people reach for is Task
  Manager — which is the one ending that leaves no audit report. The freeze
  was therefore a direct cause of the outcome the cancellation design exists
  to prevent.
- **A cancel that outlasted its timeout was reported as a clean finish.** The
  timeout was five seconds shorter than the operation's own worst case, so the
  one ending it existed to classify was the one it could time out on. It is
  now derived from that worst case rather than guessed at.

### Changed
- The release workflow builds the executable **before** creating the release.
  It used to run after, so a failed build left a published release whose whole
  point was missing — and the same version cannot be re-tagged to fix that.

## [1.0.0] — 2026-08-27

### Verified
- **The whole archive converted, unattended, clean.** 687 distinct files
  (1,265 including duplicates) in 641 seconds: 687 converted, 0 failed, 0 with
  warnings, `complete: true`, `unexplained_failures: 0`. This is the run the
  1.0.0 gate was written for, and it is the first time the tool has been asked
  to do the whole job in one go.
- Every number the milestone-0 inventory predicted came out right, which is
  the part worth trusting rather than the zero:
  - **70 cropped outputs** — the 56 axis-aligned crops plus the 14 that ride
    along with a rotation, exactly as `DECISIONS.md` says.
  - **transforms 609 identity / 56 crop / 22 rotate-90-ccw**, summing to 687.
  - **date sources 617 import-stamp / 68 folder / 2 embedded-scan-date.** No
    `DateTimeOriginal` was invented: the 617 carry a digitised date only.
  - **251 files in 120 pixel-identical groups**, reported as expected rather
    than as faults — the measured figure, replacing the estimate of "roughly
    146 pairs" that had been carried since milestone 0.
- Tier 3 re-run against the released commit: 64 pairs, 0 validator violations,
  worst chroma correlation 0.739 against a 0.5 gate, worst chroma offset +5.3
  against 30.0, 9 of 9 cropped files improved on the geometry oracle.

### Changed
- **Releases are no longer gated on the tier-4 eyeball pass.** The rule said
  every release stays a pre-release until two PhotoYCC files have been looked
  at by a person in a real photo app. That pass has not happened, and this
  release ships anyway by the owner's decision — so the claim comes out of the
  documentation rather than being left standing while releases go past it. The
  eyeball check is still the right thing to do and is still described in the
  testing tiers; it is a recommendation now, not a gate. **A 96-pixel
  thumbnail oracle is evidence, not sight**, and nothing automated in this
  project can see colour the way a person can.

## [0.6.0] — 2026-08-27

### Added
- **QA gallery (milestone 0.6.0).** `fpx-converter gallery` builds
  `report/index.html` from a completed run: every converted photograph as a
  thumbnail, filterable by album and by audit status, failures outlined. One
  self-contained file with no server, no build step and no external asset --
  thumbnails are inlined as data URIs, because it has to open by
  double-clicking it in five years' time on a machine with none of this
  installed. Thumbnails come from the embedded DIBs rather than from the
  outputs, which costs no decode and keeps the page able to disagree with
  what was written.
- **Album dates a person supplies.** The other half of the dating strategy,
  and the only route by which a capture date enters this archive from outside
  the files. The gallery shows every album holding an undated photograph and
  offers a date box; what is typed comes back out as `album-dates.json`,
  which `convert` reads on the next run (`--album-dates`) and writes to
  `DateTimeOriginal` with `date_source: owner-supplied`, ranked above the
  folder name and far above the import stamp. Somebody who was there is
  better evidence than a folder name, and better than a stamp that misses
  the event by up to 223 days. A single day or nothing: a month or a year is
  refused at parse time rather than rounded to its first day, which is the
  fabrication this project already paid for once.
- **`FPX_COARSE_ALBUMS`.** Demotes an album whose folder name looks
  day-precise to its year. A holiday name resolves to a calendar day, but a
  folder named for one may hold the whole season around it, and only the
  person who made the folder knows which. Deliberately one-way: it can take a
  date claim away, never add one.
- **Batch engine (milestone 0.5.0).** `convert` now runs the whole corpus
  unattended, survives any file corruption, and resumes from mid-run after a
  kill or crash. A run that stops at file 300 of 687 due to one corrupt tile
  now reports all failures across the corpus and can resume — before this,
  the same corruption halted the entire conversion. Resumption is keyed on the
  source SHA-256 (this project's dedup key), so a run interrupted mid-file costs
  only that file, not the batch. State is saved after every file and discarded
  if the output specs change, preventing a resumed run from writing files that
  don't match the command. Ctrl-C still writes state and the audit report before
  returning — the run is survivable mid-operation. Roughly 146 pixel-identical
  output pairs are expected and reported as such, not as faults, because dedup
  keys on the whole file so byte-different sources with identical pixels are
  both kept deliberately. See `batch.py` and `cli.py` for the implementation;
  `audit_report.json` is the artifact the 1.0.0 gate reads.
- **Output format and framing decoupled (milestone 0.5.0).** The archive tree
  and the sharing tree were welded together: archive meant full-frame Deflate
  TIFF and sharing meant cropped JPEG, with no way to ask for one without the
  other. They are now independent axes. `--archive-format` / `--archive-framing`
  and `--sharing-format` / `--sharing-framing` control each output tree
  separately. Format is `tiff` (Deflate, lossless) or `jpeg` (q95, 4:4:4).
  Framing is `full` (every captured pixel) or `cropped` (the Kodak software's
  intended composition, where a file carries one; 617 files have no crop).
  Defaults are unchanged (archive full TIFF, sharing cropped JPEG), so existing
  commands do not change. A full-frame JPEG is now possible, addressing the
  original ask for "the largest uncropped image"; it is available as
  `--sharing-framing full` or `--no-archive --sharing-format jpeg
  --sharing-framing full`. New flags `--no-archive` and `--no-sharing` suppress
  either tree.
- **`run-state.json` resume artifact.** Tracks the hash, album, status, and
  errors for every file in the batch, keyed on source SHA-256. Persists between
  sessions and is discarded if the output specs change or `--no-resume` is given.
- **`conversion.log` append-only text log.** Every event is flushed to disk
  after every file, so a killed run is recoverable without losing visibility
  into what was written.
- **36 new test fixtures, and the first CI coverage of colour.** All 687
  distinct files in the archive were screened by eye for people; the 40 that
  contain none are now committed with neutral filenames. Both PhotoYCC files
  are among them, so the colour path that once shipped two photographs
  solidly green with 42% of their pixels clipped now has tier-1/2 coverage
  that runs on every push. Also newly covered: a file carrying a
  viewing-transform crop, and six of the seven declared sizes.
- **Mutation tests for the colour oracle.** The fixtures must pass it *and* a
  deliberately broken decode must fail it — wrong PhotoYCC neutral, swapped
  red and blue, fully desaturated. Every one of those is a mutation the
  oracle's first version passed, because it correlated the channels
  separately and Pearson correlation is invariant under a per-channel affine
  map. An oracle that cannot fail is not an oracle.
- `fpx_converter/oracles.py`: the chroma check, moved out of the tier-3
  script so tiers 1, 2 and 3 share one definition instead of three that
  drift.
- `tests/fixtures/README.md`: what each fixture covers, what the set does
  **not** cover, and the screening rule.

### Changed
- **The output tree follows the source folder names, not the dates.** A
  descriptive source folder keeps its name as the album whatever date the
  photo carries, nested under the year when the name gives one
  (`2001/<that folder's name>/`) and sitting beside the year folders when it
  does not. Only a folder whose name says nothing — the tool-generated and
  placeholder names in `layout.NON_DESCRIPTIVE_ALBUMS` — is replaced by
  `<year>/<year> <Month>`, and on this corpus
  that is 42 of 687 files. That year-month can only come from the import
  stamp, which is not trusted as a capture date, so it is a browsing
  affordance like the filename prefix and never reaches EXIF.
- **`convert` flag changes.** The command now accepts `--no-resume` (default:
  resume from prior run), `--archive-format`, `--archive-framing`,
  `--sharing-format`, `--sharing-framing`, `--no-archive`, and `--no-sharing`
  to control output independently. `--limit` and `--dry-run` remain unchanged.
  `--manifest` and `--dest` continue to enforce source-outside containment.

### Fixed
- **The QA gallery ignored `--dest` when choosing where to write.** The
  default output path was computed from the repository root, so pointing
  `gallery` at a particular run put its page in a fixed `report/` beside the
  source tree instead of beside the run it describes. Two runs overwrote each
  other's page, and the page you opened could be describing a different run —
  which is the one thing a review artifact must never do. Found by running
  the command over the full corpus rather than over a fixture; every existing
  test built the page's inputs by hand and so had no opinion about the
  wiring. `tests/test_cli_gallery.py` now drives the real command, and four
  of its six tests fail against the old path.
- **A file is filed under the most descriptive album it belongs to, not the
  first one listed.** Most files belong to both an event folder and the flat
  dump they were also copied into, and the first-listed rule picked the dump.
  **52 photos of one Christmas** were filed under a folder named after a zip
  file — and because the album is also what resolves the date, they lost the
  day-precise capture date their real album gave for free. Files carrying
  `DateTimeOriginal` go from 70 to 122.
- **A year glued onto a word is now parsed.** The folder-date patterns
  required a word boundary before the year, which a name like
  `holidays2001-02` does not have, so 24 files lost the year their folder
  named. A digit in front still blocks the match, keeping camera-generated
  names like `DCP01999` out.

## [0.4.0] — 2026-08-27

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
  3. The two files now decode with 0% clipping and chroma that tracks the
  thumbnail. Tier 3 gained a colour check against the same embedded DIB —
  comparing **chroma** (`R-G`, `B-G`), not each channel separately, because
  per-channel correlation is invariant under any per-channel affine map and
  so scores a wrong gain or a wrong neutral point exactly as well as a
  correct decode. Verified by re-injecting four faults into the decoder and
  confirming the run fails on each: the double conversion, the wrong C2
  neutral, a fully desaturated decode, and red/blue swapped. It is still not
  a substitute for looking: the tier-4 eyeball at 1.0.0 stands.
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
    **287 tests**, all of which run in CI (locally, one skips: the guard
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
    correlation 0.981). Colour: worst chroma correlation with the
    embedded thumbnail 0.739 and worst chroma offset +5.3, against gates of
    0.5 and 30; no image clipped further than its own thumbnail, none
    near-flat.
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
