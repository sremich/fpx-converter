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

# run (0.6.0)
C:\venvs\fpx\Scripts\python.exe -m fpx_converter scan        # walk source, write manifest
C:\venvs\fpx\Scripts\python.exe -m fpx_converter ingest      # copy one file per hash
C:\venvs\fpx\Scripts\python.exe -m fpx_converter verify      # re-hash the store
C:\venvs\fpx\Scripts\python.exe -m fpx_converter metadata    # dump .fpx.json sidecars
C:\venvs\fpx\Scripts\python.exe -m fpx_converter check-dates # album ground-truth report
C:\venvs\fpx\Scripts\python.exe -m fpx_converter thumbnail   # extract embedded DIBs
C:\venvs\fpx\Scripts\python.exe -m fpx_converter convert     # batch run: TIFF + JPEG + audit
C:\venvs\fpx\Scripts\python.exe -m fpx_converter gallery     # QA page over a finished run

# desktop front end (1.1.0) -- needs requirements-gui.txt, or use the exe
C:\venvs\fpxgui\Scripts\python.exe -m fpx_gui
```

`check-dates` reports by default and only fails under `--strict`; on this
corpus the import stamp misses 7 of 9 dated albums, which is *why* it is not
trusted as a capture date, so a failing gate is the expected state rather
than a regression. `convert` takes `--limit`, `--dry-run`, `--no-resume`, `--progress` (mirror
the per-file log lines onto stdout) and `--stop-file PATH` (stop politely at
the next photo boundary and still write the audit report — the marker is only
honoured if it is newer than the run, so a stale one cannot wedge a
destination);
format and framing are independent: `--archive-format`, `--archive-framing`,
`--sharing-format`, `--sharing-framing`, `--no-archive`, `--no-sharing`.

A run writes only the images it was asked for; `--source-copy` and `--sidecar`
add the `.fpx` copy and the `.fpx.json` raw-property dump, both off by default.
`--folder-scheme album|year|year-month|flat|custom` shapes the output tree
(`custom` reads `--folder-template`, e.g. `{year}/{album}`), and
`--name-template` sets the filename, defaulting to
`{year}-{month}-{day}_{time}_{name}`. A filename pattern must contain `{name}`;
a folder pattern may use only `{year}`, `{month}` and `{album}`. Both are
validated once before a run, and changing either invalidates a resume.

`scan` takes `--source` to override `FPX_SOURCE_ROOT` without a `.env`.
Both `--manifest` and `--dest` refuse any path inside the source root — the
read-only rule is enforced in code, not left to the caller. The batch engine
never aborts on a bad file and resumes by hash, so a killed run costs the file
in flight, not the batch.

External tool: **ExifTool** (metadata writer), installed with
`winget install --id OliverBetz.ExifTool`. It is not a Python package and is
not in `requirements.txt`. Do not try to fetch it from a URL — see
`DECISIONS.md`.

## Testing tiers

| Tier | What it is | Gates |
|------|-----------|-------|
| 1. Unit | Property-set parser against hand-built byte fixtures; tile-table parsing; JPEG table + tile reassembly; timestamp and offset logic; naming scheme; collision handling; batch engine; resume state; output control. Also the desktop front end's Qt-free half — argument building, log parsing, the summary, the cancellation worker against a fake child process, and the two tests that fail if the window stops calling `ensure_outside_source`. No real photos, no ExifTool, no source archive. | Every push (CI) |
| 2. e2e | Desktop front end driving a real conversion through a real child process, including a cancellation that must still leave an audit report. Full pipeline on 40 committed person-free FPX fixtures (both colour spaces, six sizes, one crop, one camera name) → TIFF + JPEG → independent read-back of every tag; chroma oracle and four mutation tests (wrong neutral, swapped channels, desaturated, double-converted) | Any change to the decoder, metadata engine, output writer, or batch engine |
| 3. Sample batch | `scripts/tier3_sample.py` — 50 real files spanning every album, every declared size, both colour spaces and all four transform outcomes: convert, pyexiv2 read-back, pixel stats, both thumbnail oracles, album ground-truth date check. Exits non-zero on any of them and prints its own sample composition | Before merging any branch that touches decode, metadata, or batch logic |
| 4. Full dataset | Unattended batch run over all files via the batch engine; audit report shows zero unexplained failures; 2 PhotoYCC files eyeballed in a real photo app for colour correctness | The batch half **passed at 1.0.0** (687/687, `complete: true`). The eyeball half is outstanding and is a strong recommendation, not a release gate — that was Stevie's call, taken knowingly |

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
They run locally, and their outputs are gitignored. CI's job is tiers 1 and 2.

**The colour oracle lives in `fpx_converter/oracles.py`, not in the tier-3
script**, so tiers 1, 2 and 3 run the same code rather than three copies that
drift. Tier 2 exercises it both ways: the fixtures must pass it, and a
deliberately broken decode must *fail* it — wrong PhotoYCC neutral, swapped
red and blue, fully desaturated. All three are mutations the previous
per-channel oracle passed, which is why the pair of directions is the test
and not just the first half.

**Rotation has no fixture and cannot get one.** All 22 rotated files in the
archive contain people. Tier 3 is the only automated cover for the branch
that carried the 0.4.0 dropped-crop defect; see `tests/fixtures/README.md`.

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
- [x] **0.5.0 — Batch engine + audit.** CLI with resume-by-hash,
      `conversion.log`, `audit_report.json`, `run-state.json`; never aborts
      on one bad file. Output format and framing decoupled for independent
      control. 36 new person-free archive fixtures for CI PhotoYCC coverage.
- [x] **0.6.0 — QA gallery.** `report/index.html`, thumbnails free from the
      embedded DIBs, filters by album and audit status, **plus the per-group
      date-entry affordance the dating strategy requires** — the gallery
      renders the JSON for a person to save as `album-dates.json`, `convert`
      reads it back, and that round trip is the only route by which a
      defensible capture date enters this archive. Shipped together with 0.5.0 as one combined **0.6.0
      pre-release on 2026-08-27**: both milestones were built and audited as
      a single unit, so the intermediate state was never separately
      released.
- [x] **1.0.0 — Full dataset run.** The whole archive in one unattended
      pass: 687 converted, 0 failed, 0 with warnings, `complete: true`,
      `unexplained_failures: 0`, 641 s. Every predicted number matched — 70
      cropped outputs, 609/56/22 transforms, 617/68/2 date sources — and the
      "roughly 146 pixel-identical pairs" estimate was replaced by the
      measurement, 251 files in 120 groups. **Shipped 2026-08-27.** The
      tier-4 eyeball half is outstanding: Stevie chose to ship on the
      automated gate, so it is a recommendation rather than a gate. It is
      still worth doing — `output/full-1.0.0/report/index.html` is the way
      in, and the 2 PhotoYCC files are the ones that matter.
- [x] **1.1.0 — Desktop app.** A GUI so somebody who does not use a
      terminal can run this: pick a source folder, pick a destination, watch
      progress, read the audit result. It **wraps the CLI rather than
      reimplementing it** — the conversion logic has one home and one set of
      tests, and the GUI is a front end over the same commands. Ships as a
      single Windows executable alongside it. Folded together with the
      PyInstaller work, because they are the same packaging problem.
      **Shipped 2026-08-27.** PySide6 6.11.2 (a `cp310-abi3` wheel, so it
      runs on 3.14) and PyInstaller 6.22.2; the release workflow builds the
      exe, converts two fixtures *through it*, and only then creates the
      release — a `--version` call cannot see a missing `pyexiv2` binary, and
      a build that fails must not leave a published release with nothing in
      it. Cancellation needed two mechanisms rather than one; see
      `DECISIONS.md`.
- [x] **1.2.0 — Names, folders, and what a run writes.** Post-1.1.0 work
      driven by Stevie running the packaged application: ExifTool no longer
      opens a console window per photograph, the unreadable dropdowns are
      fixed, the app's six output controls became three exclusive choices,
      the `.fpx` copy and the sidecar became opt-in, and both the filename and
      the folder arrangement became user-definable — `--name-template`,
      `--folder-scheme`, `--folder-template`, with a live two-photograph
      preview in the window. **Shipped 2026-08-27.** 16 rules are verified by
      `scripts/mutation_check.py`, which breaks each one and requires the test
      named for it to fail. Pre-release audit found two real bugs — adding
      `--source-copy` to a finished destination wrote nothing, and a new
      trailing-character strip changed the default filename — both fixed before
      the tag.

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
- **The repository is for the software; the photographs are not.** The
  archive and everything derived from it — images, sidecars, manifests,
  logs, audit reports — is local-only working material for building and
  testing the tool. Nothing personal goes to GitHub: no photograph, no album
  name, no human-authored filename, no caption. `tests/fixtures/` is the
  only sanctioned exception, and only for images that contain **no people**
  — the Kodak stock samples, plus any archive photo confirmed person-free by
  eye and renamed to a neutral stem. Two tier-1 tests enforce this, and they
  list `--cached --others --exclude-standard`, not plain `git ls-files`: a
  brand-new file is not in the index, so the narrower listing read a leak as
  clean right up until the commit that added it — which is how one got
  pushed.
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
- **A folder is a browsing affordance; a filename's date prefix tracks what
  is claimable; `DateTimeOriginal` is the only claim.** All three now take
  patterns, and they do *not* share their date values. `--folder-scheme` and
  `{year}`/`{month}` in a folder pattern may use an album name or the import
  stamp — the licence `output_folder` has always taken. `--name-template`'s
  date fields come from `format_date_prefix` and zero anything undefensible.
  Reusing the filename's fields for folders was written and caught: a custom
  `{year}/{album}` filed almost everything under `0000/` while
  `--folder-scheme year` — the same word — correctly said `2002/`. Folder
  patterns therefore have their own three-field vocabulary (`{year}`,
  `{month}`, `{album}`), and asking for `{day}` or `{time}` in one is refused
  rather than answered. `year-month` never manufactures a month either: an
  album naming only a year files directly under the year.
- **A run that renames or refiles is not the same run.** `run-state.json`
  records the filename pattern and the folder arrangement beside the output
  specs, and a change to any of them invalidates the resume. Resuming across
  one would skip nothing and move nothing, leaving half a tree under the old
  shape and half under the new with nothing recording which was which.
- **A conversion writes only the images asked for.** The `.fpx` copy and the
  `.fpx.json` sidecar are opt-in (`--source-copy`, `--sidecar`). They were
  written on every conversion until 1.2.0, so asking for one photograph
  produced four files. The source archive is read-only and still there, so the
  copy duplicates something that was never at risk, and the sidecar is
  re-derivable with `metadata`.
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
  a caption permanently. This is why `--name-template` **requires `{name}`**:
  a pattern that drops it throws away the only thing a person wrote, for
  every file it renames, and unlike a wrong date it cannot be recovered by
  re-reading the source.
- **Do not normalise doubled file extensions.** Files differing only by a
  repeated extension can be genuinely different pixels.
- **The desktop app wraps the CLI; it never reimplements it.** Every
  conversion the window starts is `fpx_converter` running as a child process
  with the arguments a person would have typed. Nothing in `fpx_gui` decodes a
  pixel, writes a tag, or decides where a file lands, and the read-only rule
  reaches it as a *call* to `config.ensure_outside_source` rather than a
  second implementation of it. Exactly two tier-1 tests fail when that call is
  replaced by a local copy of the same check — one at `fpx_gui/options.py`,
  one at the window — and that count is measured by mutation, not asserted.
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
bump — that scaffold step does not apply here. Releases were pre-releases
through 0.x; from 1.0.0 they are full releases. The tier-4 eyeball pass is
**not** a release gate — it was one until 1.0.0, and rather than keep a rule
the releases were stepping over, the rule was removed deliberately.

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
