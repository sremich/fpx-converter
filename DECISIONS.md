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
