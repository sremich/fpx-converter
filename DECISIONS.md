# fpx-converter — decisions and hard-won lessons

> **Append-only.** Entries are never rewritten, reordered, or trimmed — a
> superseded decision gets a new entry pointing back, not an edit. This file
> exists because HANDOVER.md churns every session while lessons must not.
> It is **committed to the repo** so decisions survive into clones,
> worktrees, and CI/cloud agent sessions — write entries public-safe (no
> real IPs, hostnames, credentials, personal filenames, album names, or
> photo captions; that context belongs in HANDOVER.md and
> `source-files/inventory/`, which stay local-only).
>
> Add an entry when: a design trade-off is chosen (and why), a debugging
> session yields a non-obvious fact, an incident teaches a rule, or an
> approach is deliberately rejected.

Format:

```
## YYYY-MM-DD — Short title
**Decision/Lesson:** what was decided or learned.
**Why:** the reasoning or the incident.
**Implication:** what future work must respect because of this.
```

---

## 2026-08-26 — Milestone-0 inventory: the corpus was measured, not assumed

**Decision/Lesson:** Every "verify" item in the initial prompt's section 2
was checked against all 1,265 real files by three read-only scout agents
before any decoder code was written. Full briefs and CSVs live in
`source-files/inventory/` (gitignored). The entries below record each
resolved item; several refuted the starting assumptions.
**Why:** The prompt explicitly flagged the prior investigation's notes as
"findings to be verified, not established facts." Building on the unverified
version would have produced a converter that silently dated photos wrongly.
**Implication:** These are now settled facts. Do not re-derive them from the
spec or from the prior agent's notes; re-measure only if the corpus changes.

## 2026-08-26 — There is no capture date in this corpus (refutes prompt notes 7-9)

**Decision/Lesson:** The FlashPix per-picture camera-settings group
(`0x25xxxxxx`, including the spec capture date `0x25000000`) is **absent
from all 1,265 files** — the authoring application never wrote it. The only
timestamp present is `PIDSI_CREATE_DTM`, replicated byte-identically into
four property streams (root SummaryInformation, the Data Object Store
SummaryInformation, Transform `0x00010006`, DataObject `0x00010006`), delta
0 s. It is an **import-batch stamp**, not a shutter time: 1,265 files carry
only **26 distinct calendar dates**, and single events of ~100 photos share
a single sub-hour window.
**Why:** Measured directly. Checked against the dated-folder ground truth,
the embedded stamp fails 7 of 9 dated folders — errors range from +2 days to
+3 months, and one folder's contents land in the **wrong calendar year**.
**Implication:** The embedded timestamp must never be written to
`EXIF:DateTimeOriginal`. Honest mapping is `DateTimeDigitized` /
`xmp:CreateDate`. The absolute capture day must come from an external
signal; the folder name is better ground truth than anything in the file.
No exposure, f-number, focal length, flash, or ISO exists to map either.

## 2026-08-26 — Stored FILETIMEs are LOCAL time; do not timezone-convert

**Decision/Lesson:** The OLE FILETIMEs in this corpus hold **local wall-clock
time**, contradicting the OLE spec's UTC requirement and the prompt's note 8.
**Why:** Three independent lines of evidence. (1) `fs_mtime - embedded` is
always a whole number of hours plus 2-6 seconds — one event, not two clocks.
(2) The whole-hour gap tracks US DST transition dates exactly and is **zero
in summer** on the least-corrupted copy of the corpus; a true-UTC value would
require the copy chain to have coincidentally added exactly the zone offset.
(3) The as-stored hour histogram reads as a household PC: 46% of files fall
between 17:00-22:00, with a 2.4% dead zone from 07:00-13:00.
**Implication:** Applying a UTC-to-local conversion would roll the 20% of
files stamped 00:00-04:59 onto the **previous calendar day**. Treat stored
values as already-local. Filesystem mtime is the same instant with additional
copy corruption layered on and must never be used as a fallback.

## 2026-08-26 — Filenames are the only human-authored content in the archive

**Decision/Lesson:** No captions, titles, subjects, authors, keywords, or
comments exist in any property set of any file. No external caption or
album database exists anywhere in the source backup either. Folder
membership is expressed solely by folder name; captions are expressed
solely by filename, on ~17% of files.
**Why:** Full property census over all files plus an exhaustive search of
the source tree for `.ini`/`.db`/`.dat`/`.alb`/`.pez` sidecars. The only
sidecars found are two 8-byte mode markers.
**Implication:** Preserving the original filename and the original folder
name is **mandatory and irreplaceable** — there is no embedded fallback. Any
deduplication that collapses several paths to one output must explicitly
prefer the human-authored name over a camera-generated one, and must record
every contributing folder. Losing a filename loses a caption permanently.

## 2026-08-26 — Colour space is NIF RGB, not PhotoYCC (refutes prompt note 3)

**Decision/Lesson:** Declared colour space lives in `Image Contents` property
`0x02RR0002` (VT_BLOB, 20 bytes: uncalibrated flag, channel count, then
per-channel ids). **99.7% of subimages are NIF RGB** (channel ids
`0x00030000/1/2`). Only 4 files in the corpus are PhotoYCC.
**Why:** Read directly from the blob, then corroborated three ways: the
decoder library's own colour-space table, the per-tile "internal colour
conversion" flag being ON (the JPEG does RGB-to-YCbCr itself), and the JPEG
SOF0 component ids being 1/2/3 at 4:4:4. The PhotoYCC files invert all three.
**Implication:** The expensive YCC-to-sRGB colour-science step the prompt
anticipated is **not** needed for the bulk of the corpus — but the handful of
PhotoYCC files still need it, and decoding them as RGB yields 25-28 levels of
error. Detect per file; never assume corpus-wide. No ICC profile exists
anywhere, so sRGB is an assumption the output makes explicit.

## 2026-08-26 — Viewing transforms are real: some images need 90° CCW rotation

**Decision/Lesson:** Every file has a `Transform` stream. The spatial
orientation matrix is property `0x10000003` (VT_VECTOR|VT_R4, 16 elements).
Across the corpus it is identity on most files, scale+translate (crop) on
~100, and a **pure 90° rotation on 45 instances** covering 24 distinct
images. Direction is **counter-clockwise**.
**Why:** Rotation direction was settled empirically rather than by reading
the spec: correlating the candidate rotations against each file's own
already-oriented embedded thumbnail gave +0.999 for CCW versus -0.23 for CW.
The human-readable edit log stream independently records a 270° rotate.
**Implication:** A decoder that ignores `0x10000003` will emit those images
sideways and will ignore ~100 crops. The matrix is authoritative and present
in every file; the human-readable edit log is corroboration only, and exists
on just 12% of files. Also present: a non-identity colour twist
(`0x10000004`) on 12 files.

## 2026-08-26 — Tile format: abbreviated JPEG with external tables, +28 byte offset base

**Decision/Lesson:** Resolution headers are **64-byte preamble + N x 16-byte
little-endian records** (`offset, size, compression_type, compression_subtype`);
`64 + N*16 == len(header)` held on every file. **Tile offsets are relative to
byte 28 of the Data stream**, not byte 0. Tiles are always 64x64x3. Of
~318,000 tiles: ~97% JPEG, ~3% uncompressed (exactly 12,288 bytes, no
markers), and ~930 single-colour fills with **size 0** whose colour is
encoded in the compression subtype.
**Why:** Parsed and arithmetic-checked across the corpus; the offset base and
record layout were confirmed by `28 + max(offset+size) == len(data)`.
**Implication:** Hardcoding offset base 0 or a record size other than 16
breaks everything. Zero-length tiles are not errors. Do not derive the top
resolution index from the image width — read it from `0x01000000`, because a
few files have fewer resolutions than the corpus norm.

## 2026-08-26 — JPEG tiles are abbreviated; splice tables and strip the trailing EOI

**Decision/Lesson:** Tile JPEG streams contain **only** SOI, SOF0, SOS, EOI —
no DQT, no DHT, no APP segments (confirmed on ~11,800 tiles). The external
table stream is `Image Contents` property `0x03FE0001` (VT_BLOB, 574 bytes:
SOI + 2 DQT + 4 DHT + EOI), present on the files that have compressed tiles.
The table id is **per tile**, carried in byte 3 of the compression subtype.
Reconstruction is `tables[:-2] + tile[2:]` — the table blob's **trailing EOI
must be stripped**.
**Why:** Full marker parse of every tile in a 50-file sample. Reconstruction
verified on 150 files: 100% decoded, zero black frames, minimum per-image
standard deviation 28.77, and 0.97-0.999 correlation against each file's own
embedded thumbnail.
**Implication:** This is the working pixel path. The per-tile table id means a
single global table assumption is wrong for the minority files that use
alternate table ids.

## 2026-08-26 — Pillow's FpxImagePlugin is unusable and can crash the interpreter

**Decision/Lesson:** Run over all 1,265 files, Pillow's built-in FlashPix
plugin opened **39** and raised on **1,224** (`broken data stream when reading
image file`, `decoder fill not available`). Two files **hard-crashed the
CPython process** (access violation; heap corruption, nondeterministic). Root
cause of the common failure: the plugin prepends the table blob *including*
its trailing EOI marker. It also has no decoder for zero-length single-colour
tiles.
**Why:** The prompt asked to try the cheapest pixel path first. It was tried
exhaustively rather than on a few samples, which is what surfaced the crashes.
**Implication:** The custom decoder is the primary path, not a fallback. The
39 successes were used as a correctness oracle — they matched the custom
reconstruction at 0.0 mean absolute difference. If Pillow's plugin is ever
invoked on this corpus again, isolate it in a subprocess; an in-process crash
takes the whole batch run down.

## 2026-08-26 — Every file embeds a usable thumbnail, as a DIB (not a JPEG)

**Decision/Lesson:** `PIDSI_THUMBNAIL` (PID 17, VT_CF) is present in
**1,265/1,265**, 12-28 KB, and accounts for ~99% of the root summary stream's
size. It is `CF_DIB`: int32 -1, uint32 8, a 40-byte BITMAPINFOHEADER, then
raw bottom-up 24-bit pixels on a 4-byte stride. Long side is always 96.
**Why:** Characterized byte-exactly; the size formula matched on every file.
**Implication:** Two free wins. It gives the QA gallery its thumbnails
without decoding anything, and — because it is stored **already oriented** —
it is an independent oracle for verifying both decode correctness and
rotation direction. Writing it out as `.jpg` produces garbage; it needs a
14-byte BITMAPFILEHEADER prepended, or conversion.

## 2026-08-26 — The corpus is 541 distinct photos, not 1,265 files

**Decision/Lesson:** 1,265 files reduce to 687 distinct SHA-256, 666
distinct once volatile save-timestamp streams are excluded, and **541
distinct pixel payloads**. The two source trees are not independent: by pixel
hash one is a strict superset of the other, overlapping on 538 of 541. Of the
"same name, different hash" pairs, all but one differ by ~14 bytes in
property streams only. One large archive file in the tree contains no unique
content whatsoever.
**Why:** Three-level hash cascade (whole file / non-volatile streams / pixel
streams) over every file.
**Implication:** Keying deduplication on whole-file SHA-256 converts ~27%
more images than necessary and emits pixel-identical outputs that differ only
by a timestamp. Key on the pixel hash, ingest all paths for metadata, and
carry every contributing path forward in the sidecar. Exactly one filename
collision in the corpus is a genuinely different photo — the dedup must be
content-based, never name-based.

## 2026-08-26 — Corpus integrity is clean; no bit rot to report

**Decision/Lesson:** All 1,265 files are valid OLE2 compound documents with
the correct magic. Zero zero-length, zero truncated, zero unreadable
streams. Zero files were cloud-storage online-only placeholders, so hashing
triggered no silent downloads. Declared dimensions are uniform on 98.5% of
files, with 19 exceptions including two natively-portrait images.
**Why:** Attributes were checked before opening, and every stream in every
file was read.
**Implication:** The prompt anticipated bit-rotted files from 2002-era discs
as acceptable reported failures. There are none — so the conversion target is
genuinely 100%, and any decode failure is a pipeline bug, not media decay.

## 2026-08-26 — Environment: Python 3.14 is viable; Windows long paths are disabled

**Decision/Lesson:** The dev machine has only Python 3.14.2, and the core
dependencies install and work on it. Separately, Windows long-path support is
**disabled** on this machine — installing a dependency into a deep path
failed partway through and left a corrupt package tree.
**Why:** The prompt advised targeting 3.12/3.13 and checking wheel
availability rather than assuming; checking showed 3.14 wheels exist for the
imaging and array dependencies. The long-path failure happened in practice
during setup.
**Implication:** Target 3.14 but pin the toolchain explicitly, and re-verify
wheel availability before the packaging milestone, which is the dependency
most likely to lag. Keep venvs, working directories, and the output root at
**short paths**; a deep path plus deeply-nested package contents silently
exceeds the limit. The output root must also sit **outside cloud-synced
folders** — writing gigabytes of derivatives inside one triggers a full
upload of data that is by policy never meant to leave the machine.

## 2026-08-26 — Dating strategy: folder-derived dates plus an owner review pass

**Decision/Lesson:** Because no capture date exists in the corpus, the
absolute capture day comes from the **folder name**, not the file. Folders
whose names encode a date are parsed automatically; the remaining folders,
and the large flat folder that has no name-derived date at all, are surfaced
in the QA gallery with a per-group date field for the owner to fill once.
`EXIF:DateTimeOriginal` is written **only** where a date is defensible;
`DateTimeDigitized` / `xmp:CreateDate` always carry the import stamp.
Ordering within a group comes from the camera filename sequence and the
import order, both of which survive even where the absolute day does not.
**Why:** Three alternatives were rejected. Writing the import stamp to
`DateTimeOriginal` was rejected as knowingly false — it puts one folder's
photos in the wrong calendar year while looking authoritative. Automated
folder parsing alone was rejected as leaving most of the corpus undated.
Writing no `DateTimeOriginal` at all was rejected because chronological
sorting in photo apps is the owner's primary goal.
**Implication:** The review pass is a **product requirement**, not a
nice-to-have — the gallery must collect dates, not just display them. The
timestamp source (folder-parsed / owner-supplied / import-stamp-only) must
be recorded per file in the sidecar and in the audit report, so the mapping
can be redone later. The folder-name ground-truth check remains an automated
gate against the parsed dates.

## 2026-08-26 — Deduplication keys on whole-file SHA-256, not the pixel hash

**Decision/Lesson:** One output per distinct whole-file SHA-256 (687 units,
~2.4 GB), rather than per distinct pixel payload (541 units, ~1.9 GB).
**Why:** Owner's decision, overriding the analysis recommendation. The
prompt specified SHA-256 keying and the owner chose to keep it.
**Implication:** The run will emit roughly 146 output pairs that are
pixel-identical and differ only by a ~14-byte save timestamp in a property
stream. This is expected and must **not** be reported as a fault by the
audit. The filename-preservation rule still applies *within* each hash
group, because one hash still maps to several source paths and folders: the
output name must prefer a human-authored filename over a camera-generated
one, and the sidecar must record every contributing path and folder.

## 2026-08-26 — Output lives in the repo folder, gitignored, inside cloud sync

**Decision/Lesson:** The output root stays at `output/` inside the project
folder. `/output/` is gitignored, verified empirically: files planted at
every output subpath (archive, sharing, report, audit JSON, log) were
invisible to `git status --untracked-files=all`.
**Why:** Owner's decision, and one the prompt explicitly offered. The
machine has only one fixed drive, so an out-of-sync-scope location would
have been an arbitrary sibling directory rather than a separate volume.
**Implication:** The output root sits **inside cloud sync**, so the folder
must be pinned "always keep on this device" or sync will upload several GB
of personal derivatives. The path is configured in `.env` and is never
hardcoded, so relocating it later costs one line. The gitignore rule is
load-bearing — any change to it must be re-verified with the planted-file
test, not by inspection.

## 2026-08-26 — Milestone 0 shipped without a CI green tick (Actions outage)

**Decision/Lesson:** The `/milestone-0` skill requires CI to be green on the
configuration commit before the scaffold files are deleted. GitHub Actions
was in a **major outage** that day and created **zero** workflow runs for
either configuration push — not queued, not failed, none at all. At the
owner's direction the milestone was completed anyway, substituting a local
reproduction of the CI job: a throwaway venv built only from
`requirements-dev.txt`, in which every dependency resolved to a cp314 wheel
with no source builds, followed by `ruff check .` and the tier-1 suite,
both green. The release gate's own two checks (`scripts/check-version.sh`
and the scaffold-marker grep) were exercised by hand as well.
**Why:** The outage was verified as external, not a defect in the workflow:
the commits were on remote `main`, Actions was `enabled` on the repo, both
workflows listed as `active`, and the committed `ci.yml` parsed as valid
YAML with LF endings and no BOM. Runs on the three preceding commits had all
succeeded. Waiting would have parked the milestone indefinitely on a
third-party incident.
**Implication:** Commits `0270a0e` and `5373bd1` are the only ones in this
repo's history that were **never verified by CI**. The first CI run after
the outage recovers is therefore load-bearing — if it fails, the fault is
most likely in one of those two commits, and the local reproduction that
stood in for it is the thing that was insufficient. Do not treat a local
run as equivalent to CI again except under the same explicit direction;
the point of CI here is that it is a *different machine* from the one the
code was written on.

## 2026-08-26 — Ingestion run: the inventory's numbers reproduce exactly

**Decision/Lesson:** The first real run of the ingestion tool over the whole
corpus reproduces the read-only spike's figures to the file: **1,265 files,
494.9 MB, 687 distinct SHA-256, 263.3 MB distinct, zero non-OLE2 files.**
Duplicate structure is 114 singletons, 568 pairs, and 5 triples, which sums
to 1,265 exactly. 573 of the 687 entries appear in both source trees.
**Why:** The spike and the tool are independent implementations — different
code, written days apart, one by scout agents and one as the shipped
package. Agreement on every count is the strongest evidence available that
neither is quietly wrong.
**Implication:** The corpus is now a known quantity and the manifest is the
reference. A future run that disagrees with these numbers means the source
tree changed, not that the tool improved.

## 2026-08-26 — The read-only promise is proven, not asserted

**Decision/Lesson:** `scan` snapshots size and mtime for every source file
before opening any of them, re-compares afterwards, and re-hashes a random
sample on top. Re-running the scan *after* the 687-file copy produced a
**byte-identical manifest** — every hash, every path, every count.
**Why:** Size and mtime alone would miss a write that restored both, and
that is exactly the write that would silently corrupt an irreplaceable
archive. The sample re-hash is the check that would actually catch it.
**Implication:** Every future stage must keep this property and must keep
proving it. "The code only opens files for reading" is an assertion; a
byte-identical re-scan is evidence. Never downgrade the check to a comment.

## 2026-08-26 — Camera-name detection covers P####### too, not just DCP#####

**Decision/Lesson:** The inventory reported 219 of 1,265 files (17%) as
human-named. The shipped classifier reports **211**. The difference is
exactly 8 files, and it is not a defect in either: the inventory's rule
matched only `DCP#####.fpx`, while the classifier also treats `P#######`
as camera-generated. Those 8 are the four burst-sample frames and their
duplicates in the other tree.
**Why:** Checked rather than assumed — every name the classifier calls
camera-generated was verified to be literally `DCP` or `P` followed by
digits, with **zero** false positives. No human-authored name is being
discarded, which is the only direction of error that would lose a caption
permanently.
**Implication:** 211 is the number to carry forward. When a figure here
disagrees with the inventory briefs, reconcile it explicitly rather than
picking one — the briefs were a spike and used looser rules in places.

## 2026-08-26 — SHA-256 keying produces ~77 filename collisions, and that is fine

**Decision/Lesson:** Keying on whole-file SHA-256 means the same photo can
appear as two entries whose source filenames are identical but whose bytes
differ by a timestamp buried in a property stream. About 77 store names
therefore carry an 8-character hash suffix. Only one collision in the whole
corpus is a genuinely *different* photograph; the rest are byte-variants of
the same image.
**Why:** A direct consequence of the approved dedup key (687 SHA-256 versus
541 pixel payloads). The store must never let one variant overwrite another,
so the second claimant of a name gets a suffix and the first keeps the bare
name, ordered by hash so the result does not depend on traversal order.
**Implication:** A suffixed store name is normal and must not be treated as
an anomaly by the audit. When the pixel decoder lands, these pairs are also
the natural regression check: two entries whose decoded pixels are identical
should stay identical.

## 2026-08-26 — The pre-release audit caught what the tests were built to miss

**Decision/Lesson:** `code-auditor` returned DO NOT MERGE on 0.1.0 and was
right on every count. Four defects sat in exactly the code this project
cares most about, and all four passed a green test suite:
1. The read-only proof drew its "random" sample from a **fixed seed over a
   sorted list**, so every run re-hashed the same 25 files forever. 98% of
   the archive was permanently outside the check while the code read like
   sampling.
2. It compared only files present when the snapshot was taken, so a file
   **added** to the archive was invisible — and creating a file is a write.
3. **No write target was constrained.** `ingest --dest` and `scan
   --manifest` took free-form paths, so a mistyped flag would create a
   directory inside the archive and truncate any source file whose name
   matched a store name.
4. The only test guarding all of this **passed against a stub**: it asserted
   the happy path, which a function that inspected nothing would satisfy.
**Why:** Every one was reproduced against real data before being fixed, not
taken on the auditor's word. The pattern behind all four is the same — the
tests asserted that the code *worked*, never that it *noticed*. A check
exists for its failure mode; a suite that only exercises the success path
tests the half that does not matter.
**Implication:** For any invariant this project calls binding: enforce it in
code rather than convention (the containment guard), and test it by breaking
it (modify, delete, add, and change-while-preserving-size-and-mtime). Ask of
every new guard: *would this test still pass if the function did nothing?*
Run `code-auditor` before every release, not as a formality — it found in
one pass what a full corpus run had not surfaced.

## 2026-08-26 — Disambiguate collisions with a counter, not a longer hash prefix

**Decision/Lesson:** The first fix for the store-name collision widened the
hash prefix on each retry (8 chars, then 12, then 16). That is wrong twice:
it does not terminate for hashes sharing a long prefix, and the loop could
raise even when the candidate it had just built was free. Replaced with a
fixed 8-character prefix plus an incrementing ordinal.
**Why:** Caught by an adversarial stress test written *after* the fix, using
hashes that differ only in their last characters. The realistic case would
never have exposed it, which is the point of writing the hostile case.
**Implication:** A disambiguator must terminate for *any* input, not for the
inputs a real corpus happens to produce. When a retry loop derives its next
candidate from the data, check that the derivation can actually run out.

## 2026-08-26 — VT_VARIANT decoding and OLE property set completeness

**Decision/Lesson:** FlashPix property sets embed composite `VT_VARIANT`
(type 12) values (e.g. film extension data in film scans). In OLE property sets,
each `VT_VARIANT` entry carries its own 4-byte type code followed by the typed
payload. Handling `VT_VARIANT` as both scalar and vector elements allows full
zero-loss decoding of the entire archive without unparsed properties or dropped
metadata.
**Why:** The inventory prototype skipped `VT_VARIANT` on 4 film scan files.
Supporting recursive typed parsing decodes them cleanly across 100% of files.
**Implication:** Never swallow parser gaps. When a format specification
defines variant containers, decode them recursively or capture the structured
type and raw bytes explicitly.

## 2026-08-26 — Windows zoneinfo is empty without tzdata; calculate US DST directly

**Decision/Lesson:** On Windows without the `tzdata` wheel installed, Python's
`zoneinfo.ZoneInfo` finds no system timezone database (`available_timezones()`
returns an empty set). For calculating standard vs daylight saving UTC offsets
(`OffsetTime*`) on historical US dates (1998–2002) without modifying the local
wall-clock digits, calculating the 1987–2006 US DST rule (1st Sunday in April
to last Sunday in October) in pure Python is exact, portable, and dependency-free.
**Why:** Running `zoneinfo` lookups on clean Windows environments failed
silently and fell back to standard-time offsets.
**Implication:** Avoid unnecessary runtime dependencies for well-defined
historical schedules; a 15-line deterministic date formula is more reliable
than relying on OS-level IANA timezone databases on Windows.

## 2026-08-26 — FlashPix tile table offset 36 is relative to section start (0x1C)

**Decision/Lesson:** In the FlashPix `Subimage 0000 Header` stream, the header
field at offset `0x38` states the tile-table offset as 36 (`0x00000024`), while
the tile records physically begin at byte 64 (`0x00000040`). The offset is
relative to the start of the section header at byte 28 (`0x1C`):
`28 + 36 = 64` (0x40).
**Why:** Resolves the discrepancy flagged during the initial format reverse-engineering.
The subimage header follows standard OLE section layout conventions where
internal offsets are measured from the section header boundary.
**Implication:** Both the relative offset calculation (`28 + table_offset`) and
the fixed 64-byte preamble formula yield identical, byte-exact pointers across
100% of corpus files.

## 2026-08-26 — Retain binary payloads in VT_BLOB and VT_CF for downstream consumers

**Decision/Lesson:** OLE property parsers that convert binary types (`VT_BLOB`,
`VT_CF`) strictly into summary descriptors or truncated hex previews prevent
downstream modules (such as pixel decoders and thumbnail extractors) from
accessing essential payload streams (e.g. the 574-byte JPEG table blob or the
24-bit DIB pixel array). Retaining `raw_bytes` in memory while sanitizing/omitting
them during JSON sidecar serialization gives in-process decoders zero-copy access
without bloating disk sidecars.
**Why:** Discovered during milestone 0.3.0 when `decoder.py` required access to
`0x03TT0001` JPEG tables parsed by `propset.py`.
**Implication:** Property parsers in multi-stage pipelines should preserve raw
binary payloads on parsed objects and delegate serialization filtering to the
output serialization layer.

## 2026-08-26 — ExifTool CreateDate maps to EXIF DateTimeDigitized (0x9004)

**Decision/Lesson:** In ExifTool, the command-line flag `-EXIF:CreateDate` writes
standard EXIF tag `0x9004` (`Exif.Photo.DateTimeDigitized`) and `XMP-xmp:CreateDate`.
The flag `-EXIF:DateTimeOriginal` writes tag `0x9003` (`Exif.Photo.DateTimeOriginal`).
Setting `-EXIF:CreateDate` for the import timestamp ensures consistent, conflict-free
tag representation across both TIFF and JPEG containers when independently read
back via pyexiv2.
**Why:** Confirmed during dual output implementation and pyexiv2 round-trip testing.
**Implication:** Do not use proprietary or conflicting tag aliases. Maintain
strict separation between `CreateDate` (import batch stamp) and `DateTimeOriginal`
(defensible capture/folder date).

## 2026-08-26 — Deflate TIFF compression (Tag 8 / 32946) over LZW

**Decision/Lesson:** Saving archival TIFF derivatives with Pillow's
`compression="tiff_deflate"` writes Adobe Deflate (tag 8) or PKZIP Deflate
(tag 32946), producing byte-exact lossless images with superior compression ratios
over LZW while avoiding legacy LZW patent compatibility quirks.
**Why:** Required by project specification (requirement 18 and section 4).
**Implication:** Validate compression tags directly on written files via
`img.tag_v2.get(259)` during test execution.

## 2026-08-26 — DateTimeOriginal only from a day-precise folder name

**Decision/Lesson:** A folder date may become EXIF `DateTimeOriginal` only when
it names a single day. A bare year, a two-year span, a season and a month may
not, and the time-of-day is written as midnight rather than borrowed from the
import stamp.

**Why:** The first implementation accepted any folder name that parsed and used
the first day of the range, then took the hour, minute and second from the Kodak
import batch. Measured over the 687 distinct files: 219 were given a
folder-derived capture date, of which 151 had no day-precise evidence — 97 from
a bare year, 34 from a year span, 20 from a season. That is 22% of the archive
carrying a fabricated capture moment, precise to the second, in the one field
this project says may hold only a defensible date. After the change, 70 files
carry `DateTimeOriginal`: 68 day-precise folders and the 2 embedded scan dates.

**Implication:** Coarse folder dates are still useful and are still kept — as
`sort_datetime`, which drives the filesystem mtime and the filename prefix.
Those are ordering affordances, not claims. The prefix writes unknown
components as zeros (`2001-00-00_000000_`), which sorts correctly and can never
be mistaken for a date somebody knew. EXIF has no way to say "sometime in
2001"; a filename does.

## 2026-08-26 — Viewing-transform crops (superseded: now applied to the JPEG)

**Decision/Lesson:** `0x10000003` carries three shapes in this corpus, and the
decoder now classifies all three rather than testing for one. Measured over 687
files: 612 identity, 22 a 90° CCW rotation (applied), and **53 a
scale-and-translate matrix — a crop, which is not applied**. Six files also
carry a non-standard `RectangleOfInterest`.

**Why:** The decoder tested only for the rotation and let everything else fall
through to an unrotated image with `rotation_applied = 0`. An identity matrix, a
crop matrix and a `Transform` stream that failed to parse produced byte-identical
output and the same empty report, so 53 discarded crops were invisible.

**Implication:** Whether an archival TIFF should honour a crop somebody made in
Kodak's software in 2002, or preserve the full frame the camera captured, is an
owner decision and is still open. Until it is made, `convert` names every
affected file. Note also that `has_transform` previously compared the ROI
against `[0, 0, 1, 1]` and was therefore `True` for all 687 files: FlashPix
normalises height to 1 and expresses width as the aspect ratio, so a 4:3
full-frame ROI is `[0, 0, 1.333, 1]`.

## 2026-08-26 — CI installs ExifTool; a missing one fails rather than skips

**Decision/Lesson:** The CI workflow installs ExifTool and sets
`FPX_REQUIRE_EXIFTOOL=1`, which converts the tier-2 skip guard into a failure. A
tier-1 test asserts the workflow keeps doing both.

**Why:** The tier-2 tests that write tags with ExifTool and read them back with
pyexiv2 were gated on the tool being present. GitHub's Windows runners ship no
ExifTool, so on CI they skipped — meaning the "validate with a different tool
than the one that wrote" rule was advertised as covered while running nowhere.
Separately, one convert test had no skip guard at all, so **every commit on
`feat/0.4.0-dual-output` failed CI** while the milestone was reported green from
a local run.

**Implication:** A skip that hides a binding rule is worse than a missing test,
because the suite still reports green. Where a tier depends on an external tool,
either install it in CI or make its absence loud. The CI ExifTool is deliberately
unpinned, unlike `requirements.txt`: the pinned copy is the one on the conversion
machine, and CI's job is to notice when upstream changes break the round-trip.

## 2026-08-26 — Output names are assigned per album from the manifest

**Decision/Lesson:** Output stems are resolved for the whole batch up front by
`naming.assign_output_stems`, from the manifest alone, before any metadata is
extracted.

**Why:** `<album>/<date>_<stem>.<ext>` has no collision handling, and files in one
album usually share a date prefix, so the stem was the only thing separating two
photos. This corpus already contains distinct SHA-256s sharing a filename, because
Kodak cameras reset their numbering — the second file overwrote the first and the
run reported both converted. This is the same defect the 0.1.0 audit found in
`assign_store_names`, one layer further down.

**Implication:** Assignment must not depend on filesystem state or on which files
have already been converted, or a resumed run would name things differently from
the run it resumed. Ordering is by hash for the same reason it is in
`assign_store_names`.

## 2026-08-26 — VT_LPSTR honours the section CODEPAGE; sidecars keep binary payloads

**Decision/Lesson:** Two fidelity fixes in the property-set layer. Strings are
decoded with the codec the section's `CODEPAGE` declares (resolved before any
string is parsed, not whenever PID 1 is reached), and binary payloads up to
64 KiB are carried in the sidecar as base64 with a SHA-256 alongside.

**Why:** The parser read `CODEPAGE`, stored it, and then decoded every `VT_LPSTR`
as latin-1 regardless. 1,374 sections in this corpus declare 1252, which differs
from latin-1 in exactly the `0x80`–`0x9F` range holding curly quotes, dashes and
ellipsis — latin-1 maps those to C1 control characters. No `VT_LPSTR` in the
corpus currently contains such a byte, so this repairs nothing today; it stops a
name that does from reaching XMP as junk. Separately, the sidecar dropped every
binary buffer and kept a 32-byte `hex_preview`, while describing itself as the
complete raw property dump — losing the embedded thumbnail DIB (~20 KB) and the
external JPEG tables, the two properties anyone would come back for.

**Implication:** A parser that reads an encoding declaration and ignores it is
worse than one that never read it, because the sidecar then records a code page
that does not describe its own strings.

## 2026-08-26 — The crop goes to sharing/, the full frame stays in archive/

**Decision/Lesson:** The 53 files carrying a crop matrix now produce a
full-frame TIFF in `archive/` and a cropped JPEG in `sharing/`. Owner
decision, taken after the transform was measured. Supersedes the entry above,
which recorded crops as detected-but-not-applied.

**Why:** The crop is a composition somebody deliberately framed in the Kodak
software; the full frame is what the camera actually captured. Both are worth
keeping, and the two output trees already have exactly those two jobs. The
`.fpx` original sits beside the TIFF either way, so nothing is one-way.

**The geometry, which is not obvious.** FlashPix normalises image coordinates
so height is 1.0 and width is the aspect ratio, making one normalised unit
exactly `height` pixels on *both* axes. The matrix maps the result viewport —
spanning `[0, ResultAspectRatio] × [0, 1]` — back into the source:

    left = tx·H,  top = ty·H,  width = scale·ResultAspectRatio·H,  height = scale·H

`ResultAspectRatio` (`0x10000000`) is the term that makes this work, and it is
per-file: it describes the *cropped* result, not the source. Without it the
translation alone appears to push the crop box outside the frame, which is
what made the first reading of the matrix look wrong. With it, all 53 boxes
land inside the image and every resulting width/height matches the declared
aspect ratio to four decimal places.

**Verified against an independent oracle, not against the algebra.** The
embedded DIB thumbnail was written by the same software that recorded the
transform, so it witnesses the intended framing. Cropping improved
correlation with the thumbnail on **53 of 53 files** — mean +0.61, minimum
+0.18, none worse. This is the same oracle that confirmed the 90° rotation.

**Implication:** Round the crop origin and the crop *size* separately, not all
four edges: rounding edges independently moves the width or height by a pixel
and pushes the result off the declared aspect ratio, which is the quantity the
whole calculation is anchored on. And the validator no longer asserts that
TIFF and JPEG dimensions match — it asserts each is the size it was supposed
to be, which is the stronger check, since a crop that silently failed to apply
would satisfy a bare equality test.

---

## 2026-08-26 — A rotation can carry a crop; 14 of 22 do

**Decision/Lesson:** The crop box is derived by mapping the four corners of
the result viewport through the transform matrix and taking the bounding box,
not by reading a scale and a translation off the matrix. Rotation and crop are
independent properties of the same matrix, and asking "is this a rotation or a
crop?" answers the wrong question. Refines the entry above.

**Why:** The closed form recorded above — `left = tx·H`, `width =
scale·ResultAspectRatio·H` — is only valid for an axis-aligned matrix. For a
rotation the scale sits on the off-diagonal, so the formula reads zeros and the
code took the "this is a rotation, not a crop" branch and dropped the crop.
Measured over the corpus: **14 of the 22 rotated files also carry a crop**, and
every one of them was being written rotated but uncropped, with `crop_box:
null` in the sidecar and nothing in the audit. The corner-mapping form
reproduces the closed form exactly on the axis-aligned files and additionally
handles the rotated ones, so there is one derivation rather than two.

Applying it moved the counts: **609 untouched / 8 rotation only / 14 rotation
plus crop / 56 axis-aligned crops**, so 70 files resolve to a crop where 53 did
before. Three of those are neither rotated nor classified as crops: they are
matrices inside the classifier's 2% identity tolerance that nonetheless resolve
to a real box, and not a marginal one — they keep **83.5%, 86.5% and 74.8%** of
the frame, with the crop coming from `ResultAspectRatio` narrowing the viewport
rather than from the matrix at all. Within 2% the label is unreliable and **the
box is the authority**.

The threshold in the other direction matters too. One 320×139 file declares a
`ResultAspectRatio` 0.0056 under its frame's, which resolves to a box one
column narrower — a JPEG cut a pixel off the TIFF for no visible reason, an
oracle improvement of +0.003 that is indistinguishable from noise, and a file
moved into the crop bucket in the audit. A box within a pixel of the frame on
both axes is rounding, not a crop, and is discarded.

**Verified against the same independent oracle.** Cropping improved
correlation with the embedded DIB thumbnail on **70 of 70 files** — mean
+0.56, minimum +0.18, none worse — and the worst post-crop correlation is
0.981.

**Implication:** The crop box in the sidecar is in the *output* image's
coordinates — after rotation — because that is the image the JPEG is cut from.
The mapping under a 90° CCW rotation is `(l, t, r, b) → (t, W−r, b, W−l)`, and
it is tested by marking a pixel and following it through Pillow rather than by
re-deriving the arithmetic, because three wrong variants of that formula look
equally plausible written down.

---

## 2026-08-26 — The thumbnail oracle sees geometry, not colour

**Decision/Lesson:** `compute_image_correlation` converts both images to
greyscale (`convert("L")`) before correlating. It is therefore evidence about
framing, orientation and crop — and **no evidence at all about colour**. Do
not cite a thumbnail correlation in support of any colour claim.

**Why:** It is the strongest oracle this project has, it was used to confirm
both the 90° rotation and all 70 crops, and its numbers are high enough
(worst 0.981) to look like a general-purpose "the image is right" check. It
is not one. A file decoded with the colour channels permuted, or with
PhotoYCC left unconverted, would correlate just as well. It is **aspect-blind**
as well: `compute_image_correlation` resizes both images to a square 64×64, so
it cannot witness a box of the wrong shape either — only that the framing moved
in the right direction.

**Implication:** The 2 PhotoYCC files in the corpus have **never been looked
at by a human**. Nothing in the automated suite can tell a correct PhotoYCC
conversion from an incorrect one. Per `CLAUDE.md`'s "it decoded" is not "it
decoded correctly" rule, colour needs eyes at least once per variant, so both
PhotoYCC files are on the tier-4 eyeball list at 1.0.0 and are not covered by
anything before it.

---

## 2026-08-26 — A parser that returns errors is not a parser that raises

**Decision/Lesson:** `propset.parse_propset` reports malformed input by
returning a property set carrying `errors`, not by raising. Any caller that
guards only with `try/except` therefore treats corrupt input as valid-but-empty.

**Why:** `apply_viewing_transform` had exactly that shape. A `Transform`
stream that failed to parse produced no matrix, which read as "this file has
no transform" — byte-identical output and an identical audit line to a file
that genuinely has none. The `parse-error` status existed, was tested for by
nothing, and was unreachable. A tier-1 test feeding the function the bytes
`b"not a property set"` is what surfaced it.

**Implication:** `parse_transform_stream` checks `pset.ok` and raises
`DecoderError`. Where a helper's failure mode is a return value rather than an
exception, the test that proves the error path has to feed it real malformed
bytes — asserting on a mocked exception would have passed against the broken
version.
