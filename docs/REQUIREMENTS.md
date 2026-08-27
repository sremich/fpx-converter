# fpx-converter — requirements

> **Provenance.** This is the public-safe, committed copy of the project's
> initial prompt. The original stays local in `source-files/` (gitignored)
> together with the inventory briefs. Redacted here: the absolute path to
> the source archive, album folder names, and photo filenames and captions —
> they identify a private family archive and belong in `HANDOVER.md`, not in
> the repo.
>
> **Section 2 was a set of hypotheses, not facts.** The prompt said to treat
> the prior investigation's notes as findings to be verified. The
> milestone-0 inventory verified all of them against every file in the
> corpus, and several were **refuted**. Each note below carries its resolved
> status; the reasoning and evidence are in `DECISIONS.md`. Nothing in this
> document should be built on without reading that status line.

## 1. Context

A personal family photo collection shot around 2000–2002 on a Kodak
DC200/DC210 digital camera and managed with Kodak Picture Easy software.
Roughly 1,265 `.fpx` (FlashPix) files across old CD/DVD backups. They cover
irreplaceable events, and the capture date of each photo matters as much as
the pixels.

**The original `.fpx` files are the archive. Everything this tool produces
is a derivative. Nothing in this project may modify, move, or delete a
source file.**

The situation that motivates the project:

1. Modern operating systems and photo apps cannot open `.fpx` at all.
2. Every converter tried has failed in one of four ways: output renders as a
   black rectangle; the tool is 32-bit only and won't run on 64-bit Windows
   11; a trial tool watermarks the output; or — in every case — the embedded
   metadata is silently discarded. Without a capture date, chronological
   sorting in any modern photo app is meaningless.
3. A previous investigation with another agent produced the technical notes
   in section 2. They were to be treated as findings to be verified, not
   established facts.

The deliverable is a 64-bit conversion pipeline — a Python CLI in a venv on
Windows — that batch-converts every `.fpx` into a lossless archival
derivative and a shareable JPEG, with all recoverable metadata translated
into standard EXIF/XMP/IPTC tags and a complete sidecar dump.

## 2. Technical notes, and how they resolved

### FlashPix structure

1. **CONFIRMED.** `.fpx` is an OLE2 compound document. `Data Object Store
   000001` holds a multi-resolution pyramid of `Resolution 0000` …
   `Resolution 000N` storages; the highest index is full resolution. Each
   has a `Subimage 0000 Header` stream (per-tile table) and a
   `Subimage 0000 Data` stream (64×64 tiles).
2. **CONFIRMED, with a correction.** Tiles are uncompressed, single-colour
   fill, or JPEG. The JPEG tiles are *abbreviated* — SOI/SOF0/SOS/EOI only —
   and the tables live in the `Image Contents` property set. Two details the
   note did not have: **tile offsets are relative to byte 28 of the Data
   stream**, and the table ID is **per tile**, not per file. Reassembly is
   `tables[:-2] + tile[2:]` — the table blob's trailing EOI must be
   stripped.
3. **REFUTED.** The colour space is **NIF RGB** on 1,261 of 1,265 files, not
   PhotoYCC. Only 4 files are PhotoYCC. No ICC profile exists anywhere. The
   colour-science step is therefore far smaller than budgeted.
4. **CONFIRMED — and it matters.** Viewing transforms are real: identity on
   1,114 files, scale+translate on 106, and **pure 90° CCW rotation on 45**
   (24 distinct images). Direction was proven empirically against the
   embedded thumbnail and corroborated by an edit log. A naive tile decoder
   would emit those sideways.
5. **CONFIRMED.** Never hardcode 1152×864. 1,246 files are that size; 19 are
   not, including two natively portrait. Read the declared size per file and
   use it everywhere.
6. **REFUTED, emphatically.** Pillow's `FpxImagePlugin` opens 39 files,
   raises on 1,224, and **hard-crashes CPython on 2**. It cannot be the
   pixel path. The 39 successes are useful only as an out-of-process
   correctness oracle — and they do validate the custom decoder exactly
   (0.0 mean absolute difference).

### Metadata

7. **REFUTED — this was the project's central premise.** The FlashPix
   capture-date property `0x25000000`, and the entire `0x25xxxxxx`
   per-picture group, are **absent from all 1,265 files**. Picture Easy
   never wrote them. There is no exposure time, f-number, focal length,
   flash, or ISO to map either. The only timestamp is
   `PIDSI_CREATE_DTM` — an **import-batch stamp**, not a shutter time:
   1,265 files carry just 26 distinct calendar dates.
8. **REFUTED.** The stored FILETIMEs are **local wall-clock time, not UTC**.
   Converting them would roll the 20% of files stamped between midnight and
   05:00 onto the previous calendar day. Do not convert. The home time zone
   is `America/Chicago`, with per-album overrides where a folder name
   implies elsewhere; that map selects the `OffsetTimeOriginal` /
   `OffsetTimeDigitized` values written, and applies no conversion.
9. **CONFIRMED as the check — and the preferred source failed it.** Album
   folder names encode dates, and against them the import stamp fails 7 of 9
   dated albums, including one by a whole year. Per the note's own
   instruction the pipeline does not silently switch sources: the approved
   resolution is **folder-derived dates plus an owner review pass in the QA
   gallery**, with `DateTimeOriginal` written only where a date is
   defensible and the import stamp always going to `DateTimeDigitized` /
   `xmp:CreateDate`.
10. **PARTIAL.** Camera make and model are present on 1,187 files and map
    cleanly. The per-picture settings group does not exist (note 7). No
    captions, titles, or notes exist in any property set, and no Picture
    Easy database exists anywhere in the backup.
11. **CONFIRMED.** `olefile.getproperties()` does not handle every FlashPix
    type. A custom property-set parser is required, covering all 10 property
    sets and 2 extension storages the inventory found.
12. **CONFIRMED, with an addition.** Album folder name → `IPTC:Keywords` and
    `XMP-dc:Subject`. Since no captions exist in the metadata, the
    **filename** is the only human-authored content in the archive — about
    17% of files are human-named — and must be preserved into the sidecar
    and, where meaningful, the description tags.

### Ingestion

13. **RESOLVED.** Copy only `*.fpx` / `*.FPX` (case-insensitive) into
    `source-files/`. The inventory read every archive file in place: the
    zips contain exactly the loose files and **zero unique content**, and no
    `.fpx` exists only inside a zip. No album database file exists.
14. **RESOLVED.** Filename collisions across folders do occur; exactly one
    is a genuinely different photo, so **deduplication must be
    content-based**. The manifest keys on **whole-file SHA-256** and records
    every source path and album a given file appears under. Identical hashes
    in different albums are **converted once**, with all paths recorded in
    the sidecar. Output naming is
    `<album>/<YYYY-MM-DD_HHMMSS>_<originalname>.<ext>`; files with no
    recoverable date use `0000-00-00_000000_` and are flagged in the audit.
    Note also that files differing only by a doubled extension are genuinely
    different pixels and must not be normalised together.

### Privacy, storage, and archive discipline

15. **CRITICAL.** `source-files/`, `output/`, `data/`, and every personal
    image, audio file, or sidecar must **never** be committed or pushed.
    `.gitignore` enforces this, and a tier-1 test checks `git ls-files` on
    every push. The repo is private and stays private. The single sanctioned
    exception is `tests/fixtures/` — non-personal Kodak stock sample images
    that shipped with Picture Easy, confirmed by the inventory to contain no
    people.
16. **RESOLVED.** Output is roughly 2.4 GB at the approved SHA-256 dedup key
    (687 outputs at ~3.58 MB each). It goes to `output/` in the repo folder,
    gitignored, verified empirically by planting files at every output
    subpath. That folder is inside cloud sync and must be pinned
    "always keep on this device" before a full run. The path is configured
    in `.env`, never hardcoded. There is no second fixed drive on the dev
    machine, so the "output on another drive" option does not exist.
17. The sidecar `.fpx.json` is a **complete raw dump** of every property in
    every property set (name, ID, type, raw value, decoded value), plus the
    stream inventory, plus the derived values and which source each came
    from. The point is that the EXIF mapping can be redone in ten years
    without re-parsing OLE.
18. The archive tree keeps original, derivative, and sidecar together:
    `archive/<album>/<name>.fpx`, `<name>.tif`, `<name>.fpx.json`.

## 3. Problem

1. ~1,265 family photos are locked in a dead proprietary format nothing
   modern can display.
2. Every existing converter fails outright, needs a 32-bit environment,
   watermarks the output, or throws away the metadata — and the metadata
   carries the family timeline.
3. What's needed is a repeatable, verifiable, 64-bit pipeline that decodes
   the pixels faithfully and translates every recoverable property into
   standard tags, with enough auditing to trust the result without opening
   1,265 files by hand.

## 4. Wants

- **[must] Milestone-0 inventory** (read-only spike, before any decoder
  code). **DONE** — three read-only scout agents swept all 1,265 files.
  Every "verify" item in section 2 is marked confirmed / refuted / partial
  above; the briefs are local in `source-files/inventory/` and the
  conclusions are in `DECISIONS.md`.

- **[must] Source ingestion and manifest.** Recursive, case-insensitive
  `*.fpx` copy into `source-files/`; SHA-256, size, all source paths, album
  name(s), and stream inventory per file in `source-files/manifest.json`.
  *Done when:* every `.fpx` in the source tree is in the manifest exactly
  once by hash; zero non-FPX files are ingested; `git status` shows no image
  files or data folders tracked; the source tree is byte-identical to before
  (verified by hash on a sample).

- **[must] Metadata extraction engine** — built and validated *before* the
  pixel decoder, because it is independent of it and it is the irreplaceable
  part. Custom property-set parser; timestamp logic per notes 7–9; full
  sidecar dump per note 17.
  *Done when:* sidecars exist for every file; the album ground-truth check
  runs as an automated gate; a report lists every file whose date is
  folder-derived, owner-supplied, or absent.

- **[must] 64-bit FlashPix pixel decoder.** `olefile` → highest-resolution
  storage → tile table → per-tile decode (uncompressed / single-colour /
  abbreviated JPEG with spliced tables) → stitch → crop tile padding to the
  declared size → colour-space handling → apply viewing transforms.
  *Done when:* every file decodes to an image whose dimensions match its own
  declaration after any transform, with non-black, non-uniform pixel
  statistics, no tile seams, and a visual spot-check across albums showing
  correct colour and orientation.

- **[must] Dual output.** `archive/`: TIFF, Deflate compression (not LZW),
  sRGB, full EXIF + XMP + IPTC, sidecar and original `.fpx` alongside.
  `sharing/`: JPEG quality 95, 4:4:4 chroma, sRGB, same tags, same structure
  and naming. Each output's filesystem modified time is set to the local
  `DateTimeOriginal`.
  *Done when:* every decoded file has a TIFF and a JPEG with matching
  dimensions and matching tag values; an independent read-back confirms the
  date, offset, make, model, and keywords; a sample sorts chronologically in
  a real photo app.

- **[must] Batch engine and integrity audit.** CLI with progress, resume
  (skip already-converted by hash), structured `conversion.log`, and it
  never aborts the whole run on one bad file. `audit_report.json` records
  per file: decode ok/failed with reason, dimensions vs declared, luminance
  mean and standard deviation, timestamp source, ground-truth result, tag
  read-back result, with summary counts at the top.
  *Done when:* the full run completes unattended and every source file
  appears in the audit either as converted-and-verified or as a failure with
  a stated reason. The inventory found zero corrupt or truncated files, so
  **100% conversion is a genuine target**.

- **[should] Visual QA gallery.** Static `report/index.html`: thumbnail per
  photo (free from the embedded DIB thumbnails), album badge, date, date
  source, audit status, key EXIF fields; filter by album and audit status.
  This is how sideways photos and wrong colours get caught. The approved
  dating strategy adds a requirement: the gallery must also **collect**
  dates, not just display them.
  *Done when:* opening the file shows every converted photo, filtering to
  "failed" or "undated" takes one click, and a date entered for a group
  persists back into a re-run.

- **[should, conditional] Embedded audio extraction — CLOSED.** Conditional
  on the inventory finding audio streams. It found none in any file, as
  expected for these camera models. The want is closed, not deferred.

- **[later] Standalone Windows executable.** PyInstaller bundle including
  the metadata-writing tool. Not needed for the archival run itself.
  PyInstaller support for Python 3.14 is unverified and must be checked
  before this starts.
  *Done when:* the exe runs the full pipeline on a clean Windows machine.

## 5. Non-goals

- Modifying, moving, or deleting anything under the source backup path. All
  access is read-only, and ingestion verifies it.
- Ingesting non-`.fpx` files into the repo (inventorying them is in scope;
  copying them is not).
- Authoring `.fpx` files as a product feature. **Exception:** committed
  non-personal fixtures (or a minimal test-only fixture writer) solely for
  tier-1/2 tests. Fixtures must never be family photos.
- Coefficient-level lossless JPEG re-muxing of tiles into a single JPEG.
  Possible in principle; not worth it at this resolution. Parked.
- Any web service, multi-user, or cloud component.
- Committing any personal image, sidecar, or source data to git, ever.

## 6. Integrations

- `olefile` — OLE2 container access, with custom property-set parsing on top.
- `Pillow` + `numpy` — tile decode, stitching, colour conversion, TIFF/JPEG
  output.
- **Metadata writing: ExifTool**, driven by subprocess. It is the only tool
  that reliably writes EXIF + XMP + IPTC into both TIFF and JPEG. `piexif`
  is excluded (no XMP/IPTC).
- **Metadata validation must use a different reader than the writer.**
  ExifTool writes; **`pyexiv2`** reads back. Writing and auditing with the
  same tool proves less than it appears to.
- `PyInstaller` — [later] only.
- No live external systems. Everything runs against local files, and the
  project needs no credentials of any kind.

## 7. Environment

- Target runtime: Python CLI in a venv on Windows 11, 64-bit. **Python
  3.14** — the prompt asked for a version where every dependency publishes
  Windows wheels; 3.14 was checked rather than assumed, and Pillow, numpy,
  olefile, and pyexiv2 all publish cp314 win_amd64 wheels. PyInstaller
  support for 3.14 remains unverified and gates the [later] want only.
- Dev machine: Windows 11, PowerShell 5.1 / 7. **CI runs on
  `windows-latest`.** There is no Docker target in this project.
- Source: a read-only backup tree (path in `.env`), ~495 MB of `.fpx` across
  two directory trees — one flat with no album structure, one organised into
  album folders. It may contain cloud-sync placeholders needing hydration
  before hashing; the inventory found none outstanding.
- Workspace: `source-files/` (gitignored); output per note 16.

## 8. Rules — repo, versioning, releases

- Created from the `project-scaffold` template. **Scaffold adaptation:** the
  scaffold assumes a Docker/GHCR release; this project ships no container.
  The Dockerfile and compose stubs were **deleted** at milestone 0 rather
  than left as dead stubs, and CI was retargeted to `windows-latest`. When
  the [later] exe exists, `release.yml` gains a build-and-attach job.
- Versioning: +0.0.1 bugfix, +0.1.0 minor, +1.0.0 major. Always three-part
  X.Y.Z. The version lives only in `VERSION`; `pyproject.toml` reads it
  dynamically.
- **CI owns releases end to end.** A release is: update CHANGELOG, bump
  `VERSION`, commit, push, push annotated tag `vX.Y.Z`. CI verifies tag ==
  VERSION, refuses any surviving scaffold marker, lints, tests, and creates
  the GitHub release — automatically a pre-release while 0.x. Never create
  releases or edit tags by hand.
- Releases are driven by the `/release` skill and its checklist.
- Work one milestone at a time: build → test → release → audit. Expect a
  checkpoint between milestones; never start the next one unprompted.
- Never commit secrets, runtime logs, `source-files/`, `output/`, or any
  personal image or sidecar. `CLAUDE.md` and `DECISIONS.md` are committed
  and public-safe; `source-files/` and `HANDOVER.md` are gitignored.
- Cloud-sync discipline: commit and push before switching machines; pin
  `.git` and the venv "always keep on this device"; recreate the venv on a
  new machine rather than trusting the synced copy.
- Worktrees for risky refactors or parallel sub-agent work, always outside
  the synced folder. Nothing releases from a worktree.
- Assume the session can die at any moment; follow the
  interruption-resilience rules in `CLAUDE.md`.

## 9. Rules — documentation and handover

- Documentation is a write/audit pair of sub-agents in `.claude/agents/`:
  `docs-writer` drafts README, CHANGELOG, and wiki; `docs-auditor` audits
  for leakage, accuracy against the code, and version alignment. Run the
  pair before every release.
- Use `scout` for large inputs and third-party documentation, instead of
  reading them into the main session's context.
- Run `code-auditor` on every sub-agent build branch before merging to
  `main`, and before any release.
- The wiki lives in the repo under `docs/wiki/` with `Home.md` as index.
  Public-safe from day one. Update the release-history page every release.
- `CLAUDE.md`, `DECISIONS.md`, and `HANDOVER.md` are kept current. The
  resolved "verify" items from section 2 are recorded as `DECISIONS.md`
  entries — those are exactly the hard-won facts it exists for.
- When wrapping up, run the `/wrap-up` skill.

## 10. Rules — testing and validation

The four tiers and their gates are maintained in `CLAUDE.md` so there is one
copy to keep current. In summary: tier 1 (unit, no real photos) gates every
push; tier 2 (e2e on committed non-personal fixtures) gates decoder,
metadata, and writer changes; tier 3 (sample batch over ~50 real files)
gates any merge touching decode or metadata; tier 4 (full unattended dataset
run plus an eyeball pass) gated **1.0.0**. That last gate was removed at 1.0.0
by a deliberate decision — the batch half passed, the eyeball half had not been
done, and keeping a rule the releases were stepping over was worse than
dropping it. Both halves have since passed: the eyeball pass was done after
1.2.1.

Manual testing is kept to a minimum until just before 1.0.0; the gallery is
the main manual instrument. Tiers 3 and 4 read the personal corpus and never
run in CI.
