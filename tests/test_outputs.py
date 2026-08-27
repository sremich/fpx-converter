"""Tier-1: format and framing are independent settings.

They used to be welded to the output tree -- `archive/` meant a full-frame
TIFF and `sharing/` meant a cropped JPEG, with no way to ask for one without
the other. A cropped TIFF and a full-frame JPEG are both reasonable things to
want, so the two axes are now separate.

The defaults are the shipped behaviour and several tests here exist purely to
keep them that way: this refactor could quietly have changed what a bare
`convert` writes over an irreplaceable archive.
"""

from __future__ import annotations

import pytest
from PIL import Image

from fpx_converter import outputs


class TestSpecValidation:
    @pytest.mark.parametrize(
        ("tree", "fmt", "framing"),
        [
            ("archive", "tiff", "full"),
            ("archive", "jpeg", "cropped"),
            ("sharing", "tiff", "full"),
            ("sharing", "jpeg", "cropped"),
        ],
    )
    def test_every_combination_of_the_two_axes_is_allowed(
        self, tree: str, fmt: str, framing: str
    ) -> None:
        """That is the point of separating them."""
        spec = outputs.OutputSpec(tree, fmt, framing)
        assert spec.label == f"{tree}/{fmt}/{framing}"

    @pytest.mark.parametrize(
        ("tree", "fmt", "framing"),
        [
            ("backup", "tiff", "full"),
            ("archive", "png", "full"),
            ("archive", "tiff", "square"),
            ("archive", "TIFF", "full"),
        ],
    )
    def test_a_value_it_cannot_honour_is_refused_at_construction(
        self, tree: str, fmt: str, framing: str
    ) -> None:
        """Loudly, and before any file is written.

        A misspelt format that fell through to a default would write the wrong
        thing over a whole corpus and report success.
        """
        with pytest.raises(outputs.OutputSpecError):
            outputs.OutputSpec(tree, fmt, framing)

    def test_extensions_are_the_ones_the_naming_scheme_expects(self) -> None:
        assert outputs.OutputSpec("archive", "tiff", "full").ext == "tif"
        assert outputs.OutputSpec("sharing", "jpeg", "full").ext == "jpg"


class TestDefaults:
    def test_the_default_pair_is_still_what_shipped(self) -> None:
        """Archive keeps every captured pixel; sharing gets the 2002 framing."""
        assert (
            outputs.OutputSpec("archive", "tiff", "full"),
            outputs.OutputSpec("sharing", "jpeg", "cropped"),
        ) == outputs.DEFAULT_SPECS

    def test_build_specs_with_no_arguments_reproduces_it(self) -> None:
        assert outputs.build_specs() == outputs.DEFAULT_SPECS

    def test_dropping_the_sharing_tree_leaves_the_lossless_full_frame(self) -> None:
        """The owner's ask: the largest, non-cropped image, format immaterial."""
        specs = outputs.build_specs(sharing=False)
        assert len(specs) == 1
        assert specs[0] == outputs.OutputSpec("archive", "tiff", "full")

    def test_a_full_frame_jpeg_is_one_setting(self) -> None:
        specs = outputs.build_specs(sharing_framing="full")
        assert specs[1] == outputs.OutputSpec("sharing", "jpeg", "full")

    def test_a_cropped_tiff_is_one_setting(self) -> None:
        specs = outputs.build_specs(archive_framing="cropped")
        assert specs[0] == outputs.OutputSpec("archive", "tiff", "cropped")

    def test_asking_for_no_output_at_all_is_an_error_not_a_no_op(self) -> None:
        """Writing nothing looks exactly like success, which is the danger."""
        with pytest.raises(outputs.OutputSpecError, match="nothing to write"):
            outputs.build_specs(archive=False, sharing=False)


class _FakeDecoded:
    """Stands in for `decoder.DecodedImage`: a full frame and a crop of it."""

    def __init__(self) -> None:
        self.image = Image.new("RGB", (100, 80), (10, 20, 30))
        self._cropped = Image.new("RGB", (40, 30), (40, 50, 60))

    def cropped_image(self) -> Image.Image:
        return self._cropped


class TestFraming:
    def test_full_takes_the_whole_frame(self) -> None:
        assert outputs.OutputSpec("archive", "tiff", "full").image_from(
            _FakeDecoded()
        ).size == (100, 80)

    def test_cropped_takes_the_crop(self) -> None:
        assert outputs.OutputSpec("sharing", "jpeg", "cropped").image_from(
            _FakeDecoded()
        ).size == (40, 30)


class TestExpectedSize:
    """The size the validator will demand, derived from metadata not pixels."""

    DECLARED = (1152, 864)
    BOX = (100, 50, 700, 500)

    def test_a_full_output_is_the_declared_size_even_where_a_crop_exists(self) -> None:
        spec = outputs.OutputSpec("sharing", "jpeg", "full")
        assert spec.expected_size(self.DECLARED, self.BOX) == self.DECLARED

    def test_a_cropped_output_is_the_box(self) -> None:
        spec = outputs.OutputSpec("sharing", "jpeg", "cropped")
        assert spec.expected_size(self.DECLARED, self.BOX) == (600, 450)

    def test_a_cropped_output_with_no_crop_is_the_declared_size(self) -> None:
        """617 of 687 files carry no crop, so this is the common case."""
        spec = outputs.OutputSpec("sharing", "jpeg", "cropped")
        assert spec.expected_size(self.DECLARED, None) == self.DECLARED

    def test_an_unknown_declared_size_expects_nothing_rather_than_guessing(self) -> None:
        spec = outputs.OutputSpec("archive", "tiff", "full")
        assert spec.expected_size(None, None) is None
