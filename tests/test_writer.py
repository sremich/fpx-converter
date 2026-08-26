"""Tier-1 unit tests for dual output writer and naming scheme.

Tests path calculation, date prefixes, ExifTool argument generation, and mtime
computations with synthetic data. Never imports real photos.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fpx_converter import config, writer


class TestNamingAndPrefixes:
    def test_dated_photo_generates_formatted_prefix(self) -> None:
        ts_dict = {"datetime_original_exif": "2001:07:04 12:34:56"}
        pfx, is_undated = writer.format_date_prefix(ts_dict)
        assert pfx == "2001-07-04_123456"
        assert is_undated is False

    @pytest.mark.parametrize(
        ("precision", "expected"),
        [
            ("month", "2000-08-00_000000"),
            ("season", "2000-08-00_000000"),
            ("year", "2000-00-00_000000"),
        ],
    )
    def test_coarse_folder_date_zeroes_the_components_it_cannot_support(
        self, precision: str, expected: str
    ) -> None:
        # The folder range still orders the file, but the day is written as
        # 00 rather than 01: a real 1st of the month is indistinguishable
        # from a guess once it is in the filename.
        ts_dict = {"folder_date": "2000-08-01", "folder_precision": precision}
        pfx, is_undated = writer.format_date_prefix(ts_dict)
        assert pfx == expected
        assert is_undated is True

    def test_coarse_folder_date_never_yields_a_day_precise_prefix(self) -> None:
        for precision in ("month", "season", "year"):
            pfx, _ = writer.format_date_prefix(
                {"folder_date": "2000-08-01", "folder_precision": precision}
            )
            assert pfx.split("_")[0].endswith("-00"), pfx

    def test_undated_photo_generates_zero_prefix(self) -> None:
        ts_dict = {"datetime_digitized_exif": "1998:02:28 11:34:38"}
        pfx, is_undated = writer.format_date_prefix(ts_dict)
        assert pfx == "0000-00-00_000000"
        assert is_undated is True

    def test_builds_relative_path_for_album_and_preferred_name(self) -> None:
        entry = {
            "albums": ["Holiday Trip 2001"],
            "preferred_name": "Baby on Beach.fpx",
        }
        derived = {
            "timestamps": {"datetime_original_exif": "2001:07:04 12:00:00"},
        }
        rel_tif = writer.build_output_relpath(entry, derived, "tif")
        rel_jpg = writer.build_output_relpath(entry, derived, "jpg")

        assert rel_tif == Path("Holiday Trip 2001") / "2001-07-04_120000_Baby on Beach.tif"
        assert rel_jpg == Path("Holiday Trip 2001") / "2001-07-04_120000_Baby on Beach.jpg"

    def test_preserves_single_fpx_in_doubled_extension_preferred_name(self) -> None:
        entry = {
            "albums": ["Sample"],
            "preferred_name": "DCP00247.fpx.fpx",
        }
        derived = {"timestamps": {}}
        rel_tif = writer.build_output_relpath(entry, derived, "tif")
        assert rel_tif == Path("Sample") / "0000-00-00_000000_DCP00247.fpx.tif"


class TestExifToolArgBuilder:
    def test_constructs_args_for_dated_photo(self) -> None:
        derived = {
            "camera": {
                "make": "Eastman Kodak Company",
                "model": "KODAK DC200/DC210",
                "software": "Picture Easy Software 3",
            },
            "timestamps": {
                "datetime_digitized_exif": "1998:02:28 11:34:38",
                "offset_time_digitized": "-06:00",
                "datetime_original_exif": "2001:07:04 12:00:00",
                "offset_time_original": "-05:00",
            },
            "iptc_keywords": ["Summer 2001", "Family Trip"],
            "caption_title": "Baby on Beach",
        }
        args = writer.build_exiftool_args(derived, [Path("test.tif"), Path("test.jpg")])

        # Check required tags
        assert "-EXIF:Make=Eastman Kodak Company" in args
        assert "-EXIF:Model=KODAK DC200/DC210" in args
        assert "-EXIF:Software=Picture Easy Software 3" in args
        assert "-EXIF:CreateDate=1998:02:28 11:34:38" in args
        assert "-EXIF:OffsetTimeDigitized=-06:00" in args
        assert "-EXIF:DateTimeOriginal=2001:07:04 12:00:00" in args
        assert "-EXIF:OffsetTimeOriginal=-05:00" in args
        assert "-IPTC:Keywords=Summer 2001" in args
        assert "-IPTC:Keywords=Family Trip" in args
        assert "-XMP-dc:Title=Baby on Beach" in args
        assert "-EXIF:ImageDescription=Baby on Beach" in args

    def test_undated_photo_omits_datetime_original_tag(self) -> None:
        derived = {
            "camera": {"make": "Eastman Kodak Company", "model": "KODAK DC200/DC210"},
            "timestamps": {
                "datetime_digitized_exif": "1998:02:28 11:34:38",
                "offset_time_digitized": "-06:00",
                "datetime_original_exif": None,
            },
            "iptc_keywords": ["Sample"],
        }
        args = writer.build_exiftool_args(derived, [Path("test.tif")])

        assert "-EXIF:CreateDate=1998:02:28 11:34:38" in args
        # DateTimeOriginal must NOT be in args for undated photos
        assert not any("DateTimeOriginal" in a for a in args)


class TestMtimeComputationAndGuards:
    def test_computes_mtime_epoch_from_datetime_original(self) -> None:
        derived = {
            "timestamps": {"datetime_original_exif": "2001:07:04 12:00:00"},
        }
        epoch = writer.compute_mtime_epoch(derived)
        assert epoch > 990000000.0

    def test_refuses_output_inside_source_root(self, tmp_path: Path) -> None:
        source_root = tmp_path / "source"
        source_root.mkdir()
        target_inside = source_root / "output"

        with pytest.raises(config.SourceWriteRefused):
            writer.write_single_entry_dual_output(
                fpx_path=tmp_path / "photo.fpx",
                entry={"store_name": "photo.fpx"},
                output_root=target_inside,
                source_root=source_root,
            )
