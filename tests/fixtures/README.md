# Test fixtures

Real `.fpx` files, committed so tiers 1 and 2 run against the format as it
actually occurs rather than against hand-built bytes alone.

## The rule these obey

`CLAUDE.md`: *the repository is for the software; the photographs are not.*
Every file here contains **no people**. Four are Kodak stock samples that
shipped with Picture Easy; the other thirty-six are archive photographs that
were screened by eye — all 687 distinct files reviewed on contact sheets,
then every candidate re-reviewed at full size — and confirmed person-free.

Two things that pass a quick look and are still disqualifying: a body part at
the frame edge, and text in the picture. A second pass at full resolution
rejected an incubator that turned out to hold a baby, a child in a red coat
far off in a snowy yard, distant figures on a platform, and three frames of
decorated biscuits with children's names iced onto them. A thumbnail screen
alone would have committed all of those.

Filenames are neutral stems on purpose. This project treats a filename
somebody typed as a caption — the only human-authored content the archive
carries — so an adopted fixture is renamed before it is committed.

**Never add a photograph with a person in it, and never keep an original
filename.**

## What is here, and what it covers

| Group | Files | Why it is here |
|---|---|---|
| `clouds01`–`clouds09` | 9 | A time-lapse: consecutive frames of one sky. Nearly identical pixels, distinct hashes — the dedup path's worked example. |
| `conservatory01`–`08`, `feeder01`–`02`, `foliage01`–`04`, `pond-bed01`–`02` | 16 | Butterflies, flowers, planting. Saturated colour over fine detail, which is what the chroma oracle needs. `feeder01`/`02` have a hand at the frame edge. |
| `clay01`–`clay04` | 4 | Modelling clay on a dark table: strong primaries, dim surround. |
| `dragonfly01`–`02` | 2 | High contrast, small subject, deep shadow. |
| `feeder-crop` | 1 | **The only fixture carrying a viewing-transform crop.** |
| `starfish`, `storm-fence` | 2 | **The only two PhotoYCC files in the archive.** Everything else is NIF_RGB. |
| `giraffe`, `mask`, `train-platform`, `harbor`, `squirrel`, `Clouds01`, `P0000016` | 7 | Six of the seven declared sizes between them; `P0000016` is the one camera-named stem. |

Between them: both colour spaces, six of seven declared sizes, one crop, and
one camera-generated filename.

## What they do *not* cover

**Rotation.** Twenty-two files in the archive carry a 90° rotation and
fourteen of those also carry a crop — and every single one of them has a
person in it. That branch cannot be covered by a committed fixture, which
matters, because it is the branch that carried the 0.4.0 defect where
rotated files shipped with their crop silently dropped. Tier 3 against the
real corpus is the only automated cover it has.

## If you change this directory

`tests/test_fixtures_scan.py` pins every file's SHA-256 and byte length. That
table catches a corrupted or replaced fixture *and* a scanner that reads the
wrong bytes. Regenerate it only when adding a fixture deliberately — never to
turn a red test green, which is the one failure it exists to report.

`tests/test_fixtures_colour.py` asserts the set still contains a PhotoYCC
file and a cropped file, so the coverage cannot be deleted one file at a time
without something going red.
