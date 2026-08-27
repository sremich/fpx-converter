"""Tier-1: the validator, across every combination of format and framing.

`validate_outputs` is the only automated proof this project has that a crop
was actually applied. It was rewritten when format and framing became
independent axes, and until now it was exercised only through the default
pair — so `(tiff, cropped)` and `(jpeg, full)` were never checked at all, and
exactly one of forty fixtures carries a crop.

These build the images directly rather than converting a `.fpx`, so every
combination can be tested and every one can be broken on purpose. Tag
validation needs ExifTool and pyexiv2 and belongs at tier 2; what is tested
here is the size and format logic, which is where a silently-unapplied crop
would hide.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from fpx_converter import outputs, validator

DECLARED = (400, 300)
CROP_BOX = (50, 40, 250, 190)  # 200x150
CROP_SIZE = (200, 150)


def _derived(crop: tuple[int, int, int, int] | None = CROP_BOX) -> dict:
    """Metadata as `metadata.py` produces it: the independent expectation."""
    return {
        "image_dimensions": {"declared_width": DECLARED[0], "declared_height": DECLARED[1]},
        "viewing_transform": {
            "tiff_size": list(DECLARED),
            "crop_box": list(crop) if crop else None,
        },
    }


def _write(path: Path, size: tuple[int, int], fmt: str) -> Path:
    image = Image.new("RGB", size, (90, 120, 150))
    if fmt == "tiff":
        image.save(path, format="TIFF", compression="tiff_deflate")
    else:
        image.save(path, format="JPEG", quality=95, subsampling=0)
    return path


def _size_errors(errors: list[str]) -> list[str]:
    """Only the geometry complaints; tag readback is tier 2's business."""
    return [e for e in errors if "expected" in e or "full frame" in e]


class TestEveryCombination:
    """A crop that failed to apply has to fail, whatever the output shape."""

    @pytest.mark.parametrize("fmt", ["tiff", "jpeg"])
    def test_a_correct_cropped_output_passes_the_size_check(
        self, fmt: str, tmp_path: Path
    ) -> None:
        spec = outputs.OutputSpec("sharing", fmt, "cropped")
        path = _write(tmp_path / f"c.{spec.ext}", CROP_SIZE, fmt)
        result = validator.validate_outputs([(path, spec)], _derived())
        assert _size_errors(result.errors) == []

    @pytest.mark.parametrize("fmt", ["tiff", "jpeg"])
    def test_a_correct_full_frame_output_passes(self, fmt: str, tmp_path: Path) -> None:
        """Including where a crop exists -- a full-frame output ignores it.

        This is the combination the rewrite introduced. Before it, a
        full-frame JPEG would have been read as a crop that failed to apply.
        """
        spec = outputs.OutputSpec("sharing", fmt, "full")
        path = _write(tmp_path / f"f.{spec.ext}", DECLARED, fmt)
        result = validator.validate_outputs([(path, spec)], _derived())
        assert _size_errors(result.errors) == []

    @pytest.mark.parametrize("fmt", ["tiff", "jpeg"])
    def test_a_crop_that_failed_to_apply_is_caught(self, fmt: str, tmp_path: Path) -> None:
        """The defect this function exists for.

        Two of this project's shipped bugs were crops that silently did not
        apply: 53 files cropped where 70 should have been, then 14 rotated
        files dropping their crop entirely.
        """
        spec = outputs.OutputSpec("sharing", fmt, "cropped")
        path = _write(tmp_path / f"u.{spec.ext}", DECLARED, fmt)
        result = validator.validate_outputs([(path, spec)], _derived())
        assert not result.ok
        assert any("full frame" in e or "expected" in e for e in result.errors)

    @pytest.mark.parametrize("framing", ["full", "cropped"])
    def test_an_output_of_the_wrong_size_is_caught(
        self, framing: str, tmp_path: Path
    ) -> None:
        spec = outputs.OutputSpec("archive", "tiff", framing)
        path = _write(tmp_path / "w.tif", (123, 45), "tiff")
        result = validator.validate_outputs([(path, spec)], _derived())
        assert not result.ok


class TestFormatChecks:
    def test_an_uncompressed_tiff_is_refused(self, tmp_path: Path) -> None:
        """The archive copy is Deflate. An uncompressed one is not the format
        that was asked for, whatever its pixels."""
        path = tmp_path / "raw.tif"
        Image.new("RGB", DECLARED, (1, 2, 3)).save(path, format="TIFF")
        result = validator.validate_outputs(
            [(path, outputs.OutputSpec("archive", "tiff", "full"))], _derived(None)
        )
        assert any("Deflate" in e for e in result.errors)

    def test_a_subsampled_jpeg_is_refused(self, tmp_path: Path) -> None:
        """4:4:4 is the point: chroma subsampling throws away colour
        resolution, and this is a one-shot conversion of an archive."""
        path = tmp_path / "sub.jpg"
        Image.new("RGB", DECLARED, (1, 2, 3)).save(path, format="JPEG", subsampling=2)
        result = validator.validate_outputs(
            [(path, outputs.OutputSpec("sharing", "jpeg", "full"))], _derived(None)
        )
        assert any("4:4:4" in e for e in result.errors)


class TestMissingInputs:
    def test_a_missing_output_fails_rather_than_passing_vacuously(
        self, tmp_path: Path
    ) -> None:
        spec = outputs.OutputSpec("archive", "tiff", "full")
        result = validator.validate_outputs([(tmp_path / "nope.tif", spec)], _derived())
        assert not result.ok
        assert any("missing" in e for e in result.errors)

    def test_an_unknown_declared_size_reports_that_it_checked_nothing(
        self, tmp_path: Path
    ) -> None:
        """A check that silently does not run is worse than no check.

        With no declared size there is nothing to compare against -- but
        passing in silence makes an unverified file indistinguishable from a
        verified one.
        """
        spec = outputs.OutputSpec("archive", "tiff", "full")
        path = _write(tmp_path / "x.tif", DECLARED, "tiff")
        result = validator.validate_outputs([(path, spec)], {})
        assert any("no declared size" in e.lower() for e in result.errors), (
            "a skipped size check was not reported"
        )
