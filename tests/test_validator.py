"""Tier-1: the validator, across every combination of format and framing.

`validate_outputs` is the only automated proof this project has that a crop
was actually applied. It was rewritten when format and framing became
independent axes, and until now it was exercised only through the default
pair — so `(tiff, cropped)` and `(jpeg, full)` were never checked at all, and
exactly one of forty fixtures carries a crop.

These build the images directly rather than converting a `.fpx`, so every
combination can be tested and every one can be broken on purpose.

The tag half of the file is new. The validator reads tags back with Pillow
now rather than `pyexiv2`, so the read-back path needs its own coverage in
both directions: the ten tags must be *found* on both containers, and every
one of them must be able to *fail*. A tag whose check cannot fail is the
defect this project has shipped twice, and swapping the reader is exactly
when a check quietly stops running — Pillow finding no XMP at all would have
made three of the ten pass in silence.

Those tests need ExifTool, because ExifTool is the writer half of the "a
different tool than the one that wrote" rule and there is no honest way to
test the round trip without it. They skip when it is absent and fail when
`FPX_REQUIRE_EXIFTOOL` is set, exactly as the tier-2 fixtures do.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from fpx_converter import outputs, validator, writer

REPO_ROOT = Path(__file__).resolve().parents[1]

DECLARED = (400, 300)
CROP_BOX = (50, 40, 250, 190)  # 200x150
CROP_SIZE = (200, 150)

HAVE_EXIFTOOL = writer.resolve_exiftool_path() is not None
REQUIRE_EXIFTOOL = os.environ.get("FPX_REQUIRE_EXIFTOOL", "").strip() not in ("", "0")
needs_exiftool = pytest.mark.skipif(
    not HAVE_EXIFTOOL and not REQUIRE_EXIFTOOL,
    reason="ExifTool not installed or not found on PATH",
)


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
    """Only the geometry complaints; tag readback is checked separately."""
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


# --------------------------------------------------------------------------
# The GPL boundary.
#
# `pyexiv2` is GPL-3.0 and carries a GPL-2.0-or-later `exiv2.dll`. The
# packaged .exe bundles whatever `fpx_converter` imports, so one import here
# relicenses an Apache-2.0 project. `pyexiv2` is still a dev dependency and
# the tier-2 and tier-3 tests still use it as a third opinion; what must not
# happen is the package importing it.
# --------------------------------------------------------------------------


class TestNoGplAtRuntime:
    def test_pyexiv2_is_available_so_these_tests_are_not_vacuous(self) -> None:
        """Guard the guards.

        Both tests below would pass in an environment with no `pyexiv2` at
        all, for entirely the wrong reason. `requirements-dev.txt` pins it,
        so its absence means the environment is wrong, not that the rule
        holds.
        """
        assert importlib.util.find_spec("pyexiv2") is not None, (
            "pyexiv2 is not installed, so the no-GPL-at-runtime tests below "
            "would pass without proving anything. Install requirements-dev.txt."
        )

    def test_importing_the_package_does_not_load_pyexiv2(self) -> None:
        """The claim the licence rests on, measured rather than asserted."""
        code = (
            "import sys, importlib;"
            "importlib.import_module('fpx_converter.validator');"
            "importlib.import_module('fpx_converter.writer');"
            "print('pyexiv2' in sys.modules)"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        assert proc.stdout.strip() == "False", (
            "importing fpx_converter pulled in pyexiv2, which would bundle "
            f"GPL code into the published .exe. stdout={proc.stdout!r}"
        )

    def test_no_module_in_the_package_names_pyexiv2_as_an_import(self) -> None:
        """A lazy import inside a function would not show up above.

        `import pyexiv2` buried in a rarely-taken branch still ships the DLL
        and still relicenses the executable, and it would not be loaded by
        the import test.
        """
        offenders = []
        for path in sorted((REPO_ROOT / "fpx_converter").rglob("*.py")):
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if stripped.startswith(("import pyexiv2", "from pyexiv2")):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}")
        assert not offenders, f"pyexiv2 is imported by the shipped package: {offenders}"

    def test_requirements_keeps_pyexiv2_out_of_the_runtime_set(self) -> None:
        runtime = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
        dev = (REPO_ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
        pins = [
            line.split("==")[0].strip()
            for line in runtime.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        assert "pyexiv2" not in pins, "pyexiv2 is pinned as a runtime dependency again"
        assert "defusedxml" in pins, (
            "defusedxml is not pinned at runtime -- Pillow returns an empty XMP "
            "dict without it and every XMP check would pass without checking"
        )
        assert "pyexiv2==" in dev, "pyexiv2 must stay pinned for the tests that use it"


# --------------------------------------------------------------------------
# Tag read-back. ExifTool writes; the validator reads with Pillow.
# --------------------------------------------------------------------------

#: Invented, person-free values. Nothing here comes from the archive.
CAMERA = {
    "make": "KODAK",
    "model": "DC210 Zoom Camera",
    "software": "Picture Easy Software 3",
}
KEYWORDS = ["Sample Images", "Second Album"]
CAPTION = "A Caption Somebody Typed"
DIGITIZED = "1998:02:28 11:34:38"
ORIGINAL = "2001:12:25 00:00:00"


def _tagged_derived(*, dated: bool = True) -> dict:
    derived = _derived(None)
    derived["camera"] = dict(CAMERA)
    derived["timestamps"] = {
        "datetime_digitized_exif": DIGITIZED,
        "offset_time_digitized": "-06:00",
        "datetime_original_exif": ORIGINAL if dated else None,
        "offset_time_original": "-06:00" if dated else None,
    }
    derived["iptc_keywords"] = list(KEYWORDS)
    derived["caption_title"] = CAPTION
    return derived


def _tagged_file(tmp_path: Path, fmt: str, derived: dict, stem: str = "t") -> Path:
    """One output written by Pillow and tagged by ExifTool, as a run would."""
    spec = outputs.OutputSpec("archive" if fmt == "tiff" else "sharing", fmt, "full")
    path = _write(tmp_path / f"{stem}.{spec.ext}", DECLARED, fmt)
    tool = writer.resolve_exiftool_path()
    assert tool, "ExifTool is required for the read-back tests"
    proc = subprocess.run(
        [tool, *writer.build_exiftool_args(derived, [path])],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"ExifTool failed: {proc.stderr}"
    return path


@needs_exiftool
class TestTagReadBack:
    """Every tag must be found on both containers, and each must be able to fail.

    The first direction alone is not a test. A reader that finds nothing
    passes any file whose expectations are empty, and the checks here are
    driven entirely by what `expected_derived` asks for.
    """

    @pytest.mark.parametrize("fmt", ["tiff", "jpeg"])
    def test_all_ten_tags_survive_the_round_trip(self, fmt: str, tmp_path: Path) -> None:
        derived = _tagged_derived()
        path = _tagged_file(tmp_path, fmt, derived)
        spec = outputs.OutputSpec("archive" if fmt == "tiff" else "sharing", fmt, "full")
        result = validator.validate_outputs([(path, spec)], derived)
        assert result.ok, result.errors

    @pytest.mark.parametrize("fmt", ["tiff", "jpeg"])
    def test_the_reader_actually_finds_each_store(self, fmt: str, tmp_path: Path) -> None:
        """Named tags, not just "no errors".

        `validate_outputs` reports absence and mismatch identically, so this
        asserts on the dicts themselves: EXIF, XMP and IPTC each have to come
        back populated on each container. An empty XMP dict is the specific
        way this swap could have gone wrong and stayed green.
        """
        derived = _tagged_derived()
        path = _tagged_file(tmp_path, fmt, derived)
        exif, xmp, iptc = validator._read_tags(path)

        assert exif["Exif.Image.Make"] == CAMERA["make"]
        assert exif["Exif.Image.Model"] == CAMERA["model"]
        assert exif["Exif.Image.Software"] == CAMERA["software"]
        assert exif["Exif.Photo.DateTimeDigitized"] == DIGITIZED
        assert exif["Exif.Photo.DateTimeOriginal"] == ORIGINAL
        assert exif["Exif.Photo.OffsetTimeDigitized"] == "-06:00"
        assert exif["Exif.Photo.OffsetTimeOriginal"] == "-06:00"
        assert xmp["Xmp.dc.subject"] == KEYWORDS
        assert xmp["Xmp.dc.title"] == {'lang="x-default"': CAPTION}
        assert iptc["Iptc.Application2.Keywords"] == KEYWORDS

    @pytest.mark.parametrize("fmt", ["tiff", "jpeg"])
    def test_a_single_keyword_is_not_mistaken_for_a_missing_one(
        self, fmt: str, tmp_path: Path
    ) -> None:
        """Pillow collapses a one-item Bag to a bare string, and a one-item
        IPTC dataset to bare bytes. Most photos in this archive sit in one
        album, so the collapsed shape is the common case, not the edge."""
        derived = _tagged_derived()
        derived["iptc_keywords"] = ["Solo Album"]
        path = _tagged_file(tmp_path, fmt, derived)
        _exif, xmp, iptc = validator._read_tags(path)
        assert xmp["Xmp.dc.subject"] == ["Solo Album"]
        assert iptc["Iptc.Application2.Keywords"] == ["Solo Album"]

    @pytest.mark.parametrize("fmt", ["tiff", "jpeg"])
    @pytest.mark.parametrize(
        ("mutate", "expect_in_error"),
        [
            (lambda d: d["camera"].update(make="NOT KODAK"), "EXIF Make mismatch"),
            (lambda d: d["camera"].update(model="Other Model"), "EXIF Model mismatch"),
            (lambda d: d["camera"].update(software="Other Software"), "EXIF Software mismatch"),
            (
                lambda d: d["timestamps"].update(datetime_digitized_exif="2020:01:01 00:00:00"),
                "EXIF DateTimeDigitized mismatch",
            ),
            (
                lambda d: d["timestamps"].update(datetime_original_exif="2020:01:01 00:00:00"),
                "EXIF DateTimeOriginal mismatch",
            ),
            (
                lambda d: d["timestamps"].update(offset_time_digitized="+09:00"),
                "EXIF OffsetTimeDigitized mismatch",
            ),
            (
                lambda d: d["timestamps"].update(offset_time_original="+09:00"),
                "EXIF OffsetTimeOriginal mismatch",
            ),
            (lambda d: d.update(caption_title="A Different Caption"), "XMP Title mismatch"),
            (lambda d: d.update(iptc_keywords=["Absent Album"]), "XMP Subject missing keyword"),
            (lambda d: d.update(iptc_keywords=["Absent Album"]), "IPTC Keywords missing"),
        ],
    )
    def test_every_tag_check_can_fail(
        self, fmt: str, mutate, expect_in_error: str, tmp_path: Path
    ) -> None:
        """The direction that matters.

        A per-tag mutation of the expectation, checked against a correctly
        written file: each of the ten must produce its own complaint. Without
        this, a reader that returned `{}` for everything would pass every
        test above that only asserts `result.ok` on a correct file.
        """
        written = _tagged_derived()
        path = _tagged_file(tmp_path, fmt, written)
        expected = _tagged_derived()
        mutate(expected)
        spec = outputs.OutputSpec("archive" if fmt == "tiff" else "sharing", fmt, "full")
        result = validator.validate_outputs([(path, spec)], expected)
        assert not result.ok
        assert any(expect_in_error in e for e in result.errors), result.errors

    @pytest.mark.parametrize("fmt", ["tiff", "jpeg"])
    def test_an_undated_photo_round_trips_without_a_capture_date(
        self, fmt: str, tmp_path: Path
    ) -> None:
        derived = _tagged_derived(dated=False)
        path = _tagged_file(tmp_path, fmt, derived)
        exif, _xmp, _iptc = validator._read_tags(path)
        assert "Exif.Photo.DateTimeOriginal" not in exif
        spec = outputs.OutputSpec("archive" if fmt == "tiff" else "sharing", fmt, "full")
        assert validator.validate_outputs([(path, spec)], derived).ok

    @pytest.mark.parametrize("fmt", ["tiff", "jpeg"])
    def test_a_capture_date_on_an_undated_photo_is_caught(
        self, fmt: str, tmp_path: Path
    ) -> None:
        """There is no capture date in this corpus. A `DateTimeOriginal` that
        appears on a file with no defensible date is a fabricated claim, and
        the reader has to be able to see that it is there."""
        path = _tagged_file(tmp_path, fmt, _tagged_derived(dated=True))
        result = validator.validate_outputs(
            [(path, outputs.OutputSpec("archive" if fmt == "tiff" else "sharing", fmt, "full"))],
            _tagged_derived(dated=False),
        )
        assert not result.ok
        assert any("present on undated photo" in e for e in result.errors)


class TestUnreadableStoresAreNotPasses:
    def test_an_unparseable_xmp_packet_is_an_error_not_an_empty_dict(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "bad.jpg"
        Image.new("RGB", (8, 8), (0, 0, 0)).save(
            path, format="JPEG", quality=95, subsampling=0, xmp=b"<not xml at all"
        )
        with Image.open(path) as img, pytest.raises(validator.MetadataReadbackError):
            validator._read_xmp(img)

    def test_a_missing_defusedxml_is_an_error_rather_than_a_silent_pass(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The quiet failure this reader was most likely to have.

        Pillow does not raise when `defusedxml` is absent: it warns and
        returns `{}`, and `{}` is indistinguishable from "this file has no
        XMP". Every XMP check is driven by what the expectation asks for, so
        a silent `{}` would have turned three of the ten tags into checks
        that cannot fail -- the precise defect this project shipped twice.
        `Image.ElementTree is None` is exactly how Pillow detects it.
        """
        path = tmp_path / "x.jpg"
        Image.new("RGB", (8, 8), (0, 0, 0)).save(
            path,
            format="JPEG",
            quality=95,
            subsampling=0,
            xmp=b'<?xpacket?><x:xmpmeta xmlns:x="adobe:ns:meta/"></x:xmpmeta>',
        )
        monkeypatch.setattr(Image, "ElementTree", None, raising=False)
        with Image.open(path) as img, pytest.raises(
            validator.MetadataReadbackError, match="defusedxml"
        ):
            validator._read_xmp(img)

    def test_that_error_reaches_the_caller_as_a_failed_validation(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "bad2.jpg"
        Image.new("RGB", DECLARED, (0, 0, 0)).save(
            path, format="JPEG", quality=95, subsampling=0, xmp=b"<not xml at all"
        )
        result = validator.validate_outputs(
            [(path, outputs.OutputSpec("sharing", "jpeg", "full"))], _derived(None)
        )
        assert not result.ok
        assert any("readback failed" in e for e in result.errors)

    def test_a_file_with_no_xmp_at_all_is_simply_empty(self, tmp_path: Path) -> None:
        """Absence is not the same as unreadable. A file nobody tagged has no
        packet, and that must not be reported as a broken one."""
        path = _write(tmp_path / "plain.jpg", DECLARED, "jpeg")
        with Image.open(path) as img:
            assert validator._read_xmp(img) == {}
            assert validator._read_iptc(img) == {}
