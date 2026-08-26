"""Tier-2: metadata extraction and sidecar dump over real committed `.fpx` fixtures.

The four fixtures are non-personal Kodak stock sample images that shipped with
Picture Easy. Never add personal photos here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpx_converter import metadata, scan

pytestmark = pytest.mark.fixtures

FIXTURES = Path(__file__).parent / "fixtures"

EXPECTED_FIXTURE_DETAILS = {
    "Clouds01.fpx": {
        "width": 1152,
        "height": 864,
        "num_resolutions": 6,
        "file_source": 5,
        "software": "Picture Easy Software 3",
        "scanner": None,
    },
    "P0000016.FPX": {
        "width": 640,
        "height": 480,
        "num_resolutions": 5,
        "file_source": 5,
        "software": "Picture Easy Software 3",
        "scanner": None,
    },
    "harbor.fpx": {
        "width": 768,
        "height": 512,
        "num_resolutions": 5,
        "file_source": 1,
        "software": "Picture Easy Software",
        "scanner_make": "KODAK     /4220",
        "scanner_model": "FilmScanner 2000",
    },
    "squirrel.fpx": {
        "width": 996,
        "height": 1536,
        "num_resolutions": 6,
        "file_source": 5,
        "software": "Picture Easy Software 3",
        "scanner": None,
    },
}


def test_metadata_extracts_all_property_sets_from_real_fixtures() -> None:
    for filename, expected in EXPECTED_FIXTURE_DETAILS.items():
        fpx_path = FIXTURES / filename
        assert fpx_path.is_file()

        meta = metadata.extract_fpx_metadata(fpx_path)
        assert not meta.errors, f"{filename} had extraction errors: {meta.errors}"

        # 1. Image dimensions
        dims = meta.derived["image_dimensions"]
        assert dims["declared_width"] == expected["width"], f"{filename} width mismatch"
        assert dims["declared_height"] == expected["height"], f"{filename} height mismatch"
        assert (
            dims["num_resolutions"] == expected["num_resolutions"]
        ), f"{filename} res count mismatch"
        assert len(dims["resolutions"]) == expected["num_resolutions"]

        # 2. Colour space: all 4 stock fixtures are NIF RGB
        col = meta.derived["colour_space"]
        assert col["colour_space"] == "NIF_RGB"
        assert col["channel_count"] == 3

        # 3. Standard property sets are parsed
        psets = meta.property_sets
        assert "\x05SummaryInformation" in psets
        assert "\x05Global Info" in psets
        assert "\x05Transform 000001" in psets
        assert "Data Object Store 000001/\x05Image Contents" in psets
        assert "Data Object Store 000001/\x05Image Info" in psets
        assert "Data Object Store 000001/\x05SummaryInformation" in psets

        # 4. Import timestamp is present and parsed
        ts = meta.derived["timestamps"]
        assert ts["import_datetime"] is not None
        assert ts["datetime_digitized_exif"] is not None
        assert ts["offset_time_digitized"] is not None

        # 5. Software & File source
        cam = meta.derived["camera"]
        assert cam["software"] == expected["software"]
        assert cam["file_source"] == expected["file_source"]


def test_scanner_identity_on_harbor_fixture() -> None:
    meta = metadata.extract_fpx_metadata(FIXTURES / "harbor.fpx")
    scanner = meta.derived["scanner"]
    assert scanner is not None
    assert scanner["manufacturer"] == "KODAK     /4220"
    assert scanner["model"] == "FilmScanner 2000"


def test_sidecar_dump_end_to_end_over_fixtures(tmp_path: Path) -> None:
    from fpx_converter import manifest as manifest_mod

    scanned, _ = scan.scan_tree(FIXTURES, progress_every=0)
    manifest = manifest_mod.build(scanned, source_root=FIXTURES, tool_version="test")

    out_dir = tmp_path / "sidecars"
    report = metadata.dump_sidecars(
        manifest,
        fpx_dir=FIXTURES,
        output_dir=out_dir,
        source_root=FIXTURES,
    )
    assert report.ok
    assert report.written == len(EXPECTED_FIXTURE_DETAILS)

    for entry in manifest["entries"]:
        store_name = entry["store_name"]
        sidecar_path = out_dir / f"{store_name}.json"
        assert sidecar_path.is_file(), f"Missing sidecar for {store_name}"

        data = json.loads(sidecar_path.read_text(encoding="utf-8"))
        assert data["sidecar_version"] == 1
        assert data["sha256"] == entry["sha256"]
        assert data["store_name"] == store_name
        assert "property_sets" in data
        assert "derived_metadata" in data
        assert not data["extraction_errors"]
