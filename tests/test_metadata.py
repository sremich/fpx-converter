"""Tier-1 unit tests for metadata extraction and sidecar dump generator.

Tests derived metadata computations, sidecar schema structure, and error
resilience without accessing real photos or external tools.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpx_converter import config, metadata


class TestDerivedMetadata:
    def test_derives_dimensions_and_resolutions(self) -> None:
        psets = {
            "Data Object Store 000001/\x05Image Contents": {
                "sections": [
                    {
                        "properties": {
                            "NumberOfResolutions": {"decoded_value": 6},
                            "HighestResolutionWidth": {"decoded_value": 1152},
                            "HighestResolutionHeight": {"decoded_value": 864},
                            "Res0_SubimageWidth": {"decoded_value": 36},
                            "Res0_SubimageHeight": {"decoded_value": 27},
                            "Res5_SubimageWidth": {"decoded_value": 1152},
                            "Res5_SubimageHeight": {"decoded_value": 864},
                        }
                    }
                ]
            }
        }
        derived = metadata._derive_metadata(psets, entry=None)
        dims = derived["image_dimensions"]
        assert dims["declared_width"] == 1152
        assert dims["declared_height"] == 864
        assert dims["num_resolutions"] == 6
        assert len(dims["resolutions"]) == 2
        assert dims["resolutions"][0] == {"resolution": 0, "width": 36, "height": 27}
        assert dims["resolutions"][1] == {"resolution": 5, "width": 1152, "height": 864}

    def test_detects_90_deg_ccw_viewing_transform(self) -> None:
        # 90 CCW rotation matrix
        rot_matrix = [
            0.0, -1.113, 0.0, 1.113,
            1.113, 0.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ]
        psets = {
            # The declared size has to be here. Without it no crop box can be
            # resolved, and a transform whose geometry cannot be resolved is
            # reported as unsupported rather than assumed to be a plain
            # rotation -- which is the whole point of that branch.
            "Data Object Store 000001/\x05Image Contents": {
                "sections": [
                    {
                        "properties": {
                            "HighestResolutionWidth": {"decoded_value": 1152},
                            "HighestResolutionHeight": {"decoded_value": 864},
                        }
                    }
                ]
            },
            "\x05Transform 000001": {
                "sections": [
                    {
                        "properties": {
                            "SpatialOrientationMatrix": {"decoded_value": rot_matrix},
                            "ResultAspectRatio": {"decoded_value": 1.12},
                        }
                    }
                ]
            },
        }
        derived = metadata._derive_metadata(psets, entry=None)
        tx = derived["viewing_transform"]
        assert tx["has_transform"] is True
        assert tx["is_rotation_90_ccw"] is True
        assert tx["aspect_ratio"] == 1.12
        # A rotated file's TIFF is the declared size with the axes swapped.
        assert tx["tiff_size"] == [864, 1152]

    def test_a_transform_whose_geometry_cannot_be_resolved_is_unsupported(self) -> None:
        """No declared size means no crop box -- and no claim that there is none.

        This used to return a plain `rotate-90-ccw` with `crop_box: null`,
        which is indistinguishable from a rotated file that genuinely carries
        no crop. 14 of the 22 rotated files in this corpus do carry one.
        """
        rot_matrix = [
            0.0, -1.113, 0.0, 1.113,
            1.113, 0.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ]
        psets = {
            "\x05Transform 000001": {
                "sections": [
                    {"properties": {"SpatialOrientationMatrix": {"decoded_value": rot_matrix}}}
                ]
            }
        }
        derived = metadata._derive_metadata(psets, entry=None)
        tx = derived["viewing_transform"]
        assert tx["transform_status"] == "unsupported"
        assert tx["crop_box"] is None
        assert "ResultAspectRatio" in tx["transform_note"]

    def test_derives_camera_make_model_and_software(self) -> None:
        psets = {
            "Data Object Store 000001/\x05Image Info": {
                "sections": [
                    {
                        "properties": {
                            "CameraManufacturerName": {"decoded_value": "Eastman Kodak Company"},
                            "CameraModelName": {"decoded_value": "KODAK DC200/DC210"},
                            "FileSource": {"decoded_value": 3},
                        }
                    }
                ]
            },
            "\x05SummaryInformation": {
                "sections": [
                    {
                        "properties": {
                            "PIDSI_APPNAME": {"decoded_value": "Picture Easy Software 3"},
                        }
                    }
                ]
            },
        }
        derived = metadata._derive_metadata(psets, entry=None)
        cam = derived["camera"]
        assert cam["make"] == "Eastman Kodak Company"
        assert cam["model"] == "KODAK DC200/DC210"
        assert cam["software"] == "Picture Easy Software 3"
        assert cam["file_source"] == 3

    def test_derives_human_caption_title_and_keywords(self) -> None:
        entry = {
            "preferred_name": "Baby on Beach.fpx",
            "preferred_name_is_human_authored": True,
            "albums": ["Summer Vacation 2001", "Family Trip"],
        }
        derived = metadata._derive_metadata({}, entry=entry)
        assert derived["caption_title"] == "Baby on Beach"
        assert derived["iptc_keywords"] == ["Family Trip", "Summer Vacation 2001"]

    def test_camera_generated_name_leaves_caption_title_none(self) -> None:
        entry = {
            "preferred_name": "DCP00123.fpx",
            "preferred_name_is_human_authored": False,
            "albums": ["Sample"],
        }
        derived = metadata._derive_metadata({}, entry=entry)
        assert derived["caption_title"] is None


class TestSidecarBuildingAndDumping:
    def test_builds_complete_sidecar_dict_schema(self) -> None:
        entry = {
            "sha256": "abcdef1234567890",
            "size": 123456,
            "store_name": "photo.fpx",
            "preferred_name": "photo.fpx",
            "preferred_relpath": "Album/photo.fpx",
            "preferred_name_is_human_authored": True,
            "albums": ["Album"],
            "trees": ["TreeA"],
            "duplicate_count": 1,
            "sources": [
                {
                    "relpath": "Album/photo.fpx",
                    "name": "photo.fpx",
                    "album": "Album",
                    "album_path": "Album",
                    "tree": "TreeA",
                    "size": 123456,
                    "mtime": "2001-08-31T19:26:55+00:00",
                }
            ],
        }
        extracted = metadata.ExtractedMetadata(
            sha256="abcdef1234567890",
            store_name="photo.fpx",
            stream_inventory=["\x05SummaryInformation"],
            property_sets={"\x05SummaryInformation": {}},
            extension_storages={"viewpedigree_log": None, "kodak_pedigree": None},
            derived={
                "image_dimensions": {"declared_width": 1152, "declared_height": 864},
                "colour_space": {"colour_space": "NIF_RGB"},
            },
            errors=[],
        )
        sidecar = metadata.build_sidecar_dict(extracted, entry)

        # Check required fields
        assert sidecar["sidecar_version"] == 1
        assert sidecar["sha256"] == "abcdef1234567890"
        assert sidecar["store_name"] == "photo.fpx"
        assert sidecar["stream_inventory"] == ["\x05SummaryInformation"]
        assert "property_sets" in sidecar
        assert "extension_storages" in sidecar
        assert "derived_metadata" in sidecar
        assert sidecar["contributing_sources"] == entry["sources"]

    def test_refuses_to_dump_sidecars_inside_source_root(self, tmp_path: Path) -> None:
        source_root = tmp_path / "source_root"
        source_root.mkdir()
        target_inside = source_root / "sidecars"

        manifest = {"entries": []}
        with pytest.raises(config.SourceWriteRefused):
            metadata.dump_sidecars(
                manifest,
                fpx_dir=tmp_path / "fpx",
                output_dir=target_inside,
                source_root=source_root,
            )

    def test_dumps_sidecars_and_roundtrips_json(self, tmp_path: Path) -> None:
        source_root = tmp_path / "source"
        fpx_dir = tmp_path / "fpx_store"
        out_dir = tmp_path / "output_sidecars"
        source_root.mkdir()
        fpx_dir.mkdir()

        # Write a dummy test propset file
        dummy_fpx = fpx_dir / "test_item.fpx"
        # Write valid minimal OLE property set bytes
        header = bytearray(b"\xfe\xff\x00\x00\x04\x00\x02\x00" + b"\x00" * 16 + b"\x00\x00\x00\x00")
        dummy_fpx.write_bytes(header)

        entry = {
            "sha256": "1122334455667788",
            "size": len(header),
            "store_name": "test_item.fpx",
            "preferred_name": "test_item.fpx",
            "preferred_relpath": "test_item.fpx",
            "preferred_name_is_human_authored": False,
            "albums": ["Sample"],
            "trees": ["TreeA"],
            "duplicate_count": 1,
            "sources": [],
        }
        manifest = {"entries": [entry]}

        report = metadata.dump_sidecars(
            manifest,
            fpx_dir=fpx_dir,
            output_dir=out_dir,
            source_root=source_root,
        )
        assert report.ok
        assert report.written == 1

        sidecar_file = out_dir / "test_item.fpx.json"
        assert sidecar_file.is_file()
        loaded = json.loads(sidecar_file.read_text(encoding="utf-8"))
        assert loaded["sha256"] == "1122334455667788"
