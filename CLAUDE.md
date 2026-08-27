# fpx-converter — working notes

A 64-bit Python CLI that batch-converts Kodak DC200/DC210 `.fpx` (FlashPix)
photos from a 2000–2002 family archive into archival TIFFs and shareable
JPEGs, carrying every recoverable property into standard EXIF/XMP/IPTC plus
a complete raw-property JSON sidecar. Python 3.14 in a venv on Windows 11;
CI on `windows-latest`. No container, no service, no cloud component — it
reads local files and writes local files.

**The source `.fpx` files are the archive. Everything this tool produces is
a derivative. Nothing in this project may modify, move, or delete a source
file.**

This file and `DECISIONS.md` are committed (keep them public-safe — no real
IPs, hostnames, credentials, personal filenames, album names, or photo
captions). `HANDOVER.md` is the local-only roaming file: environment map,
machine state, session log. If it isn't present in your checkout (worktree,
clone, CI), you're missing only machine-local context, not project rules.
The full requirements live in `docs/REQUIREMENTS.md`; the wiki index is
`docs/wiki/Home.md`.

## Commands

The venv lives at a **short** path on purpose — Windows long-path support is
disabled on the dev machine and deep paths corrupt installs.

```sh
# install (dev machine)
py -3.14 -m venv C:\venvs\fpx
C:\venvs\fpx\Scripts\python.exe -m pip install -r requirements-dev.txt

# lint
C:\venvs\fpx\Scripts\python.exe -m ruff check .

# test (tiers 1 and 2)
C:\venvs\fpx\Scripts\python.exe -m pytest

# run (0.4.0)
C:\venvs\fpx\Scripts\python.exe -m fpx_converter scan        # walk source, write manifest
C:\venvs\fpx\Scripts\python.exe -m fpx_converter ingest      # copy one file per hash
C:\venvs\fpx\Scripts\python.exe -m fpx_converter verify      # re-hash the store
C:\venvs\fpx\Scripts\python.exe -m fpx_converter metadata    # dump .fpx.json sidecars
C:\venvs\fpx\Scripts\python.exe -m fpx_converter check-dates # album ground-truth report
C:\venvs\fpx\Scripts\python.exe -m fpx_converter thumbnail   # extract embedded DIBs
C:\venvs\fpx\Scripts\python.exe -m fpx_converter convert     # TIFF + JPEG + sidecar
```

`check-dates` reports by default and only fails under `--strict`; on this
corpus the import stamp misses 7 of 9 dated albums, which is *why* it is not
trusted as a capture date, so a failing gate is the expected state rather
than a regression. `convert` takes `--limit` and `--dry-run`.

`scan` takes `--source` to override `FPX_SOURCE_ROOT` without a `.env`.
Both `--manifest` and `--dest` refuse any path inside the source root — the
read-only rule is enforced in code, not left to the caller.

External tool: **ExifTool** (metadata writer), installed with
`winget install --id OliverBetz.ExifTool`. It is not a Python package and is
not in `requirements.txt`. Do not try to fetch it from a URL — see
`DECISIONS.md`.

## Testing tiers

| Tier | What it is | Gates |
|------|-----------|-------|
| 1. Unit | Property-set parser against hand-built byte fixtures; tile-table parsing; JPEG table + tile reassembly; timestamp and offset logic; naming scheme; collision handling. No real photos, no ExifTool, no source archive. | Every push (CI) |
| 2. e2e | Full pipeline on the committed non-personal FPX fixtures → TIFF + JPEG → independent read-back of every tag | Any change to the decoder, metadata engine, or output writer |
| 3. Sample batch | `scripts/tier3_sample.py` — ~50 real files spanning every album, every declared size, both colour spaces and all four transform outcomes: convert, pyexiv2 read-back, pixel stats, both thumbnail oracles, album ground-truth date check. Exits non-zero on any of them and prints its own sample composition | Before merging any branch that touches decode or metadata |
| 4. Full dataset | Unattended run over all files; audit report shows zero unexplained failures; ~20 files eyeballed in a real photo app for date, orientation, and colour | **1.0.0.** Until it passes, every release stays a pre-release |

Verify before claiming: tier 1 always; the matching higher tier when its
trigger applies. **"It decoded" is not "it decoded correctly"** — colour and
orientation need eyes at least once per variant.

**The two oracles are not interchangeable.** `compute_image_correlation`
folds both images to greyscale, so it witnesses framing and orientation and
says *nothing* about colour. Never cite it in support of a colour claim —
that is exactly how two solidly green files passed every check in the
project. Colour is `chroma_agreement` in `scripts/tier3_sample.py`, which
compares `R-G` and `B-G` against the same embedded DIB. **Correlating the R,
G and B channels separately is not a colour check either**: Pearson
correlation is invariant under any per-channel affine map, so a wrong gain or
a wrong neutral point scores as well as a correct decode. That version was
written, shipped and caught. Whatever the metric, a 96-pixel thumbnail is
evidence and not sight; tier 4 still needs eyes.

Tiers 3 and 4 read the personal corpus and therefore **never run in CI**.
They run locally, and their outputs are gitignored. CI's job is tier 1.

## Milestone plan

The approved plan, ticked as milestones ship. This survives context loss;
conversation memory doesn't. Approved changes to the plan get edited here;
mid-project ideas that aren't in the plan go to HANDOVER.md open items.

- [x] **0.1.0 — Scaffold + ingestion.** Milestone 0 (this configuration),
      then the read-only source walk, hash cascade, `manifest.json`, and the
      `.fpx` copy into `source-files/`. Commit the non-personal FPX fixtures.
- [x] **0.2.0 — Metadata engine.** Custom property-set parser for all 10
      property sets plus the 2 extension storages. Full raw sidecar dump.
      Timestamp resolution per the approved dating strategy. Folder-name
      ground-truth check (a report by default; `check-dates --strict` is the
      gate, opt-in because failing is the expected result here).
- [x] **0.3.0 — Pixel decoder.** Tile table at +28, per-tile JPEG splice /
      raw / single-colour fill, stitch, crop to the declared size, per-file
      colour space, `0x10000003` transform (90° CCW rotation and crops).
      Thumbnail extractor as correctness and orientation oracle — it earned
      its keep twice, confirming both the rotation and the crop geometry.
- [x] **0.4.0 — Dual output.** Deflate TIFF + q95 4:4:4 JPEG, ExifTool
      writes, pyexiv2 read-back validation, filesystem mtime, naming scheme.
      Shipped as one combined 0.4.0 pre-release: all three milestones were
      built as a branch stack and audited afterwards, so the intermediate
      states were never CI-green and were never released. **Shipped
      2026-08-27** after three audit rounds; the third found that the colour
      check added by the second could not detect colour.
- [ ] **0.5.0 — Batch engine + audit.** CLI with resume-by-hash,
      `conversion.log`, `audit_report.json`; never aborts on one bad file.
- [ ] **0.6.0 — QA gallery.** `report/index.html`, thumbnails free from the
      embedded DIBs, filters by album and audit status, **plus the per-group
      date-entry affordance the dating strategy requires**.
- [ ] **1.0.0 — Full dataset run** plus tier-4 eyeball verification.
- [ ] *later* — PyInstaller exe; re-verify 3.14 wheel support first, then
      add the build-and-attach job to `release.yml`.

Two wants from the original requirements changed after the milestone-0
inventory measured the corpus: the **audio-extraction want is CLOSED** (zero
audio streams exist in any file), and the colour-science milestone shrank
(99.7% of files are NIF RGB, not PhotoYCC) with that budget moving to the
viewing-transform work, which turned out to be real. **Small is not the same
as safe:** the 2 PhotoYCC files were being converted twice and shipped
solidly green with 42% of their pixels clipped to zero, past every automated
check the project had.

## Project-specific binding rules

These are conclusions the milestone-0 inventory paid for. Each has a full
entry in `DECISIONS.md`; violating one silently corrupts an irreplaceable
archive, so they are rules, not preferences.

- **The source tree is read-only.** Never write, move, rename, or delete
  under it. Ingestion verifies the tree is byte-identical afterwards.
- **Never commit personal media.** `tests/fixtures/` is the only sanctioned
  exception, and only for non-personal stock images. A tier-1 test enforces
  this against `git ls-files`.
- **There is no capture date in this corpus.** The FlashPix capture-date
  property is absent from every file. The only timestamp is an import-batch
  stamp. Never write it to `DateTimeOriginal` — it goes to
  `DateTimeDigitized` / `xmp:CreateDate`, and `DateTimeOriginal` is written
  only where a date is independently defensible.
- **"Defensible" means a single day.** A folder naming a year, a span, a
  season or a month does not date a photograph, and EXIF has no way to say
  "sometime in 2001" — writing one means naming a day. The first
  implementation took the start of the range and borrowed the import stamp's
  clock, giving 151 of 687 files a fabricated capture moment precise to the
  second. Coarse folder dates are still useful and still kept, as
  `sort_datetime`: they drive the mtime and the filename prefix, where
  unknown components are written as zeros (`2001-00-00_000000_`). A prefix
  is a browsing affordance; `DateTimeOriginal` is a claim.
- **A folder name somebody typed outranks any date we can derive.** A
  descriptive source folder keeps its name as the album whatever the photo's
  date, nested under the year if the name gives one and sitting beside the
  year folders if it does not. Only a folder whose name says nothing — the
  tool-generated and placeholder names in `layout.NON_DESCRIPTIVE_ALBUMS`,
  extensible per-archive through `FPX_NON_DESCRIPTIVE_ALBUMS` in `.env` — is
  replaced by
  `<year>/<year> <Month>`, and that year-month can only come from the import
  stamp, so it is a browsing affordance exactly like the filename prefix and
  never a claim. A file usually belongs to several albums; it is filed under
  the most descriptive one, **not the first listed** — taking the first put 52
  photos of one Christmas under a folder named after a zip file and cost them
  the day-precise date their real album gave for free.
- **`archive/` keeps the full frame; `sharing/` gets the crop.** 70 files
  carry a crop somebody framed in the Kodak software — 56 axis-aligned, and
  14 riding along with a 90° rotation. Both the captured frame and the
  intended composition are worth having, and the two output trees have
  exactly those jobs. Deriving the crop box needs `ResultAspectRatio` as
  well as the matrix — see `DECISIONS.md`; without it the box appears to
  fall outside the image. **A matrix's shape does not tell you whether it
  crops**: rotation and crop are independent, and within the classifier's
  tolerance an "identity" matrix can still carry one. The box is the
  authority, and where it cannot be resolved the file is reported as
  unsupported rather than assumed uncropped.
- **Stored FILETIMEs are LOCAL wall-clock time, not UTC.** Do not
  timezone-convert them. The time-zone map governs which `OffsetTime*` value
  is written, nothing more.
- **Dedup keys on whole-file SHA-256**, not the pixel hash. Roughly 146
  pixel-identical output pairs are the expected consequence — the audit must
  not flag them as faults.
- **Validate with a different tool than the one that wrote.** ExifTool
  writes; pyexiv2 reads back. Writing and auditing with the same tool proves
  less than it appears to.
- **Never hardcode 1152×864.** Read each file's declared size and use it
  everywhere (tile grid, padding crop, audit).
- **Never call Pillow's `FpxImagePlugin` in the batch path.** It fails on
  the overwhelming majority of these files and *hard-crashes CPython* on
  some. It is usable only as an out-of-process correctness oracle.
- **Filenames are the only human-authored content in the archive.** Within a
  hash group, prefer the human-authored name over a camera-generated twin,
  and record every contributing path in the sidecar. Losing a filename loses
  a caption permanently.
- **Do not normalise doubled file extensions.** Files differing only by a
  repeated extension can be genuinely different pixels.
- **Keep every path short.** Windows long-path support is disabled on the
  dev machine; deep paths corrupt installs and writes.

## Worktrees (parallel or risky work)

- Use a worktree for: risky refactors/spikes, parallel sub-agent build work,
  anything that would leave `main` dirty across sessions. Plain
  single-threaded milestone work doesn't need one.
- For sub-agent work, **prefer the harness's built-in worktree isolation** —
  it creates and cleans up the worktree itself, so there's no lifecycle to
  manage.
- Manual, long-lived worktrees live **outside OneDrive**:
  `C:\worktrees\fpx-converter\<branch>` (OneDrive sync fights `.git` locks
  and thrashes on build output). Never create one inside the OneDrive
  project folder. If one is ever orphaned, run `git worktree prune`.
- `CLAUDE.md` and `DECISIONS.md` are committed, so every worktree has the
  project rules. `HANDOVER.md`, `source-files/`, and `.env` do NOT follow —
  copy `.env` in manually only if the work needs it.
- Finish by merging the branch back and `git worktree remove` — a worktree
  is never the long-lived copy, and nothing releases from one.

## Sub-agents and delegation

Defined in `.claude/agents/` (committed): `docs-writer` (fast model) drafts
README/CHANGELOG/wiki, `docs-auditor` (stronger model) adversarially audits
docs before release, `scout` digests large `source-files/` inputs and
third-party API docs into briefs, and `code-auditor` reviews branch diffs
against this project's contract (tier triggers, test fidelity, leakage)
before they merge to `main` — run it on every sub-agent build branch and
before any release with code changes; generic bug-hunting stays with the
built-in `/code-review`. Model choices live in those files only — update
them there when models change, not in prose rules.

Delegation policy: the main agent may spawn as many sub-agents as the task
warrants — parallel searches, isolated worktree builds, independent
reviews — without asking first. Delegate when it protects the main session's
context (large reads → `scout`) or when work parallelizes cleanly; don't
delegate trivially serial work. Model choice for ad-hoc sub-agents is the
main agent's call by task weight: cheap/fast for mechanical or first-draft
work, the strongest available for adversarial review and anything that gates
a release. The only hard pins are the docs pair above, where the asymmetry
(fast drafts, stronger audit) IS the policy. Milestone checkpoints still
apply: delegation never crosses a milestone boundary Stevie hasn't
approved.

**Sub-agents inherit the read-only-source rule.** Any agent pointed at the
source archive gets it in its prompt, explicitly.

## Interruption resilience (usage limits)

Sessions die mid-task: the 5-hour usage window, a crash, a machine switch.
The remaining budget is NOT readable from inside a session (only Stevie can
see `/usage`), so the system is crash-safety, not rationing — work so that an
interruption at any moment costs minutes, not hours:

- Small verifiable increments. Never let more than ~30 minutes of work sit
  unpushed; commit and push after every green step. `wip:` commits with red
  tests are fine on a branch — an unpushed working tree is the only
  unacceptable state.
- Run `/checkpoint` (WIP commit+push + HANDOVER resume note, ~2 min) after
  each meaningful unit of work, before any large sub-agent fan-out or long
  autonomous stretch, and immediately if Stevie mentions limits/credits.
- Announce before starting an unusually large fan-out or long autonomous
  run, so Stevie — who can see the meter — has the chance to defer it. If
  he says the window is nearly spent, switch to small serial steps with a
  checkpoint after each.
- Cold-start resume: HANDOVER.md Current state (`Next action:` line), then
  `git log --oneline -10` + `git status`. Same machine: `claude --continue`
  also restores the conversation, but the files are the contract.
- Economy comes from the delegation policy (cheap models for mechanical
  work, `scout` for big reads) — never from skipping verification tiers or
  leaving checklists unticked.

A full-corpus run is itself an interruption risk: the batch engine resumes
by hash, so a killed run costs the current file, not the batch.

## Releases

Every release is driven end to end by the `/release` skill, which holds the
canonical release checklist and ends by pasting it into the conversation
with every item ticked. Ambient invariants (these hold even outside a
release): CI owns releases — never `gh release create`, never edit tags by
hand; if CI fails, no partial release exists — fix and re-tag. Increments:
+0.0.1 bugfix / +0.1.0 minor / +1.0.0 major, always three-part X.Y.Z.

This project publishes **no container image**. There is no compose pin to
bump — that scaffold step does not apply here. Releases stay pre-releases
until tier 4 passes at 1.0.0.

## House conventions

- Commits end with a `Co-Authored-By: Claude <Model> <noreply@anthropic.com>`
  trailer naming the model that did the work (currently Opus 5); git
  identity is repo-local `Stevie <sremich@gmail.com>`.
- The version lives ONLY in `VERSION`; `pyproject.toml` reads it dynamically
  and language-level copies are never hand-edited. CI refuses tags that
  disagree, and a tier-1 test refuses a second source of truth.
- Never commit secrets, tokens, runtime logs, `source-files/`, `output/`, or
  any personal image or sidecar. Credentials arrive via `.env`, not chat.
  This project talks to no external system and needs no credentials at all.
- Dependencies are pinned exactly. This pipeline runs once over an
  irreplaceable archive; a silent upstream change in a decoder or a metadata
  writer is a correctness risk, not a convenience one.
