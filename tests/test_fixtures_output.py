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

#: Set in CI. Turns a missing ExifTool from a skip into a failure.
#:
#: These tests are the only place the project's "validate with a different
#: tool than the one that wrote" rule is actually exercised. Skipping them
#: silently is worse than not having them: a green suite then implies a
#: round-trip nobody ran. Locally, where ExifTool may genuinely be absent,
#: the skip is still the right behaviour -- so the strictness is opt-in and
#: CI opts in.
REQUIRE_EXIFTOOL = os.environ.get("FPX_REQUIRE_EXIFTOOL", "").strip() not in ("", "0")

needs_exiftool = pytest.mark.skipif(
    not HAVE_EXIFTOOL and not REQUIRE_EXIFTOOL,
    reason="ExifTool not installed or not found on PATH",
)


def test_exiftool_is_present_when_required() -> None:
    """Fail loudly in CI if ExifTool went missing, instead of skipping."""
    if not REQUIRE_EXIFTOOL:
        pytest.skip("FPX_REQUIRE_EXIFTOOL is not set; ExifTool tests may skip")
    assert HAVE_EXIFTOOL, (
        "FPX_REQUIRE_EXIFTOOL is set but no ExifTool was found. The tier-2 "
        "write/read-back tests would have skipped, leaving the metadata "
        "chain unverified while the suite reported green."
    )

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


@needs_exiftool
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
            # Unconditional: guarding this on `jpg_img.layer` being present
            # is what let the validator pass a file whose sampling it could
            # not read, and the same shape has no place in the test either.
            assert jpg_img.layer, "Pillow reported no JPEG component sampling table"
            sampling_factors = [(comp[1], comp[2]) for comp in jpg_img.layer]
            assert all(sf == (1, 1) for sf in sampling_factors)

        # 4. Independent pyexiv2 validation call
        val = validator.validate_dual_output(res.tif_path, res.jpg_path, exp_info)
        assert val.ok, f"pyexiv2 validation failed on {filename}: {val.errors}"

        # 5. Assert mtime set on all files
        mtime_tif = os.stat(res.tif_path).st_mtime
        mtime_jpg = os.stat(res.jpg_path).st_mtime
        assert abs(mtime_tif - mtime_jpg) < 2.0


@needs_exiftool
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


@needs_exiftool
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



def test_claimed_paths_refuse_a_repeat_write(tmp_path: Path) -> None:
    """A second entry resolving to the same path must raise, not overwrite.

    Belt and braces behind `naming.assign_output_stems`: if a collision ever
    does reach the writer, losing a photo to it would leave no trace -- the
    run would report both files converted.
    """
    entry = {
        "store_name": "Clouds01.fpx",
        "preferred_name": "Clouds01.fpx",
        "albums": ["Album"],
        "sha256": "a" * 64,
    }
    common = {
        "entry": entry,
        "output_root": tmp_path / "out",
        "source_root": FIXTURES,
        "dry_run": True,
        "claimed": set(),
    }
    writer.write_single_entry_dual_output(fpx_path=FIXTURES / "Clouds01.fpx", **common)
    with pytest.raises(writer.WriterError, match="collision"):
        writer.write_single_entry_dual_output(fpx_path=FIXTURES / "Clouds01.fpx", **common)


def test_validator_rejects_a_subsampled_jpeg(tmp_path: Path) -> None:
    """The 4:4:4 check must actually notice 4:2:0.

    It used to sit behind `if jpg_img.layer:`, so a file whose sampling
    table could not be read validated clean. A check that cannot fail is
    indistinguishable from no check.
    """
    from fpx_converter import decoder

    decoded = decoder.decode_fpx(FIXTURES / "Clouds01.fpx", apply_transform=True)
    tif_path = tmp_path / "a.tif"
    good_jpg = tmp_path / "good.jpg"
    bad_jpg = tmp_path / "bad.jpg"

    decoded.image.save(tif_path, format="TIFF", compression="tiff_deflate")
    decoded.image.save(good_jpg, format="JPEG", quality=95, subsampling=0)  # 4:4:4
    decoded.image.save(bad_jpg, format="JPEG", quality=95, subsampling=2)  # 4:2:0

    expected: dict = {"camera": {}, "timestamps": {}, "iptc_keywords": []}

    good = validator.validate_dual_output(tif_path, good_jpg, expected)
    assert good.ok, good.errors

    bad = validator.validate_dual_output(tif_path, bad_jpg, expected)
    assert not bad.ok
    assert any("4:4:4" in e for e in bad.errors), bad.errors


def test_outputs_are_tagged_srgb(tmp_path: Path) -> None:
    """Both outputs carry an ICC profile.

    An untagged TIFF is interpreted as whatever the viewer assumes. For an
    archival file that is a guess, and colour is one of the two things
    tier 4 checks by eye.
    """
    res = writer.write_single_entry_dual_output(
        fpx_path=FIXTURES / "Clouds01.fpx",
        entry={
            "store_name": "Clouds01.fpx",
            "preferred_name": "Clouds01.fpx",
            "albums": ["Sample Images"],
            "sha256": "0" * 64,
        },
        output_root=tmp_path / "out",
        source_root=FIXTURES,
    )
    for path in (res.tif_path, res.jpg_path):
        with Image.open(path) as img:
            assert img.info.get("icc_profile"), f"{path.suffix} has no ICC profile"


def test_sidecar_preserves_binary_payloads(tmp_path: Path) -> None:
    """The sidecar carries the actual bytes, not a 32-byte preview.

    The embedded thumbnail DIB and the external JPEG tables are the two
    properties anyone would come back to this sidecar for; both used to be
    discarded on the way to JSON while the file still claimed to hold every
    raw value.
    """
    import base64
    import hashlib

    from fpx_converter import metadata as metadata_mod

    entry = {
        "sha256": "0" * 64,
        "store_name": "Clouds01.fpx",
        "preferred_name": "Clouds01.fpx",
        "albums": ["Sample Images"],
    }
    meta = metadata_mod.extract_fpx_metadata(FIXTURES / "Clouds01.fpx", manifest_entry=entry)
    sidecar = metadata_mod.build_sidecar_dict(meta, entry)

    thumb = sidecar["property_sets"]["\x05SummaryInformation"]["sections"][0]["properties"][
        "PIDSI_THUMBNAIL"
    ]["raw_value"]

    assert thumb["raw_length"] > 1000
    assert thumb["raw_base64"], "thumbnail bytes were dropped from the sidecar"
    recovered = base64.b64decode(thumb["raw_base64"])
    assert len(recovered) == thumb["raw_length"]
    assert hashlib.sha256(recovered).hexdigest() == thumb["raw_sha256"]
