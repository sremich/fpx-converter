# fpx-converter wiki

The repo is **private**, so the wiki lives here in `docs/wiki/` rather than
in GitHub's wiki section. Everything here is public-safe: no personal file
names, album names, captions, or absolute paths to the archive.

## What this project is

A 64-bit Python CLI that batch-converts Kodak DC200/DC210 `.fpx` (FlashPix)
photos from a 2000–2002 family archive into archival TIFFs and shareable
JPEGs, carrying every recoverable property into standard EXIF/XMP/IPTC plus
a complete raw-property JSON sidecar.

It exists because nothing modern opens `.fpx`, and every off-the-shelf
converter either renders black, needs a 32-bit environment, watermarks the
output, or silently discards the metadata — and the metadata is what carries
the family timeline.

## Map of the documentation

| Document | What it holds | Committed? |
|---|---|---|
| [`README.md`](../../README.md) | What it is, install, usage, current status | yes |
| [`docs/REQUIREMENTS.md`](../REQUIREMENTS.md) | The full requirements, with every starting hypothesis marked confirmed or refuted | yes |
| [`CLAUDE.md`](../../CLAUDE.md) | Working notes: commands, testing tiers, milestone plan, binding project rules | yes |
| [`DECISIONS.md`](../../DECISIONS.md) | Append-only record of decisions and hard-won lessons | yes |
| [`CHANGELOG.md`](../../CHANGELOG.md) | Keep-a-Changelog history | yes |
| [Release history](Release-History.md) | Per-release notes and what each one is safe to be trusted for | yes |
| `HANDOVER.md` | Roaming agent context: environment map, machine state, session log | **no** — gitignored, local only |
| `source-files/` | The archive copy, the inventory briefs, the original prompt | **no** — gitignored, local only |

## The five things a newcomer gets wrong

Each of these was measured against all 1,265 files during the milestone-0
inventory, and each has a full entry in [`DECISIONS.md`](../../DECISIONS.md).

1. **There is no capture date in this corpus.** The FlashPix capture-date
   property is absent from every file. The only timestamp is an
   import-batch stamp that disagrees with folder-name ground truth on 7 of 9
   dated albums — once by a whole year. Dates come from folder names plus an
   owner review pass, not from the file.
2. **The stored timestamps are local wall-clock time, not UTC.** Treating
   them as UTC and converting would move a fifth of the corpus onto the
   wrong calendar day.
3. **The colour space is NIF RGB, not PhotoYCC** — on 1,261 of 1,265 files.
   The colour-science work everyone budgets for mostly isn't there.
4. **Pillow's `FpxImagePlugin` cannot be the pixel path.** It fails on 1,224
   of 1,265 files and hard-crashes the interpreter on two of them. The
   custom decoder is primary; the plugin is an out-of-process oracle.
5. **Viewing transforms are real.** 45 files carry a genuine 90° CCW
   rotation that a naive tile decoder would ignore, emitting them sideways.

## Format notes worth keeping

- `.fpx` is an OLE2 compound document. `Data Object Store 000001` holds a
  resolution pyramid; the highest index is full resolution.
- The tile table is a 64-byte preamble followed by 16-byte little-endian
  records, and **tile offsets are relative to byte 28 of the Data stream** —
  not to its start.
- JPEG tiles are *abbreviated*: SOI/SOF0/SOS/EOI with no tables. The tables
  live in the `Image Contents` property set, and the table ID is chosen
  **per tile**. Reassembly is `tables[:-2] + tile[2:]`; the table blob's
  trailing EOI must be stripped.
- Every file embeds a 96-pixel thumbnail as a bottom-up 24-bit DIB. It is
  free gallery material and an independent orientation oracle — but it is a
  DIB, so writing those bytes to a `.jpg` produces garbage.

## Conventions

- The version lives only in `VERSION`. CI refuses a tag that disagrees, and
  a tier-1 test refuses a second source of truth.
- CI owns releases: push a `vX.Y.Z` tag and nothing else. Releases stay
  pre-releases until the tier-4 full-dataset verification passes at 1.0.0.
- This project publishes no container image and talks to no external system.
- No personal image, sidecar, or source file is ever committed.
  `tests/fixtures/` — non-personal Kodak stock samples — is the only
  exception, and a tier-1 test enforces the rule on every push.
