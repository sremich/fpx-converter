# Test fixtures

Real `.fpx` files, committed so tiers 1 and 2 run against the format as it
actually occurs rather than against hand-built bytes alone.

## The rule these obey

The repository is for the software; the photographs are not. **No file here
contains an identifiable person.** The exact standard, and the one fixture
that sits closest to its edge, are set out in [`LICENSE.md`](LICENSE.md).

Thirty-seven files, in two groups:

- **Sixteen of unknown origin** — `Clouds01`, `clouds02`–`clouds09`,
  `harbor`, `mask`, `P0000016`, `squirrel`, `starfish`, `storm-fence`,
  `train-platform`. They were found in the owner's archive in folders named
  `Sample`, `Sample/Burst` and `Sample/TimeLapse`, and were long assumed to
  be Kodak sample imagery bundled with Picture Easy. **That assumption does
  not survive examination and is no longer made** — their dimensions match
  the DC200/DC210 that took Group 2, and nine consecutive frames of one sky
  is a camera transfer rather than a curated sample set. No authorship is
  asserted and no licence is claimed over them. Three carry a 1998
  film-scanner pedigree that is **not** the owner's — he has never had film
  scanned to Photo CD and has never owned a film scanner.
- **Twenty-one are the owner's own archive photographs** — `clay01`–`04`,
  `conservatory01`–`08`, `dragonfly01`–`02`, `foliage01`–`04`, `giraffe`,
  `pond-bed01`–`02`. All 2001–2002, KODAK DC200/DC210, 1152×864, NIF_RGB.
  These were screened by eye — all 687 distinct files reviewed on contact
  sheets, then every candidate re-reviewed at full size — and confirmed
  person-free.

Neither group is covered by the repository's Apache-2.0 licence, and the two
groups do not carry the same terms. See [`LICENSE.md`](LICENSE.md) in this
directory for both, with the full file lists.

Two things that pass a quick look and are still disqualifying: a recognisable
person anywhere in the frame, however small, and text in the picture. A
second pass at full resolution rejected an incubator that turned out to hold
a baby, a child in a red coat far off in a snowy yard, and three frames of
decorated biscuits with children's names iced onto them. A thumbnail screen
alone would have committed all of those.

**And that screening still missed three.** On 2026-08-27, reviewing every
committed fixture at full resolution before this repository went public, a
figure turned up standing behind the shrubs in the upper-right background of
`feeder01`, `feeder02` and `feeder-crop` — head, face, light top, blue jeans,
dark shoes. It is small, it is behind foliage, and the subject of all three
frames is a bird feeder in the foreground, so nothing about the pictures drew
the eye to it. All three were deleted, at real cost: `feeder-crop` was the
only fixture in the repository carrying a viewing-transform crop, and that
branch now has no CI cover at all. **The rule outranks the coverage**, which
is what "never add a photograph with a person in it" has to mean when
obeying it is expensive.

There is a second lesson in it. The earlier note in this file said `feeder01`
and `feeder02` "have a hand at the frame edge" — a detail somebody recorded,
reasoned about, and decided was acceptable. It was also wrong: the thing at
the dish edge is the terracotta rim, and there is no hand. A written
observation about a photograph is not the photograph. Re-look; do not
re-read.

Filenames are neutral stems on purpose. This project treats a filename
somebody typed as a caption — the only human-authored content the archive
carries — so an adopted fixture is renamed before it is committed.

**Never add a photograph with a person in it, and never keep an original
filename.**

## Transforms are grafted on, not photographed

Every file here has an identity viewing transform, and none of them can be
replaced by one that does not: rotated and cropped files in the archive contain
people without exception. So the transform cover is built rather than adopted.

`../transform_fixture.py` copies one of these files and rewrites the
`SpatialOrientationMatrix` and `ResultAspectRatio` in the copy's `Transform`
stream. Both are fixed-width float32 fields, so the stream length never changes,
which is the one thing `olefile` requires to write it back. The originals here
are never touched — they are the only irreplaceable thing in this repository,
and the set only ever shrinks.

That covers the geometry. It cannot cover colour or framing *judged against the
file's own thumbnail*, because the thumbnail was written to the framing the file
really has. Do not point either oracle at a grafted fixture.

## What is here, and what it covers

| Group | Files | Why it is here |
|---|---|---|
| `clouds02`–`clouds09` | 8 | A time-lapse: consecutive frames of one sky. Nearly identical pixels, distinct hashes — the dedup path's worked example. (`Clouds01` is counted in the last row.) |
| `conservatory01`–`08`, `foliage01`–`04`, `pond-bed01`–`02` | 14 | Butterflies, flowers, planting. Saturated colour over fine detail, which is what the chroma oracle needs. |
| `clay01`–`clay04` | 4 | Modelling clay on a dark table: strong primaries, dim surround. |
| `dragonfly01`–`02` | 2 | High contrast, small subject, deep shadow. |
| `starfish`, `storm-fence` | 2 | **The only two PhotoYCC files in the archive.** Everything else is NIF_RGB. |
| `giraffe`, `mask`, `train-platform`, `harbor`, `squirrel`, `Clouds01`, `P0000016` | 7 | Six of the seven declared sizes between them; `P0000016` is the one camera-named stem. |

Between them: both colour spaces, six of seven declared sizes, and one
camera-generated filename. **No crop** — see "What they do *not* cover".

### Coverage that rests on a single file, or a handful

The table above groups fixtures by what they look like. Three branches of the
decoder are covered by a much smaller set than that grouping suggests, and
nothing in the group names hints at it — which is exactly how such a file
gets deleted as a duplicate. Measured across all 37 fixtures:

| Branch | Covered by | Everything else |
|---|---|---|
| **Single-colour-fill tiles** (`compression_type == 1`) | `clouds02`–`clouds06`, `clouds08`, `clouds09` — seven files. **`clouds07` has none**, despite sitting in the middle of the run | No other fixture contains one |
| **Uncompressed tiles** (`compression_type == 0`) | `harbor` — **one file** | Every other fixture is JPEG tiles throughout |
| **Scanner / Film / Kodak_Pedigree property family** | `starfish` and `storm-fence` carry the full family (`0x27*`, `0x28*`, `0x29*`) *and* the `Kodak_Pedigree Image Info` extension storage. `harbor` carries a partial one: `ScannerManufacturer` and `ScannerModel` only, no pedigree storage | No other fixture has any of it |

So the time-lapse run is not nine interchangeable pictures of a sky: seven of
them are the only cover the single-colour-fill path has. Thinning it "because
they are all the same" would delete a decoder branch's only test while every
test still passed.

### Removing the Kodak files would gut the coverage

The sixteen Kodak samples are the varied half of this directory. The owner's
twenty-one are all 1152×864 and all NIF_RGB, so dropping the Kodak files as
"not ours" would cost, in one move:

- **Both PhotoYCC files** (`starfish`, `storm-fence`) — the whole colour-space
  branch, and the one the 1.0.0-era green-image defect lived in.
- **Five of the six declared sizes present.** 640×480 (`P0000016`,
  `train-platform`), 768×512 (`harbor`), 982×1448 (`mask`), 996×1536
  (`squirrel`) and 1536×1024 (`starfish`, `storm-fence`) all go; only
  1152×864 would remain. "Never hardcode 1152×864" would then be a rule with
  no test behind it.
- The only uncompressed-tile file, all the single-colour-fill tiles, the
  entire Scanner/Film/Pedigree property family, and the one
  camera-generated filename.

They stay. See [`LICENSE.md`](LICENSE.md) for the terms they stay under.

## What they do *not* cover

Two branches of the decoder have **no committed fixture at all**. Both are
parts of the viewing-transform code, and between them they are where every
geometry defect this project has shipped came from. Tier 3, run locally
against the real corpus, is the only automated cover either of them has — and
tier 3 never runs in CI, so a pull request can be entirely green while
changing both.

**Rotation.** Twenty-two files in the archive carry a 90° rotation and
fourteen of those also carry a crop — and every single one of them has a
person in it. That branch cannot be covered by a committed fixture, which
matters, because it is the branch that carried the 0.4.0 defect where
rotated files shipped with their crop silently dropped.

**Crop.** This one *was* covered until 2026-08-27, and the cover was given up
knowingly. `feeder-crop.fpx` was the only file here carrying a
viewing-transform crop; the full-resolution review described above found a
person in its background, and it was deleted along with `feeder01` and
`feeder02`. Nothing replaces it: crops are rare in this archive and the
person-free candidates do not carry one. So the crop path — 70 files in the
real corpus, 56 axis-aligned and 14 riding along with a rotation, and the
path where a matrix's shape does *not* tell you whether it crops — is
untested on every push.

The three tests that ran against it were **not deleted**. They are recorded
rather than lost:

| Test | What it does now |
|---|---|
| `test_fixtures_colour.py::test_no_fixture_carries_a_crop_which_is_a_known_regression` | Inverted. It used to assert a cropped fixture exists; it now asserts none does, and goes red the moment one is committed again |
| `test_fixtures_decoder.py::test_a_cropped_fixture_crops_and_the_crop_is_the_right_box` | Skipped, body intact and no longer naming a fixture — restoring it is deleting one decorator |
| `test_cli_convert.py::test_a_full_frame_sharing_output_is_the_declared_size` | Skipped for the same reason: `--sharing-framing full` cannot be observed without a file that carries a crop |

All three share one reason string, `NO_CROPPED_FIXTURE_REASON` in
`tests/fixture_coverage.py`, so the explanation has one home and `pytest -rs`
prints it.

**If you commit a person-free cropped fixture, the inverted guard fails on
purpose.** That failure is the instruction: drop the two skips, invert the
guard back, and correct this section. Do not simply flip the expectation.

## If you change this directory

`tests/test_fixtures_scan.py` pins every file's SHA-256 and byte length. That
table catches a corrupted or replaced fixture *and* a scanner that reads the
wrong bytes. Regenerate it only when a fixture is added or removed
deliberately — never to turn a red test green, which is the one failure it
exists to report. Regenerate it by re-reading the files, not by editing the
rows that are in the way: the 2026-08-27 removal re-read all 37 remaining
files and confirmed every other row unchanged.

`tests/test_fixtures_colour.py` asserts the set still contains a PhotoYCC
file, so that coverage cannot be deleted one file at a time without something
going red. It used to assert the same about a cropped file — see above for
what happened to that.
