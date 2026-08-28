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
`feeder-crop.fpx`. `CLAUDE.md`'s no-people rule outranks any coverage, so all
three were removed and the loss was accepted knowingly.

`feeder-crop.fpx` was the only fixture in the repository carrying a
viewing-transform crop.
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
    "coverage. The crop branch -- the branch that carried the 0.4.0 defect "
    "where rotated files shipped with their crop silently dropped -- now has "
    "tier-3-only cover, against the real corpus, which never runs in CI. "
    "If a person-free cropped fixture is ever committed, delete this skip "
    "rather than editing it, and update tests/fixtures/README.md."
)
