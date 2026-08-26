# Release history

One entry per release, added as part of the `/release` checklist. Each entry
says what the release contains and — more usefully — **what it is safe to be
trusted for**, because until 1.0.0 every release is a pre-release that has
not been verified against the full dataset.

See [`CHANGELOG.md`](../../CHANGELOG.md) for the itemised change list.

## Verification status

| Tier | What it proves | Passing as of |
|---|---|---|
| 1. Unit | Parsers, reassembly, timestamp and naming logic | *not yet released* |
| 2. e2e | Full pipeline over the committed non-personal fixtures | *not yet reached* |
| 3. Sample batch | ~50 real files across every album and variant | *not yet reached* |
| 4. Full dataset | Unattended run over the whole corpus, plus an eyeball pass | *not yet reached — gates 1.0.0* |

## Releases

*No releases yet.* The first will be **0.1.0** — scaffold configuration and
source ingestion. It will be a pre-release, and it will be trustworthy only
for building a manifest: it converts nothing.
