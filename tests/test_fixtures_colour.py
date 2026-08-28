"""Tier-2: colour, over the committed fixtures.

Until now this ran only at tier 3, against the personal corpus, which meant
CI had no colour check at all -- and colour is where this project's worst
defect lived. Two PhotoYCC photographs shipped solidly green with 42% of
their pixels clipped to zero, past every automated gate that existed.

Both PhotoYCC files in the archive contain no people, so they are committed
now (`starfish.fpx`, `storm-fence.fpx`) and that path finally has coverage
that runs on every push.

Two kinds of test live here, and the second is the one that matters:

* the fixtures decode to believable colour, and
* the oracle **fails** when the decode is deliberately broken.

The second exists because the first version of this oracle passed everything.
It correlated the R, G and B channels separately, and Pearson correlation is
invariant under any per-channel affine map -- so a wrong gain and a wrong
neutral point scored exactly as well as a correct decode. A colour check that
cannot fail is not a colour check, and the only way to know the difference is
to break the decode on purpose and watch.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fixture_coverage import NO_CROPPED_FIXTURE_REASON
from PIL import Image

from fpx_converter import decoder, oracles, thumbnail

pytestmark = pytest.mark.fixtures

FIXTURES = Path(__file__).parent / "fixtures"

#: The two PhotoYCC files. Everything else in the archive is NIF_RGB.
PHOTOYCC_FIXTURES = ("starfish.fpx", "storm-fence.fpx")


def _fixture_paths() -> list[Path]:
    return sorted(p for p in FIXTURES.iterdir() if p.suffix.lower() == ".fpx")


def _chroma_metrics(path: Path, image: Image.Image | None = None) -> dict[str, float]:
    """Chroma of the decode against the file's own embedded thumbnail.

    `cropped_image()`, not `image`. The embedded DIB is written to the
    *cropped* framing, so comparing it against the full frame lines up two
    different pictures and reads as a colour fault: on the cropped fixture
    this directory used to hold it scored 0.42 and 0.15, well under the 0.5
    gate. Tier 3 made this exact mistake and false-positived on all nine of
    its cropped files. No committed fixture is cropped any more (see
    `NO_CROPPED_FIXTURE_REASON`), so nothing here would catch the mistake
    being made again -- which is a reason to keep the call, not to simplify
    it.
    """
    decoded = decoder.decode_fpx(path).cropped_image() if image is None else image
    return oracles.chroma_agreement(decoded, thumbnail.extract_thumbnail(path))


@pytest.mark.parametrize("path", _fixture_paths(), ids=lambda p: p.name)
def test_every_fixture_decodes_to_believable_colour(path: Path) -> None:
    """Chroma agrees with the embedded DIB, which a different tool wrote."""
    faults = oracles.chroma_faults(_chroma_metrics(path))
    assert not faults, f"{path.name}: {', '.join(faults)}"


@pytest.mark.parametrize("name", PHOTOYCC_FIXTURES)
def test_photoycc_fixtures_really_are_photoycc(name: str) -> None:
    """Guards the coverage itself, not the decode.

    If somebody removes these files or the archive's colour-space detection
    regresses, the PhotoYCC path silently stops being tested and every other
    test here still passes. That is exactly how it went untested before.
    """
    assert decoder.decode_fpx(FIXTURES / name).colour_space == "PhotoYCC"


def test_the_fixture_set_still_covers_what_it_was_chosen_to_cover() -> None:
    """A fixture set can be gutted one deletion at a time without a red test.

    These files were picked out of 687 by eye because they are the only
    person-free ones, and a few of them are the only committed cover for a
    branch. Name what must remain.
    """
    profiles = [decoder.decode_fpx(p) for p in _fixture_paths()]
    colour_spaces = {d.colour_space for d in profiles}
    assert "PhotoYCC" in colour_spaces, "no PhotoYCC fixture: the colour path is untested"
    assert "NIF_RGB" in colour_spaces
    # The crop branch used to be asserted here too. It is not any more, and
    # `test_no_fixture_carries_a_crop_which_is_a_known_regression` below says
    # why -- read that before adding a crop assertion back to this list.
    # Sizes are read per file, never assumed -- so more than one has to exist
    # or nothing would catch a hardcoded 1152x864.
    assert len({(d.declared_width, d.declared_height) for d in profiles}) >= 4


def test_no_fixture_carries_a_crop_which_is_a_known_regression() -> None:
    """The inverted guard, standing where the crop-coverage guard stood.

    This used to read `assert any(d.crop_applied is not None ...)` with the
    message "no cropped fixture: the crop path is untested", and it existed to
    stop that cover being deleted one file at a time. Then the thing it
    guarded against was done deliberately: the only cropped fixture contained
    a person and had to go. See `NO_CROPPED_FIXTURE_REASON`.

    So it is inverted rather than deleted. It records the state the fixture
    set is really in -- which is the state `tests/fixtures/README.md` and the
    two skipped crop tests describe -- and it goes red the moment a cropped
    fixture is committed again, at which point the cover is restored rather
    than this expectation quietly flipped.
    """
    cropped = sorted(p.name for p in _fixture_paths() if decoder.decode_fpx(p).crop_applied)
    assert not cropped, (
        f"a cropped fixture is back ({', '.join(cropped)}). Restore the crop "
        f"coverage instead of only updating this test: drop the skip on "
        f"test_a_cropped_fixture_crops_and_the_crop_is_the_right_box in "
        f"tests/test_fixtures_decoder.py and on "
        f"test_a_full_frame_sharing_output_is_the_declared_size in "
        f"tests/test_cli_convert.py, invert this assertion back, and update "
        f"tests/fixtures/README.md. Context: {NO_CROPPED_FIXTURE_REASON}"
    )


class TestTheOracleCanActuallyFail:
    """Mutation tests. Break the decode; the oracle must notice.

    Every mutation here is one the *previous* per-channel oracle passed.
    """

    @pytest.mark.parametrize("name", PHOTOYCC_FIXTURES)
    def test_the_shipped_photoycc_bug_is_caught(self, name: str, monkeypatch) -> None:
        """The real defect: C1 and C2 have different neutral points.

        C1 is 156 and C2 is 137. Using 156 for both is what shipped, and it
        leaves correlation and scale untouched -- only the offset moves. If
        the offset gate is ever dropped as redundant, this test goes red.
        """
        monkeypatch.setattr(decoder, "PHOTOYCC_C2_NEUTRAL", decoder.PHOTOYCC_C1_NEUTRAL)
        faults = oracles.chroma_faults(_chroma_metrics(FIXTURES / name))
        assert faults, f"{name}: a wrong PhotoYCC neutral produced no fault"

    @pytest.mark.parametrize("name", PHOTOYCC_FIXTURES)
    def test_swapped_red_and_blue_is_caught(self, name: str) -> None:
        path = FIXTURES / name
        r, g, b = decoder.decode_fpx(path).image.split()
        faults = oracles.chroma_faults(_chroma_metrics(path, Image.merge("RGB", (b, g, r))))
        assert faults, f"{name}: an R/B swap produced no fault"

    @pytest.mark.parametrize("name", PHOTOYCC_FIXTURES)
    def test_a_greyscale_decode_is_caught(self, name: str) -> None:
        """The one unambiguous colour fault, which the first oracle scored 1.0.

        A flat chroma channel has no correlation to compute, and returning
        "perfect" for it made the clearest possible failure the one guaranteed
        to pass.
        """
        path = FIXTURES / name
        grey = decoder.decode_fpx(path).image.convert("L").convert("RGB")
        faults = oracles.chroma_faults(_chroma_metrics(path, grey))
        assert faults, f"{name}: a fully desaturated decode produced no fault"

    def test_a_faithful_decode_is_not_flagged(self) -> None:
        """The other half of a mutation test: no false positive on the truth.

        Without this, a gate that flags everything would pass all three tests
        above.
        """
        for name in PHOTOYCC_FIXTURES:
            assert not oracles.chroma_faults(_chroma_metrics(FIXTURES / name))


def test_no_fixture_decodes_flat_or_clipped() -> None:
    """Pixel statistics, the pass that found the double conversion.

    Neither correlation nor size sees a decode that clipped half its pixels
    to zero. This does.
    """
    for path in _fixture_paths():
        arr = np.asarray(decoder.decode_fpx(path).image, dtype=np.uint8)
        clipped = float(np.mean((arr == 0) | (arr == 255)))
        assert float(arr.std()) > 15.0, f"{path.name} decoded flat (std={arr.std():.1f})"
        assert clipped < 0.25, f"{path.name} clipped {clipped:.0%} of its pixels"
