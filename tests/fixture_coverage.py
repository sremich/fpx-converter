"""What the committed fixture set deliberately does *not* cover, and why.

A fixture set can be gutted one deletion at a time without a red test, so this
project guards its coverage with tests that assert the cover still exists.
When one of those guards has to be stood down, the guard is **not** deleted:
it is inverted or skipped, and it points here.

One entry so far.

`tests/test_fixtures_colour.py` used to assert `any(d.crop_applied is not
None ...)` with the message "no cropped fixture: the crop path is untested".
That assertion was written precisely to stop the crop coverage disappearing
quietly, and then on 2026-08-27 it was made to disappear on purpose: a
full-resolution review of all 40 committed fixtures ahead of the repository
going public found a person -- a figure standing behind the shrubs in the
upper-right background -- in `feeder01.fpx`, `feeder02.fpx` and
`feeder-crop.fpx`. The no-people rule -- stated exactly in
`tests/fixtures/LICENSE.md` -- outranks any coverage, so all three were
removed and the loss was accepted knowingly.

`feeder-crop.fpx` was the only fixture in the repository carrying a
viewing-transform crop.

**Partly restored, 2026-08-28, without committing a photograph.** Every fixture
already carries a `Transform` stream whose matrix and aspect are fixed-width
float32 fields, so `tests/transform_fixture.py` can hand a *copy* of a
person-free fixture any transform wanted and `tests/test_fixtures_transform.py`
runs the real path over it. That covers the geometry, which is where both crop
defects lived. It does not cover what the deleted fixture also gave for free --
a crop the file's own embedded thumbnail agrees with -- because a thumbnail
written to the original framing says nothing about a crop we invented. So the
guard and the two skips below stay exactly as they are.
"""

from __future__ import annotations

#: Why no committed fixture exercises the crop branch. Quoted in the skip
#: reason of every test that used to run against `feeder-crop.fpx`, and in the
#: failure message of the inverted guard that watches for a cropped fixture
#: coming back.
NO_CROPPED_FIXTURE_REASON = (
    "No committed fixture carries a viewing-transform crop. The only one that "
    "did, feeder-crop.fpx, was removed on 2026-08-27: a full-resolution review "
    "found a person in its background, and the no-people rule outranks the "
    "coverage. What this test needs is a cropped photograph whose own embedded "
    "thumbnail witnesses the crop, and that is still tier-3-only, against the "
    "real corpus, which never runs in CI. "
    "The crop *geometry* is no longer uncovered: tests/test_fixtures_transform.py "
    "grafts a transform onto a copy of a person-free fixture at test time and "
    "runs the whole path over it -- see tests/transform_fixture.py. That covers "
    "the branch the 0.4.0 defect lived in, and deliberately asserts nothing "
    "about colour, because a thumbnail written to the uncropped framing is no "
    "witness to a crop somebody invented. "
    "If a person-free cropped photograph is ever committed, delete this skip "
    "rather than editing it, and update tests/fixtures/README.md."
)
