"""Tier-1 unit tests for dual output writer and naming scheme.

Tests path calculation, date prefixes, ExifTool argument generation, and mtime
computations with synthetic data. Never imports real photos.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from fpx_converter import config, decoder, naming, writer


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


class TestOutputNameCollisions:
    """Two distinct photos must never resolve to one output file.

    The date prefix does not separate them -- files in one album usually
    share it -- so the stem is the only thing keeping them apart.
    """

    def test_same_name_in_same_album_gets_distinct_stems(self) -> None:
        sha_a = "a" * 64
        sha_b = "b" * 64
        stems = naming.assign_output_stems(
            [
                (sha_a, "Holiday Trip 2001", "DCP00247.fpx"),
                (sha_b, "Holiday Trip 2001", "DCP00247.fpx"),
            ]
        )
        assert stems[sha_a] != stems[sha_b]
        assert len(set(stems.values())) == 2

    def test_same_name_in_different_albums_keeps_both_bare(self) -> None:
        # Different album folders already separate them, so neither name
        # needs disfiguring with a hash.
        sha_a, sha_b = "a" * 64, "b" * 64
        stems = naming.assign_output_stems(
            [
                (sha_a, "Album One", "Picnic.fpx"),
                (sha_b, "Album Two", "Picnic.fpx"),
            ]
        )
        assert stems[sha_a] == "Picnic"
        assert stems[sha_b] == "Picnic"

    def test_assignment_is_stable_across_input_order(self) -> None:
        # A resumed run must assign the same names as the run it resumes.
        sha_a, sha_b = "a" * 64, "b" * 64
        pairs = [
            (sha_a, "Album", "Same.fpx"),
            (sha_b, "Album", "Same.fpx"),
        ]
        assert naming.assign_output_stems(pairs) == naming.assign_output_stems(pairs[::-1])

    def test_source_named_like_the_fallback_does_not_steal_it(self) -> None:
        # A file literally named `Same_aaaaaaaa.fpx` claims the disambiguated
        # name first; the next claimant must keep going rather than collide.
        sha_a, sha_b, sha_c = "a" * 64, "b" * 64, "c" * 64
        stems = naming.assign_output_stems(
            [
                (sha_a, "Album", "Same.fpx"),
                (sha_b, "Album", "Same.fpx"),
                (sha_c, "Album", f"Same_{sha_b[:8]}.fpx"),
            ]
        )
        assert len(set(stems.values())) == 3

    def test_distinct_relpaths_for_colliding_entries(self) -> None:
        derived = {"timestamps": {"datetime_original_exif": "2001:07:04 00:00:00"}}
        entry = {"albums": ["Album"], "preferred_name": "DCP00247.fpx"}
        first = writer.build_output_relpath(entry, derived, "tif", "DCP00247")
        second = writer.build_output_relpath(entry, derived, "tif", "DCP00247_bbbbbbbb")
        assert first != second


class TestDualImageSaving:
    """What actually lands on disk for a cropped photo.

    The decision this pins down: `archive/` keeps every pixel the camera
    captured, `sharing/` shows the composition somebody framed in 2002. Both
    halves have to be true at once, and until this test existed neither was
    checked anywhere -- all four committed fixtures are identity, and the
    files that carry crops are personal and cannot be committed.
    """

    @staticmethod
    def _decoded(crop: tuple[int, int, int, int] | None) -> decoder.DecodedImage:
        img = Image.new("RGB", (1152, 864), (10, 20, 30))
        # A mark outside the crop box, so a JPEG that kept the full frame is
        # distinguishable from one that was cropped to the same size.
        img.paste((255, 0, 0), (0, 0, 40, 40))
        return decoder.DecodedImage(
            image=img,
            declared_width=1152,
            declared_height=864,
            colour_space="NIF_RGB",
            resolution_index=0,
            rotation_applied=0,
            crop_applied=crop,
        )

    def test_tiff_keeps_the_full_frame_while_the_jpeg_is_cropped(
        self, tmp_path: Path
    ) -> None:
        tif, jpg = tmp_path / "a.tif", tmp_path / "a.jpg"
        writer.save_dual_images(self._decoded((200, 150, 900, 700)), tif, jpg)

        with Image.open(tif) as im:
            assert im.size == (1152, 864), "the archival TIFF lost pixels the camera captured"
        with Image.open(jpg) as im:
            assert im.size == (700, 550), "the JPEG was not cropped to the declared box"
            # The red corner sits outside the crop box, so it must be gone.
            assert im.convert("RGB").getpixel((5, 5))[0] < 100

    def test_an_uncropped_photo_yields_two_identically_sized_files(
        self, tmp_path: Path
    ) -> None:
        tif, jpg = tmp_path / "b.tif", tmp_path / "b.jpg"
        writer.save_dual_images(self._decoded(None), tif, jpg)
        with Image.open(tif) as t_im, Image.open(jpg) as j_im:
            assert t_im.size == j_im.size == (1152, 864)

    def test_both_outputs_are_tagged_srgb(self, tmp_path: Path) -> None:
        # An untagged archival file leaves its colour meaning to whatever the
        # viewer assumes.
        tif, jpg = tmp_path / "c.tif", tmp_path / "c.jpg"
        writer.save_dual_images(self._decoded((0, 0, 600, 400)), tif, jpg)
        with Image.open(tif) as t_im, Image.open(jpg) as j_im:
            assert t_im.info.get("icc_profile")
            assert j_im.info.get("icc_profile")

    def test_the_tiff_is_deflate_compressed(self, tmp_path: Path) -> None:
        tif, jpg = tmp_path / "d.tif", tmp_path / "d.jpg"
        writer.save_dual_images(self._decoded(None), tif, jpg)
        with Image.open(tif) as t_im:
            assert t_im.tag_v2.get(259) in (8, 32946)
