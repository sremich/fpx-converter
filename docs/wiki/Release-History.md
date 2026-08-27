# Release history

One entry per release, added as part of the `/release` checklist. Each entry
says what the release contains and — more usefully — **what it is safe to be
trusted for**. Everything before 1.0.0 was a pre-release that had not been
verified against the full dataset; 1.0.0 onwards are full releases.

See [`CHANGELOG.md`](../../CHANGELOG.md) for the itemised change list.

## Verification status

| Tier | What it proves | Passing as of |
|---|---|---|
| 1. Unit | Parsers, reassembly, timestamp and naming logic, batch engine, resume state, audit reporting, output control, filename and folder patterns, the desktop front end's Qt-free half, mutation tests for the colour oracle | 1.2.1 — 834 tests, plus `scripts/mutation_check.py`, which breaks 17 load-bearing rules on purpose and requires the test named for each to go red |
| 2. e2e | Full pipeline over 40 committed person-free fixtures covering both colour spaces, the crop path, and six of seven declared sizes; the desktop front end driving a real child process, cancellation included | 1.2.1 — scan through convert on both trees, pixel decoding with PhotoYCC coverage, metadata embedding, pyexiv2 read-back on both TIFF and JPEG, colour oracle mutation tests |
| 3. Sample batch | Real files spanning every album, every declared size, both colour spaces and all four transform outcomes | 1.2.1 — 64/64 converted clean, 0 pyexiv2 violations, worst chroma correlation 0.739 against a gate of 0.5, thumbnail oracle improved on 9 of 9 cropped files |
| 4. Full dataset | Unattended batch run over the whole corpus with audit report, plus an eyeball pass for colour on the PhotoYCC files | **Both halves passed.** The batch half at 1.0.0 (687/687, `complete: true`, `unexplained_failures: 0`); the eyeball half after 1.2.1, on 2026-08-27. It had stopped being a release gate at 1.0.0 — a deliberate decision — and was done anyway |

## Releases

### 1.2.1 (release)

**What it contains:** Two fixes to things a person meets before the converter
has done anything at all.

The desktop window opened too small to read: the cards were squashed into
slivers, three radio buttons collapsed to underscores, and the naming card was
empty. `setMinimumSize(920, 760)` was right for the four sections 1.1.0 had and
silently wrong once 1.2.0 added a card, so Qt was allowed to open the window
nearly 300 pixels shorter than its contents needed. The size now comes from the
layout, measured at the width the window will actually have, and the contents
sit in a scroll area so a display too short for them scrolls rather than
squeezing them.

Custom also stopped asking a question it had no business asking. It offered a
further choice between an archive copy and a shareable one, which is the choice
directly above it, and let somebody tick neither and meet a greyed-out Convert
button. All three modes now write one image; Custom is the one where you say
which. Which folder it lands in follows the framing — `archive/` keeps the full
frame, `sharing/` gets the crop — so the same two answers reach the same place
however they were given, and the window says so under the menus. Both trees in
a single run remain a command-line thing.

And the executable carries its version — `fpx-converter-1.2.1.exe` — so two
downloads a year apart are not two files with the same name.

**What it is safe to trust for:** Everything 1.2.0 was. No conversion logic
changed: the diff is the window's geometry, which of its controls exist, some
shorter explanatory lines, and the name of the built file. The only
`fpx_converter` change is a display string the CLI never reads — the one-line
description beside a folder scheme, which only the window shows.

**What does NOT work:** The tier-4 eyeball pass, unchanged since 1.0.0.

**Verification:** Tiers 1, 2 and 3 all passing; `scripts/mutation_check.py`
green, all 16 rules caught by the test named for each. Tier 3 was run rather
than argued about: `fpx_converter/layout.py` is in the diff, and output pathing
is batch-path code even when the change is only a display string. 64/64
converted clean, 0 pyexiv2 violations, worst chroma correlation 0.739 against a
gate of 0.5. The executable was built locally and run before tagging: it reports
1.2.1, converts, and honours `--folder-scheme flat --name-template '{name}'`.
The window's new sizing is covered by tests that state the screen rather than
inherit the headless one, because the offscreen platform reports 800x800 and
the old hardcoded 760 satisfied it — the first version of those tests could not
have failed in CI.

### 1.2.0 (release)

**What it contains:** The first release driven by somebody running the packaged
application rather than the test suite, and it shows in what it fixes. ExifTool
no longer opens a console window for every photograph — a 687-file run flashed
687 of them. The desktop app's dropdown menus, which had been rendering their
text in a colour that vanished against the field, are readable.

Three changes to what a run does. A conversion now writes only the images asked
for: the `.fpx` source copy and the `.fpx.json` sidecar became `--source-copy`
and `--sidecar`, off by default, where before every photograph produced four
files. The app offers three exclusive choices — Archive copy, Shareable copy,
Custom — instead of two checkboxes and four menus, and `Start over` is gone.
And both the output folders and the filenames are now user-definable:
`--folder-scheme album|year|year-month|flat|custom` with `--folder-template`,
and `--name-template` over the fields `{year} {month} {day} {date} {time}
{name} {album}`. The window shows a live preview of two photographs — one an
album dated, one with nothing to date it — built by calling the same function
the conversion calls.

**What it is safe to trust for:**
- Everything 1.1.0 was, with the same defaults: an unchanged default filename
  (verified byte-for-byte against the old expression over all 687 manifest
  entries and over a set of deliberately awkward names) and an unchanged
  default folder layout
- Filing photographs by year, by year and month, flat, or by your own pattern,
  with output names unique by construction in every scheme
- A refusal, before a run starts, of any pattern that would lose the archive's
  filenames or put files outside the destination
- Resuming: a change to the output specs, the filename pattern, the folder
  arrangement, or a request for a file the previous run did not write all
  invalidate the resume rather than silently skipping

**What does NOT work:** The tier-4 eyeball pass on the two PhotoYCC files is
still outstanding, unchanged from 1.0.0. The console-window and dropdown fixes
are the two things in this release that no test can cover — both were found by
running the application, and confirming them needs the application run again.

**Verification:** Tiers 1, 2 and 3 passing, plus `scripts/mutation_check.py`
green over 16 mutations. Tier 3 was a trigger for this release (it touches the
output writer, the batch engine and output naming) and ran: 64 files, 64 clean,
0 pyexiv2 violations. Two bugs found by pre-release audit and fixed before the
tag: adding `--source-copy` to a finished destination wrote nothing at all, and
a new trailing-character normalisation changed the default filename for names
ending in a dot or a space.

### 1.1.0 (release)

**What it contains:** A desktop application, shipped as one standalone Windows
executable — no Python, no `pip`, no terminal. Two folder pickers, output
controls, Convert and Cancel, a progress bar following the real per-file trail,
a log pane, and a plain-language summary read back from `audit_report.json`.
It wraps the CLI rather than reimplementing it: every conversion is
`fpx_converter` running as a child process with the arguments a person would
have typed. New CLI hooks a front end needs: `convert --progress` and
`convert --stop-file PATH`.

**What it is safe to trust for:**
- Converting an archive without touching a terminal, on a machine with nothing
  installed but ExifTool
- Cancelling a run and still getting an audit report describing what was done
- The read-only source rule reaching the front end as a *call* to
  `config.ensure_outside_source`, not a second copy of the check — replace it
  with a local copy and exactly two tests fail, a count measured by mutation

**What does NOT work:** The tier-4 eyeball pass, unchanged from 1.0.0.

**Verification:** Tiers 1 and 2 passing, including the front end driving a real
child process and a cancellation that must still leave a report. The release
workflow builds the executable and **converts two fixtures through it** before
creating the release — a `--version` call cannot see a missing `pyexiv2`
binary. Two full `code-auditor` rounds, 19 findings, all closed.

### 1.0.0 (release)

**What it contains:** The whole archive converted in one unattended pass. 687
converted, 0 failed, 0 with warnings, `complete: true`,
`unexplained_failures: 0`, in 641 seconds.

**What it is safe to trust for:**
- The pipeline over a full real corpus rather than a sample. Every predicted
  number matched what the run produced: 70 cropped outputs, 609/56/22 transform
  outcomes, 617/68/2 date sources
- The pixel-identical-pairs estimate replaced by a measurement — 251 files in
  120 groups, reported as expected duplicates and not as faults

**What does NOT work:** The tier-4 eyeball pass — two PhotoYCC files opened in
a real photo application and looked at by a person. It gated releases until
this one, and rather than keep a rule the releases were stepping over, the rule
was removed deliberately. It is still worth doing, and it has still not been
done.

**Verification:** Tiers 1, 2 and 3 passing; the automated half of tier 4
passing over all 687 files. The eyeball half outstanding, knowingly.

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
