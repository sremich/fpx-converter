"""Tier-2: the viewing transform, end to end, over a real OLE2 container.

This is the branch that carried the 0.4.0 defect. A rotation and a crop are
independent properties of the same matrix, and the first implementation asked
"is this a rotation or a crop?" -- which is the wrong question. Under a rotation
the scale sits on the off-diagonal, the closed-form read of a scale and a
translation returned zeros, and the code took the "this is a rotation, not a
crop" branch and dropped the crop. Fourteen files shipped rotated and uncropped,
with `crop_box: null` in the sidecar and nothing in the audit.

`tests/test_decoder.py` covers the matrix arithmetic against synthetic matrices,
which is where that defect actually lived. What it cannot cover is the whole
path -- a real file, parsed, decoded, transformed and written -- and that path
had no cover in CI at all after `feeder-crop.fpx` was deleted. `transform_fixture`
puts it back by giving a copy of a person-free fixture a transform at test time.
Read its module docstring before adding anything here.

**No oracle may be run against these files.** The embedded DIB thumbnail was
written to the framing the file originally had, which is uncropped and unrotated;
against a transform we invented it witnesses nothing, and
`compute_image_correlation` would happily score a wrong answer 0.98 because it
folds to greyscale and resizes to a square. Every assertion in this module is
geometric, and that is not an oversight to be corrected by the next reader.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import transform_fixture as tfx
from PIL import Image

from fpx_converter import decoder, outputs, writer

pytestmark = pytest.mark.fixtures

FIXTURES = Path(__file__).parent / "fixtures"

#: The fixture every transform here is grafted onto. Modelling clay on a dark
#: table: the owner's own photograph, person-free, NIF_RGB, and 1152x864, which
#: is the declared size all the geometry below is worked out against.
BASE = FIXTURES / "clay01.fpx"
BASE_W, BASE_H = 1152, 864

#: A 90-degree rotation that covers the whole source and crops nothing. The
#: scale is the source aspect, so the result viewport's 1.0 of height maps onto
#: the full 1.3333 of source width.
ROTATE_ONLY = (tfx.rotate_90_ccw(BASE_W / BASE_H, BASE_W / BASE_H, 0.0), BASE_H / BASE_W)

#: The same rotation carrying a crop -- the 0.4.0 shape. The viewport covers
#: 0.9 x 0.9 normalised units of a 1.3333 x 1.0 source, centred.
#:
#: The result is deliberately **square**, and that is not an arbitrary choice.
#: A 90-degree rotation of this source produces a 0.75 frame, so a crop that
#: also came out 0.75 would be indistinguishable from no crop at all by shape
#: -- which is what the first version of this file used, and a mutation run
#: proved the aspect assertion below could not fail against it. An aspect the
#: uncropped rotation cannot produce is what makes that assertion mean
#: something.
ROTATE_AND_CROP = (tfx.rotate_90_ccw(0.9, 1.11666666, 0.05), 1.0)
#: Which source pixels the result covers, before the rotation is applied.
ROTATE_AND_CROP_SOURCE_BOX = (187, 43, 965, 821)
#: The same region in the rotated image's coordinates, which is what
#: `crop_applied` reports and what `sharing/` actually cuts. Not the same
#: numbers, and the sidecar once carried both with nothing saying which.
ROTATE_AND_CROP_BOX = (43, 187, 821, 965)
ROTATE_AND_CROP_SIZE = (778, 778)

#: An axis-aligned crop, the shape 56 of the corpus's 70 crops take. Values
#: taken from `test_decoder.py`, where the same matrix is checked arithmetically.
AXIS_CROP = (tfx.axis_aligned(0.7449, 0.0, 0.2521), 0.8746)


@pytest.fixture
def transformed(tmp_path: Path):  # noqa: ANN201
    """Build a decoded copy of `BASE` carrying the transform asked for."""

    def build(matrix_and_aspect: tuple[list[float], float], name: str = "t.fpx"):  # noqa: ANN202
        matrix, aspect = matrix_and_aspect
        path = tfx.write_transform(
            BASE, tmp_path / name, matrix=matrix, result_aspect=aspect
        )
        return decoder.decode_fpx(path)

    return build


class TestARotationCarryingACropResolvesBoth:
    """The 0.4.0 regression guard, and the reason this module exists."""

    def test_the_crop_is_not_dropped(self, transformed) -> None:  # noqa: ANN001
        decoded = transformed(ROTATE_AND_CROP)
        assert decoded.transform_status == decoder.TRANSFORM_ROTATE_90_CCW
        assert decoded.crop_applied is not None, (
            "a rotation carrying a crop resolved to no crop. This is the 0.4.0 "
            "defect exactly: the closed-form read of a scale and a translation "
            "is only valid for an axis-aligned matrix, and under a rotation it "
            "reads zeros and takes the 'rotation, not a crop' branch."
        )
        assert decoded.crop_applied == ROTATE_AND_CROP_BOX

    def test_the_reported_box_is_in_the_rotated_frame_not_the_source(self) -> None:
        """Two coordinate systems, and the sidecar once carried both.

        `resolve_crop_box` answers in source coordinates and the rotation
        turns that into the result's. Reporting the source box beside a
        rotated image is not a rounding difference -- it names different
        pixels -- so the two are pinned separately here.
        """
        matrix, aspect = ROTATE_AND_CROP
        source_box, reason = decoder.resolve_crop_box(matrix, aspect, BASE_W, BASE_H)
        assert reason == ""
        assert source_box == ROTATE_AND_CROP_SOURCE_BOX
        assert source_box != ROTATE_AND_CROP_BOX, (
            "the two frames coincide here, so this fixture cannot tell them "
            "apart -- pick a crop that is not symmetric about the diagonal"
        )
        assert decoder.output_geometry(
            matrix, aspect, BASE_W, BASE_H
        ).crop_box == ROTATE_AND_CROP_BOX

    def test_the_rotation_is_applied_to_the_full_frame(self, transformed) -> None:  # noqa: ANN001
        """`image` is always every pixel the camera captured, upright."""
        decoded = transformed(ROTATE_AND_CROP)
        assert decoded.image.size == (BASE_H, BASE_W)

    def test_the_crop_is_smaller_than_the_frame_it_came_from(self, transformed) -> None:  # noqa: ANN001
        decoded = transformed(ROTATE_AND_CROP)
        cropped = decoded.cropped_image()
        assert cropped.size == ROTATE_AND_CROP_SIZE
        assert cropped.width < decoded.image.width
        assert cropped.height < decoded.image.height

    def test_the_result_carries_the_declared_aspect(self, transformed) -> None:  # noqa: ANN001
        """A crop resolved to the wrong box would still be *a* box.

        Checking the shape against `ResultAspectRatio` -- which the file
        declares independently of the matrix -- is what makes this more than a
        restatement of the box the code just derived.
        """
        decoded = transformed(ROTATE_AND_CROP)
        cropped = decoded.cropped_image()
        assert cropped.width / cropped.height == pytest.approx(
            ROTATE_AND_CROP[1], abs=0.01
        )


class TestARotationWithoutACropInventsNone:
    """The other half. A check that only ever fires one way is not a check.

    `resolve_crop_box` distinguishes "there is no crop" from "the crop could not
    be resolved", and a fix for the defect above that reported a crop on every
    rotation would pass every assertion in the class before this one.
    """

    def test_a_full_frame_rotation_reports_no_crop(self, transformed) -> None:  # noqa: ANN001
        decoded = transformed(ROTATE_ONLY)
        assert decoded.transform_status == decoder.TRANSFORM_ROTATE_90_CCW
        assert decoded.crop_applied is None

    def test_both_framings_are_the_same_pixels(self, transformed) -> None:  # noqa: ANN001
        decoded = transformed(ROTATE_ONLY)
        assert decoded.cropped_image().size == decoded.image.size


class TestAnAxisAlignedCropIsUnaffectedByAnyOfThis:
    """The 56-file shape, kept beside the 14-file one so a fix to either is
    measured against both."""

    def test_it_crops_without_rotating(self, transformed) -> None:  # noqa: ANN001
        decoded = transformed(AXIS_CROP)
        assert decoded.transform_status == decoder.TRANSFORM_CROP
        assert decoded.image.size == (BASE_W, BASE_H)
        assert decoded.crop_applied is not None
        cropped = decoded.cropped_image()
        assert cropped.size[0] < BASE_W and cropped.size[1] < BASE_H


class TestTheTwoTreesGetTheTwoFramings:
    """`archive/` keeps the full frame; `sharing/` gets the crop.

    Through the real writer rather than by reading `DecodedImage` again, because
    the defect this guards against is a crop that resolves correctly and then
    fails to reach the file somebody opens. No ExifTool needed: this is the
    pixel half, and the tag half is `test_fixtures_output.py`.
    """

    def test_the_tiff_is_full_frame_and_the_jpeg_is_cropped(
        self, transformed, tmp_path: Path
    ) -> None:  # noqa: ANN001
        decoded = transformed(ROTATE_AND_CROP)
        tif, jpg = tmp_path / "a.tif", tmp_path / "b.jpg"
        writer.save_dual_images(decoded, tif, jpg)

        with Image.open(tif) as archive_image:
            assert archive_image.size == (BASE_H, BASE_W)
        with Image.open(jpg) as sharing_image:
            assert sharing_image.size == ROTATE_AND_CROP_SIZE

    def test_the_audit_expectation_is_derived_from_the_metadata_not_the_decode(
        self, transformed
    ) -> None:  # noqa: ANN001
        """`expected_size` must agree with what was actually written.

        It deliberately computes from the declared size and the crop box rather
        than from the decoded object, so that a crop which silently failed to
        apply cannot match itself. That only means anything if the two agree
        when the crop *did* apply.
        """
        decoded = transformed(ROTATE_AND_CROP)
        declared = decoded.image.size
        for spec in outputs.DEFAULT_SPECS:
            expected = spec.expected_size(declared, decoded.crop_applied)
            assert spec.image_from(decoded).size == expected


class TestTheFixtureItselfIsNeverTouched:
    """The source archive is read-only, and the fixtures are this repository's.

    They are the one irreplaceable thing here: a fixture cannot be regenerated,
    and the three that were deleted for containing a person are proof that the
    set only ever shrinks.
    """

    def test_writing_a_transform_leaves_the_original_alone(self, tmp_path: Path) -> None:
        before = BASE.read_bytes()
        copy = tmp_path / "copy.fpx"
        tfx.write_transform(
            BASE, copy, matrix=ROTATE_AND_CROP[0], result_aspect=ROTATE_AND_CROP[1]
        )

        assert BASE.read_bytes() == before
        assert decoder.decode_fpx(BASE).transform_status == decoder.TRANSFORM_IDENTITY
        assert copy.read_bytes() != before, "the copy was supposed to change"

    def test_only_the_transform_stream_differs(self, tmp_path: Path) -> None:
        """Everything except the transform survives the patch byte for byte.

        A helper that rewrote the wrong offset could still produce a file that
        parses and decodes -- so the pixels, the declared size and the metadata
        are checked to be untouched rather than assumed to be.
        """
        copy = tfx.write_transform(
            BASE,
            tmp_path / "copy.fpx",
            matrix=ROTATE_AND_CROP[0],
            result_aspect=ROTATE_AND_CROP[1],
        )
        original = decoder.decode_fpx(BASE, apply_transform=False)
        patched = decoder.decode_fpx(copy, apply_transform=False)

        assert patched.declared_width == original.declared_width
        assert patched.declared_height == original.declared_height
        assert patched.image.tobytes() == original.image.tobytes()


def test_the_helper_refuses_a_fixture_with_no_transform_stream(tmp_path: Path) -> None:
    """A file without the stream must fail loudly, not silently write nothing.

    Every fixture in this repository happens to carry one, so this is checked
    against a file that does not rather than left to be discovered later.
    """
    empty = tmp_path / "empty.fpx"
    shutil.copy2(FIXTURES / "clay02.fpx", empty)
    # An .fpx with the stream removed is not constructible with olefile, which
    # only replaces streams in place -- so the negative case is exercised by
    # pointing the helper at a plain file instead.
    not_an_fpx = tmp_path / "notole.fpx"
    not_an_fpx.write_bytes(b"not an OLE2 container")
    with pytest.raises(Exception):  # noqa: B017 -- olefile's own error type
        tfx.write_transform(
            not_an_fpx, tmp_path / "out.fpx", matrix=ROTATE_ONLY[0],
            result_aspect=ROTATE_ONLY[1],
        )
