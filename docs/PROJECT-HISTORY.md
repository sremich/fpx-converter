# Project history

**Nobody needs to read this to use the tool.** It is the record of how
fpx-converter came to be what it is: the original requirements, what the
corpus turned out to contain, what each milestone shipped, and what was
verified at each release.

It exists because most of the surprising decisions in this codebase were paid
for by something that went wrong, and a decision without its history gets
reversed by the next person who finds it inconvenient. For the *conclusions* in
usable form, read `ARCHITECTURE.md`, `docs/FORMAT.md`, `docs/DATES.md` and
`docs/TESTING.md` instead — those are maintained; this one is a record.

---

## 1. Where it started

A personal family photo collection shot around 2000–2002 on a Kodak DC200/DC210
digital camera and managed with Kodak Picture Easy software: roughly 1,265
`.fpx` (FlashPix) files spread across old CD and DVD backups, covering
irreplaceable events. The capture date of each photograph mattered as much as
the pixels.

The situation that motivated the project:

1. Modern operating systems and photo applications cannot open `.fpx` at all.
2. Every converter tried failed in one of four ways: the output rendered as a
   black rectangle; the tool was 32-bit only and would not run on 64-bit
   Windows 11; a trial tool watermarked the output; or — in every case — the
   embedded metadata was silently discarded. Without a capture date,
   chronological sorting in a modern photo application is meaningless.
3. A previous investigation had produced technical notes about the format.
   Those were treated as hypotheses to be verified, not as facts — which turned
   out to matter a great deal.

The deliverable: a 64-bit pipeline that batch-converts every `.fpx` into a
lossless archival derivative and a shareable JPEG, with all recoverable
metadata translated into standard EXIF/XMP/IPTC tags and a complete sidecar
dump.

**The founding constraint, then and now:** the original `.fpx` files are the
archive; everything the tool produces is a derivative; nothing in the project
may modify, move or delete a source file.

### Non-goals, stated up front

- Modifying anything under the source backup. All access is read-only.
- Authoring `.fpx` files as a product feature (test-only fixtures excepted).
- Coefficient-level lossless JPEG re-muxing of tiles into a single JPEG —
  possible in principle, not worth it at this resolution. Parked.
- Any web service, multi-user, or cloud component.
- Committing any personal image, sidecar, or source data to git, ever.

---

## 2. Milestone 0: the inventory that refuted the premise

Before any decoder code was written, three read-only sweeps measured all 1,265
files against the starting hypotheses. Several of the most load-bearing ones
were **refuted**, and the project would have been built wrong without that pass.

### What was confirmed

- `.fpx` is an OLE2 compound document with a resolution pyramid; the highest
  index is full resolution.
- Tiles are uncompressed, single-colour fill, or abbreviated JPEG — **with two
  corrections the original notes did not have**: tile offsets are relative to
  byte 28 of the Data stream, and the JPEG table id is chosen *per tile*, not
  per file.
- Viewing transforms are real. Identity on most files, scale-plus-translate on
  about a hundred, and a genuine 90° counter-clockwise rotation on 22 distinct
  images. A naive tile decoder emits those sideways.
- Never hardcode 1152×864 — 19 files are a different size, including two
  natively portrait.
- `olefile.getproperties()` does not handle every FlashPix type; a custom
  property-set parser was required, covering all 10 property sets and the 2
  extension storages found.

### What was refuted

- **The colour space is NIF RGB, not PhotoYCC** — 1,261 of 1,265 files. The
  expensive colour-science work everyone budgets for was mostly not there. That
  budget moved to the viewing-transform work, which turned out to be real. But
  *small is not the same as safe*: the handful of PhotoYCC files went on to
  cause the worst defect in the project's history.
- **Pillow's `FpxImagePlugin` cannot be the pixel path.** It opened 39 files,
  raised on 1,224, and **hard-crashed CPython on 2**.
- **There is no capture date in this corpus** — the project's central premise.
  The FlashPix capture-date property and the entire per-picture settings group
  are absent from all 1,265 files. Picture Easy never wrote them. There is no
  exposure time, f-number, focal length, flash or ISO to map either. The only
  timestamp is an **import-batch stamp**: 1,265 files carry just 26 distinct
  calendar dates.
- **The stored FILETIMEs are local wall-clock time, not UTC.** Converting them
  would roll the 20% of files stamped between midnight and 05:00 onto the
  previous calendar day.
- **The import stamp fails the ground-truth check.** Album folder names encode
  dates, and against them the import stamp disagrees on 7 of 9 dated albums,
  including one by a whole year.

### Corpus statistics

| Measure | Value |
|---|---|
| Files scanned | 1,265 |
| Distinct whole-file SHA-256 | 687 |
| Distinct non-volatile-stream hashes | 666 |
| Distinct pixel payloads | 541 |
| Corrupt or truncated files | **0** — no bit rot to report |
| Files with an embedded thumbnail | 1,265 of 1,265 |
| NIF RGB / PhotoYCC | 1,261 / 4 |
| Human-authored filenames | about 17% |
| Camera make and model present | 1,187 files |
| Audio streams | **0** — the audio-extraction want was closed, not deferred |
| Total output at the chosen dedup key | ~2.4 GB, 687 outputs |

The two source trees were not independent: by pixel hash, one was a strict
superset of the other. One large archive file in the tree contained no unique
content whatsoever, and no `.fpx` existed only inside a zip.

The dedup key was an owner decision taken against the analysis recommendation:
**whole-file SHA-256** rather than pixel hash, converting about 27% more images
than strictly necessary and producing pixel-identical output pairs on purpose.
The 1.0.0 run replaced the "roughly 146 pairs" estimate with a measurement:
251 files in 120 groups.

---

## 3. The milestone record

| Milestone | What it delivered |
|---|---|
| **0.1.0** — Scaffold and ingestion | Read-only source walk, hash cascade, `manifest.json`, the `.fpx` copy into a deduplicated store. Non-personal fixtures committed |
| **0.2.0** — Metadata engine | Custom property-set parser for all 10 property sets plus 2 extension storages; full raw sidecar dump; timestamp resolution; the folder-name ground-truth check |
| **0.3.0** — Pixel decoder | Tile table, per-tile JPEG splice / raw / single-colour fill, stitch, crop to declared size, per-file colour space, the `0x10000003` transform. The thumbnail extractor earned its keep twice, confirming both the rotation and the crop geometry |
| **0.4.0** — Dual output | Deflate TIFF plus quality-95 4:4:4 JPEG, ExifTool writes, independent read-back validation, filesystem mtime, naming scheme |
| **0.5.0** — Batch engine and audit | CLI with resume-by-hash, `conversion.log`, `audit_report.json`, `run-state.json`; never aborts the run on one bad file. Output format and framing decoupled |
| **0.6.0** — QA gallery | `report/index.html`, thumbnails free from the embedded DIBs, filters by album and audit status, **plus the per-group date-entry affordance the dating strategy requires** |
| **1.0.0** — Full dataset run | The whole archive in one unattended pass |
| **1.1.0** — Desktop app | A GUI for somebody who does not use a terminal, shipped as one Windows executable. It wraps the CLI rather than reimplementing it |
| **1.2.0** — Names, folders, and what a run writes | User-definable filenames and folder arrangements; the source copy and sidecar became opt-in; the app's six output controls became three exclusive choices |
| **1.2.1** — Window and Custom fixes | The window sizes from its layout; Custom stopped asking a question it had already asked |

Two wants changed after milestone 0 measured the corpus. The **audio-extraction
want was closed** (zero audio streams exist in any file), and the colour-science
milestone shrank, with that budget moving to the viewing transform.

0.4.0, 0.5.0 and 0.6.0 were each shipped as combined pre-releases: they were
built as branch stacks and audited afterwards, so the intermediate states were
never CI-green and were never released.

---

## 4. Per-release verification log

Everything before 1.0.0 was a pre-release that had not been verified against the
full dataset. 1.0.0 onwards are full releases. See `CHANGELOG.md` for the
itemised change list, and `docs/TESTING.md` for what the tiers are.

**A note on the read-back tool.** Through 1.2.1 the independent metadata
read-back used `pyexiv2`, and the entries below are historically accurate on
that point. It was later removed from the shipped package — `pyexiv2` is GPL-3.0
and bundles a GPL-2.0-or-later `exiv2.dll`, which would relicense the Windows
executable — and replaced by Pillow with `defusedxml`. `pyexiv2` remains a
development-only dependency where tiers 2 and 3 use it as a third opinion. The
binding rule is unchanged: validate with a different tool than the one that
wrote.

### 0.1.0 (pre-release)

Source ingestion complete: a read-only scan walks every `.fpx`, builds a
SHA-256-keyed manifest, and copies one file per distinct hash to a local store
with verification. Filename selection preserves human-authored content.

Trustworthy for: building and verifying the manifest; confirming zero
corruption across 1,265 valid OLE2 documents; producing a local read-only copy.
Nothing else existed yet. Tiers 1 and 2 passing.

### 0.4.0 (pre-release)

The full conversion pipeline in one release: metadata engine, pixel decoder,
and the dual-output writer with ExifTool embedding and independent validation.

Trustworthy for: a 50-file sample spanning every album, all 7 declared sizes,
both colour spaces and all four transform outcomes; metadata preservation into
standard tags; verified geometry for the 90° rotation including the 14
rotated-and-cropped files; defensible date assignment; the crop handling on all
70 affected files, verified against the thumbnail oracle (70 of 70 improved,
worst correlation 0.981).

**Explicitly not trustworthy for colour on the PhotoYCC files** — that check was
deferred to tier 4, and the caution was justified. Shipped after three audit
rounds; the third found that the colour check added by the second could not
detect colour.

### 0.6.0 (pre-release)

Combines the 0.5.0 batch engine (resume-by-hash, audit reporting, never stops
on one bad file) with the 0.6.0 QA gallery and its per-album date entry. Output
format and framing became independent settings. The output tree started
following source folder names rather than deriving album structure from
timestamps.

Trustworthy for: unattended batch conversion with resumption keyed on source
SHA-256; correct handling of the expected pixel-identical output pairs;
independent control of both trees' format and framing; complete audit
reporting; folder-name-based album organisation preferring the most descriptive
folder (which fixed a regression affecting 52 photographs); day-precise-only
date entry. Tiers 1, 2 and 3 passing; tier 4 not yet reached.

### 1.0.0 (release)

The whole archive converted in one unattended pass: **687 converted, 0 failed,
0 with warnings, `complete: true`, `unexplained_failures: 0`, in 641 seconds.**

Every predicted number matched what the run produced — 70 cropped outputs,
609/56/22 transform outcomes, 617/68/2 date sources — and the pixel-identical
estimate was replaced by the measurement of 251 files in 120 groups, reported
as expected duplicates and not as faults.

Shipped on the automated gate with the **tier-4 eyeball half outstanding**, by
a deliberate decision: it had gated releases until this one, and rather than
keep a rule the releases were stepping over, the rule was removed knowingly.

### 1.1.0 (release)

A desktop application shipped as one standalone Windows executable — no Python,
no `pip`, no terminal. Folder pickers, output controls, a progress bar following
the real per-file trail, a log pane, and a plain-language summary read back from
`audit_report.json`. New CLI hooks a front end needs: `convert --progress` and
`convert --stop-file PATH`.

Trustworthy for: converting an archive without a terminal on a machine with
nothing installed but ExifTool; cancelling a run and still getting an audit
report; the read-only rule reaching the front end as a *call* to
`config.ensure_outside_source` rather than a second copy of the check.

The release workflow builds the executable and **converts fixtures through it**
before creating the release — a `--version` call cannot see a missing binary
dependency, and a build that fails must not leave a published release with
nothing in it. Cancellation needed two mechanisms rather than one. Two full
adversarial audit rounds, 19 findings, all closed.

### 1.2.0 (release)

The first release driven by somebody running the packaged application rather
than the test suite, and it shows in what it fixes: ExifTool no longer opens a
console window per photograph (a 687-file run flashed 687 of them), and the
dropdown menus became readable.

Three changes to what a run does. A conversion writes only the images asked for
— the `.fpx` copy and the sidecar became opt-in, where before every photograph
produced four files. The app offers three exclusive choices instead of two
checkboxes and four menus. And both output folders and filenames became
user-definable, with a live two-photograph preview built by calling the same
function the conversion calls.

The default filename was verified byte-for-byte against the old expression over
all 687 manifest entries and a set of deliberately awkward names. Pre-release
audit found two real bugs — adding `--source-copy` to a finished destination
wrote nothing, and a new trailing-character strip changed the default filename
— both fixed before the tag.

### 1.2.1 (release)

Two fixes to things a person meets before the converter has done anything. The
window had opened too small to read: a minimum size that was right for the
sections 1.1.0 had was silently wrong once 1.2.0 added a card. The size now
comes from the layout, measured at the width the window will actually have, and
the contents sit in a scroll area. Custom stopped offering a further choice
between archive and shareable — which is the choice directly above it — and all
three modes now write one image, filed by **framing** rather than by mode. The
executable carries its version in its filename.

No conversion logic changed. The new sizing is covered by tests that state the
screen rather than inherit the headless one: the offscreen platform reports
800×800, and the first version of those tests could not have failed in CI.

### After 1.2.1 — the eyeball pass

**Tier 4's second half was done.** The converted photographs were opened in a
real photo application and checked for colour, orientation and date by eye. It
passed. Every tier this project defines has now passed on the reference corpus.

It had stopped being a release gate at 1.0.0 — deliberately — and that decision
was about the *gate*, never about the *check*. The check mattered here more than
in most projects: two PhotoYCC files had shipped solidly green with 42% of their
pixels clipped to zero, past every automated check the project had at the time,
and what finally caught that class of fault was looking at it.

**The pass is of the output as it stood at 1.2.1, not a permanent property of
the code.** Any change to the decoder, the colour conversion, or the viewing
transform puts it back to outstanding — and the PhotoYCC files are the ones to
look at, not a random sample.

### Preparing to open-source

Before the repository went public, every committed fixture was reviewed again
at full resolution. That review found a figure standing behind foliage in the
background of three of them, and all three were deleted — including the only
fixture in the repository that carried a viewing-transform crop, which left
that branch with no CI cover at all.

There is a second lesson recorded alongside it. An earlier note in the fixtures
README had described a detail in two of those files, reasoned about it, and
concluded it was acceptable. That written observation was also simply wrong
about what was in the picture. **A written observation about a photograph is
not the photograph. Re-look; do not re-read.**

---

## 5. Things that were tried and rejected

Kept because "why didn't they just…" is a question worth answering once.

- **Writing the import stamp to `DateTimeOriginal`.** Rejected as knowingly
  false: it puts one folder's photographs in the wrong calendar year while
  looking authoritative.
- **Automated folder parsing alone.** Rejected as leaving most of the corpus
  undated.
- **Writing no `DateTimeOriginal` at all.** Rejected because chronological
  sorting in a photo application is the whole point of the exercise. The
  resolution was folder-derived dates *plus* an owner review pass — which made
  the review pass a product requirement rather than a nice-to-have.
- **Taking the start of a date range.** Implemented, shipped, and removed: it
  gave 151 of 687 files a fabricated capture moment precise to the second.
- **`piexif` as the metadata writer.** Excluded — no XMP or IPTC support.
- **LZW TIFF compression.** Deflate instead, for better ratios without the
  legacy compatibility quirks.
- **Per-channel Pearson correlation as a colour check.** Written, shipped, and
  caught. Correlation is invariant under any per-channel affine map, so it
  passed a wrong neutral point, a full desaturation, and a red/blue swap.
- **Reading a scale and translation off the transform matrix.** Only valid for
  an axis-aligned matrix; it silently dropped the crop on 14 rotated files.
- **Deriving the album from the first folder listed.** Put 52 photographs of
  one holiday under a folder named after a zip file, and cost them the
  day-precise date their real album gave for free.
- **One shared date vocabulary for folders and filenames.** A custom
  `{year}/{album}` filed almost everything under `0000/` while
  `--folder-scheme year` — the same word — correctly said `2002/`.
