# Release history

One entry per release, added as part of the `/release` checklist. Each entry
says what the release contains and — more usefully — **what it is safe to be
trusted for**, because until 1.0.0 every release is a pre-release that has
not been verified against the full dataset.

See [`CHANGELOG.md`](../../CHANGELOG.md) for the itemised change list.

## Verification status

| Tier | What it proves | Passing as of |
|---|---|---|
| 1. Unit | Parsers, reassembly, timestamp and naming logic | 0.1.0, for the code that exists so far — naming, manifest, config, and the read-only proof |
| 2. e2e | Full pipeline over the committed non-personal fixtures | 0.1.0, for the ingestion path only — scan, manifest, copy, re-hash. There is no TIFF/JPEG output to test yet |
| 3. Sample batch | ~50 real files across every album and variant | *not yet reached* |
| 4. Full dataset | Unattended run over the whole corpus, plus an eyeball pass | *not yet reached — gates 1.0.0* |

## Releases

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
