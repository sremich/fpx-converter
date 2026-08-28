# Testing

Four tiers. Two of them run anywhere; two of them need a private photo archive
and can never run in CI or on a contributor's machine. That is a designed
property of the project, not a gap — the corpus this tool was built for is a
family archive that cannot be published.

## The tiers

| Tier | What it is | When it runs |
|---|---|---|
| **1. Unit** | The property-set parser against hand-built byte fixtures; tile-table parsing; JPEG table and tile reassembly; timestamp and offset logic; naming and folder schemes; collision handling; the batch engine, resume state and output control. Plus the desktop front end's Qt-free half — argument building, log parsing, the summary, and the cancellation worker against a fake child process. No real photographs, no ExifTool, no archive. | Every push (CI) |
| **2. End-to-end** | The full pipeline over the committed person-free `.fpx` fixtures — scan through convert, both colour spaces, TIFF and JPEG out, then an independent read-back of every tag. Includes the colour oracle in both directions and the four mutation decodes below. Also the desktop front end driving a real conversion through a real child process, including a cancellation that must still leave an audit report. | Any change to the decoder, metadata engine, output writer, or batch engine |
| **3. Sample batch** | `scripts/tier3_sample.py` — a sample of real archive files spanning every album, every declared size, both colour spaces and all four transform outcomes. Converts through the real writer, re-reads the output with a third metadata parser, takes pixel statistics, runs both oracles, and checks album ground-truth dates. Exits non-zero on any of them and prints its own sample composition. | Before merging any branch touching decode, metadata, or batch logic — **locally only** |
| **4. Full dataset** | An unattended batch run over the entire archive, with the audit report showing zero unexplained failures — *and* a person opening the converted photographs in a real photo application and checking colour and orientation by eye. | **Locally only.** Both halves have passed on the reference corpus |

**Tiers 3 and 4 read a private archive and therefore never run in CI.** Their
outputs are gitignored. CI's job is tiers 1 and 2, and a green pull request
means those two passed and nothing more. If you have your own `.fpx` corpus,
tier 3 is worth pointing at it; if you do not, the tier is simply unavailable
and that is expected rather than broken.

Tier 4's eyeball half deserves its own sentence, because it is the one people
assume is ceremony. **"It decoded" is not "it decoded correctly."** The defect
that made this rule was two files that came out solidly green with 42% of their
pixels clipped to zero, and passed every automated check the project had at the
time. What caught it was looking. Any change to the decoder, the colour
conversion, or the viewing transform puts that verification back to outstanding.

## The two oracles are not interchangeable

Both compare a decode against the thumbnail embedded in the same file by the
software that wrote it. They witness different things.

- **`thumbnail.compute_image_correlation`** folds both images to greyscale
  before correlating. It witnesses framing, orientation and crop, and says
  **nothing whatever about colour**. It is also aspect-blind: it resizes both
  images to a square 64×64. Its scores are high enough (worst 0.981 on this
  corpus) to look like a general "the image is right" check. It is not one.
  Never cite it in support of a colour claim.
- **`oracles.chroma_agreement`** is the colour check. It compares `R-G` and
  `B-G` against the same thumbnail, dividing out the luma the greyscale oracle
  already covers, and reports correlation, scale and offset separately because
  each catches a different fault.

**Correlating the R, G and B channels separately is not a colour check.**
Pearson correlation is invariant under any per-channel affine map, so a wrong
gain or a wrong neutral point scores exactly as well as a correct decode. That
version shipped: it passed a decode with the wrong PhotoYCC neutral, passed a
fully desaturated decode, and passed one with red and blue swapped.

The colour oracle lives in `fpx_converter/oracles.py` and not in the tier-3
script, so tiers 1, 2 and 3 exercise the *same* code rather than three copies
that drift.

**Tier 2 exercises it in both directions**, which is the actual test: the
fixtures must pass it, and four deliberately broken decodes must *fail* it —
wrong PhotoYCC neutral, swapped red and blue, fully desaturated, and
double-converted. The first three are mutations the old per-channel oracle
passed. A check that has only ever been run against correct input has not been
shown to be able to fail.

Known blind spot, measured rather than assumed: chroma is `R-G` and `B-G`, so a
fault confined to the **green** channel moves both signals together and largely
cancels. A green gain of ×1.10 trips no gate on any file in the reference
corpus, while a comparable red gain trips 39% of them. A green-only fault
belongs to tier 4 and nothing before it will catch one.

## Mutation checking

`scripts/mutation_check.py` breaks each load-bearing rule on purpose and
requires the test named for that rule to go red. **It currently covers 17
rules** — filename and folder pattern validation, path-traversal guards,
reserved device names, the opt-in extras, the crop-goes-to-`sharing/` rule, and
the four conditions that must invalidate a resume.

The point is the naming. Each mutation names the test file that is supposed to
catch it, so a pass says the *right* test caught it and not merely that
something somewhere went red. That distinction was earned: the first version of
the script passed an unsupported argument to the test runner, every run died on
the argument error, every mutation was scored as caught, and it reported nine
catches it had not made. It now refuses to count a red run that names no failing
test.

It needs the GUI virtualenv, because some of the rules are caught by the
window's tests. Run it on a clean tree — it restores every file it touches,
including on failure, but a crash mid-run on a dirty tree is hard to tell from
an edit. It also takes a lock, because two concurrent runs read each other's
mutations and one of the ways that goes wrong is a false catch.

## Fixtures, and the holes in them

`tests/fixtures/` holds real `.fpx` files so that tiers 1 and 2 run against the
format as it actually occurs rather than against hand-built bytes alone. See
`tests/fixtures/README.md` for the full inventory, the licensing, and the
screening rule.

The screening rule is absolute: **every committed fixture contains no people.**
That rule outranks coverage, which is what it has to mean when obeying it is
expensive — and it has been expensive. Three fixtures were deleted on
2026-08-27 when a full-resolution review before this repository went public
found a figure standing behind foliage in the background of all three.

What the remaining set covers between them: both colour spaces, six of the
seven declared sizes present in the reference archive, one camera-generated
filename, single-colour-fill tiles, uncompressed tiles, and the
scanner/film/pedigree property family. Several of those rest on **one or two
files**, which nothing in the filenames hints at — the fixtures README maps
which branch depends on which file, and it is worth reading before deleting
anything that looks like a duplicate.

Two branches of the decoder have **no committed fixture at all**, and between
them they are where every geometry defect this project has shipped came from.
Tier 3 is the only automated cover either has, and tier 3 never runs in CI — so
a pull request can be entirely green while changing both.

- **Rotation** has never had a fixture and cannot get one: every rotated file in
  the reference archive contains a person. This is the branch that carried the
  defect where rotated files shipped with their crop silently dropped.
- **Crop** had exactly one fixture, and lost it in the 2026-08-27 removal
  described above. Crops are rare in the archive and the person-free candidates
  do not carry one.

**The geometry of both is covered anyway, synthetically.** A `.fpx` keeps its
viewing transform in a `Transform 000001` property set whose orientation matrix
and result aspect are fixed-width float32 fields, and `olefile` will replace a
stream with data of the same size — so `tests/transform_fixture.py` gives a
*copy* of a person-free fixture any transform wanted, and
`tests/test_fixtures_transform.py` runs scan-free decode, crop and write over it.
Rotation, rotation-plus-crop and the axis-aligned crop all have tier-2 cover
again, including the exact 0.4.0 case where a rotation carrying a crop must not
resolve to no crop.

**What that does not buy, and must not be claimed to:** the embedded thumbnail in
those files was written to the framing the file originally had. Against a
transform we invented it witnesses nothing, so every assertion there is
geometric and neither oracle may be pointed at them. Colour and orientation on a
genuinely transformed photograph remain tier-3 and tier-4 work — which is the
same sentence this document opens with, and the reason the eyeball tier exists.

The three tests that ran against the cropped fixture were recorded rather than
deleted: one is inverted and now asserts that no cropped fixture exists, going
red the moment one is committed again, and two are skipped with their bodies
intact. All three share one reason string in `tests/fixture_coverage.py`, so
`pytest -rs` prints the explanation. **If you commit a person-free cropped
fixture, the inverted guard fails on purpose** — that failure is the
instruction to drop the two skips and invert the guard back, not something to
silence.

## Running the tests

```sh
# lint
python -m ruff check .

# tiers 1 and 2
python -m pytest

# tier 3 (needs a real corpus configured; never run in CI)
python scripts/tier3_sample.py

# mutation check (needs the GUI virtualenv; run on a clean tree)
python scripts/mutation_check.py
```

Tier 2 needs **ExifTool** on `PATH`, which is an external program and not a
Python package. A missing ExifTool fails rather than skips: a metadata test
that quietly skips when the metadata writer is absent is a test that cannot
fail.
