"""Tier-2: end-to-end dual output generation and pyexiv2 validation over committed fixtures.

The four fixtures are non-personal Kodak stock sample images. Never add personal photos.
"""

from __future__ import annotations

import os
from pathlib import Path

import pyexiv2
import pytest
from PIL import Image

from fpx_converter import validator, writer

pytestmark = pytest.mark.fixtures

FIXTURES = Path(__file__).parent / "fixtures"
HAVE_EXIFTOOL = writer.resolve_exiftool_path() is not None

EXPECTED_FIXTURE_DERIVED = {
    "Clouds01.fpx": {
        "width": 1152,
        "height": 864,
        "albums": ["Sample Images"],
        "camera": {
            "make": None,
            "model": None,
            "software": "Picture Easy Software 3",
        },
        "timestamps": {
            "datetime_digitized_exif": "1998:02:28 11:34:38",
            "offset_time_digitized": "-06:00",
            "datetime_original_exif": None,  # undated fixture
        },
        "iptc_keywords": ["Sample Images"],
    },
    "P0000016.FPX": {
        "width": 640,
        "height": 480,
        "albums": ["Stock Photos"],
        "camera": {
            "make": None,
            "model": None,
            "software": "Picture Easy Software 3",
        },
        "timestamps": {
            "datetime_digitized_exif": "1998:03:02 09:39:16",
            "offset_time_digitized": "-06:00",
            "datetime_original_exif": None,
        },
        "iptc_keywords": ["Stock Photos"],
    },
    "harbor.fpx": {
        "width": 768,
        "height": 512,
        "albums": ["Kodak Demos"],
        "camera": {
            "make": None,
            "model": None,
            "software": "Picture Easy Software",
        },
        "scanner": {
            "manufacturer": "KODAK     /4220",
            "model": "FilmScanner 2000",
        },
        "timestamps": {
            "datetime_digitized_exif": "1998:01:23 17:47:46",
            "offset_time_digitized": "-06:00",
            "datetime_original_exif": None,
        },
        "iptc_keywords": ["Kodak Demos"],
    },
    "squirrel.fpx": {
        "width": 996,
        "height": 1536,
        "albums": ["Wildlife"],
        "camera": {
            "make": None,
            "model": None,
            "software": "Picture Easy Software 3",
        },
        "timestamps": {
            "datetime_digitized_exif": "1998:03:25 17:50:27",
            "offset_time_digitized": "-06:00",
            "datetime_original_exif": None,
        },
        "iptc_keywords": ["Wildlife"],
    },
}


@pytest.mark.skipif(not HAVE_EXIFTOOL, reason="ExifTool not installed or not found on PATH")
def test_dual_output_on_all_fixtures_and_validates_with_pyexiv2(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    source_root = FIXTURES

    for filename, exp_info in EXPECTED_FIXTURE_DERIVED.items():
        fpx_path = FIXTURES / filename
        assert fpx_path.is_file()

        entry = {
            "store_name": filename,
            "preferred_name": filename,
            "albums": exp_info["albums"],
            "sha256": "0" * 64,
        }

        # 1. Execute dual output write
        res = writer.write_single_entry_dual_output(
            fpx_path=fpx_path,
            entry=entry,
            output_root=output_root,
            source_root=source_root,
        )

        assert res.validation_ok, f"Validation failed for {filename}: {res.errors}"
        assert not res.errors

        # 2. Assert output files exist in archive/ and sharing/
        assert res.tif_path.is_file()
        assert res.jpg_path.is_file()
        assert res.sidecar_path.is_file()
        assert res.fpx_copy_path.is_file()

        # 3. Assert TIFF Deflate compression and JPEG 4:4:4
        with Image.open(res.tif_path) as tif_img:
            assert tif_img.size == (exp_info["width"], exp_info["height"])
            comp_tag = tif_img.tag_v2.get(259)
            assert comp_tag in (8, 32946) or tif_img.info.get("compression") in (
                "tiff_adobe_deflate",
                "tiff_deflate",
            )

        with Image.open(res.jpg_path) as jpg_img:
            assert jpg_img.size == (exp_info["width"], exp_info["height"])
            if hasattr(jpg_img, "layer") and jpg_img.layer:
                sampling_factors = [(comp[1], comp[2]) for comp in jpg_img.layer]
                assert all(sf == (1, 1) for sf in sampling_factors)

        # 4. Independent pyexiv2 validation call
        val = validator.validate_dual_output(res.tif_path, res.jpg_path, exp_info)
        assert val.ok, f"pyexiv2 validation failed on {filename}: {val.errors}"

        # 5. Assert mtime set on all files
        mtime_tif = os.stat(res.tif_path).st_mtime
        mtime_jpg = os.stat(res.jpg_path).st_mtime
        assert abs(mtime_tif - mtime_jpg) < 2.0


@pytest.mark.skipif(not HAVE_EXIFTOOL, reason="ExifTool not installed or not found on PATH")
def test_dual_output_with_dated_entry_and_caption(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    source_root = FIXTURES
    fpx_path = FIXTURES / "Clouds01.fpx"

    entry = {
        "store_name": "Clouds01.fpx",
        "preferred_name": "Summer Sky Over Beach.fpx",
        "preferred_name_is_human_authored": True,
        "albums": ["4th of July 2001"],
        "sha256": "0" * 64,
    }

    res = writer.write_single_entry_dual_output(
        fpx_path=fpx_path,
        entry=entry,
        output_root=output_root,
        source_root=source_root,
    )

    assert res.validation_ok, f"Validation failed: {res.errors}"
    assert res.tif_path.name == "2001-07-04_000000_Summer Sky Over Beach.tif"
    assert res.jpg_path.name == "2001-07-04_000000_Summer Sky Over Beach.jpg"
    assert res.tif_path.parent.name == "4th of July 2001"

    # Read back with pyexiv2 to verify DateTimeOriginal and Caption/Title
    with pyexiv2.Image(str(res.jpg_path)) as meta:
        exif = meta.read_exif()
        xmp = meta.read_xmp()
        iptc = meta.read_iptc()

        # Midnight on the day the folder names. The 11:34:38 belongs to the
        # 1998 import stamp below and must not be borrowed to dress this up
        # as a precise capture moment.
        assert exif.get("Exif.Photo.DateTimeOriginal") == "2001:07:04 00:00:00"
        assert exif.get("Exif.Photo.DateTimeDigitized") == "1998:02:28 11:34:38"
        assert exif.get("Exif.Image.ImageDescription") == "Summer Sky Over Beach"
        assert "4th of July 2001" in iptc.get("Iptc.Application2.Keywords", [])
        title = xmp.get("Xmp.dc.title", {})
        assert title.get('lang="x-default"') == "Summer Sky Over Beach"


@pytest.mark.skipif(not HAVE_EXIFTOOL, reason="ExifTool not installed or not found on PATH")
def test_year_only_album_gets_no_datetime_original(tmp_path: Path) -> None:
    """A folder naming only a year must not produce a capture date.

    This is the tier-2 half of the corpus's largest dating hazard: 151 of its
    687 files sit in albums named for a year, a span, or a season. Writing
    the 1st of January for those would be indistinguishable, in the finished
    archive, from a date somebody actually knew.
    """
    entry = {
        "store_name": "Clouds01.fpx",
        "preferred_name": "Backyard.fpx",
        "preferred_name_is_human_authored": True,
        "albums": ["Assorted 2001"],
        "sha256": "0" * 64,
    }

    res = writer.write_single_entry_dual_output(
        fpx_path=FIXTURES / "Clouds01.fpx",
        entry=entry,
        output_root=tmp_path / "output",
        source_root=FIXTURES,
    )

    assert res.validation_ok, f"Validation failed: {res.errors}"
    assert res.is_undated is True
    assert res.tif_path.name == "2001-00-00_000000_Backyard.tif"

    for path in (res.tif_path, res.jpg_path):
        with pyexiv2.Image(str(path)) as meta:
            exif = meta.read_exif()
            assert "Exif.Photo.DateTimeOriginal" not in exif
            assert "Exif.Photo.OffsetTimeOriginal" not in exif
            # The import stamp is still recorded -- in the field for it.
            assert exif.get("Exif.Photo.DateTimeDigitized") == "1998:02:28 11:34:38"

