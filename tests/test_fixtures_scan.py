"""Tier-2: the scan and ingest path over real `.fpx` files.

The four fixtures are Kodak stock sample images that shipped with Picture
Easy — a squirrel on a fence, a harbour, a cloud time-lapse frame, and one
frame of a burst sequence on a station platform. **No identifiable person
appears in any of them** (the platform frame has one small, distant,
unidentifiable figure), which is why these four and only these four are
committed. Never add a family photo here.

The pinned hashes are load-bearing twice over: they catch a fixture that got
corrupted or replaced, and they catch a scanner that silently reads the wrong
bytes.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from fpx_converter import ingest as ingest_mod
from fpx_converter import manifest as manifest_mod
from fpx_converter import scan

pytestmark = pytest.mark.fixtures

FIXTURES = Path(__file__).parent / "fixtures"

EXPECTED = {
    "Clouds01.fpx": ("77a413cc466b5c3b8be7045079428094ff016be0fdbe839006d0a9c8259ceb07", 326656),
    "P0000016.FPX": ("346fde190a07e7cd6e5f569c9d56d0e71452f31e68c2485ed6fb3b83454b2dbc", 241788),
    "harbor.fpx": ("b2a934b0051e464dd11358b07031dd316ddebcb3d150038822a64226814930d3", 1629696),
    "squirrel.fpx": ("0ce6651ae6940e0ad341dae6344b56dc3d5a80b7bb77a7de7cfa70d0bbbe06b1", 1820672),
}

#: Present in every FlashPix file this project will ever see. If a future
#: change makes one of these disappear from the inventory, the scanner has
#: stopped seeing inside the container.
REQUIRED_STREAMS = {
    "\x05SummaryInformation",
    "\x05Transform 000001",
    "Data Object Store 000001/\x05Image Contents",
    "Data Object Store 000001/\x05Image Info",
}


def test_fixtures_are_present_and_unmodified() -> None:
    found = {p.name for p in FIXTURES.iterdir() if p.suffix.lower() == ".fpx"}
    assert found == set(EXPECTED)
    for name, (sha, size) in EXPECTED.items():
        path = FIXTURES / name
        assert path.stat().st_size == size, f"{name} changed size"
        assert scan.sha256_file(path) == sha, f"{name} is not the committed fixture"


def test_case_insensitive_discovery_finds_the_uppercase_file() -> None:
    """One fixture is `.FPX` on purpose: Kodak wrote both cases."""
    names = {p.name for p in scan.iter_fpx_files(FIXTURES)}
    assert "P0000016.FPX" in names
    assert len(names) == len(EXPECTED)


def test_scan_reads_the_flashpix_structure() -> None:
    scanned, _ = scan.scan_tree(FIXTURES, progress_every=0)
    assert len(scanned) == len(EXPECTED)
    for item in scanned:
        expected_sha, expected_size = EXPECTED[item.name]
        assert item.sha256 == expected_sha
        assert item.size == expected_size
        assert item.is_ole is True
        assert item.ole_error is None
        missing = REQUIRED_STREAMS - set(item.streams)
        assert not missing, f"{item.name} is missing {missing}"


def test_scanning_does_not_modify_the_fixtures() -> None:
    """The read-only promise, exercised against real files."""
    scanned, snapshot = scan.scan_tree(FIXTURES, progress_every=0)
    hashes = {str(i.path): i.sha256 for i in scanned}
    report = scan.verify_unchanged(snapshot, FIXTURES, hashes, sample_size=len(EXPECTED))
    assert report.resampled == len(EXPECTED)
    assert report.ok, (report.modified, report.vanished, report.added, report.rehash_mismatches)


def test_manifest_over_real_files(tmp_path: Path) -> None:
    scanned, _ = scan.scan_tree(FIXTURES, progress_every=0)
    manifest = manifest_mod.build(scanned, source_root=FIXTURES, tool_version="test")
    assert manifest["counts"]["files_seen"] == len(EXPECTED)
    assert manifest["counts"]["distinct_sha256"] == len(EXPECTED)
    assert manifest["counts"]["not_ole"] == 0

    # P0000016 is camera-named; the other three are not.
    assert manifest["counts"]["human_authored_names"] == 3

    path = tmp_path / "manifest.json"
    manifest_mod.write(path, manifest)
    assert manifest_mod.load(path) == manifest


class TestIngest:
    def test_copies_and_verifies_every_file(self, tmp_path: Path) -> None:
        scanned, _ = scan.scan_tree(FIXTURES, progress_every=0)
        manifest = manifest_mod.build(scanned, source_root=FIXTURES, tool_version="test")
        dest = tmp_path / "store"

        report = ingest_mod.ingest(manifest, source_root=FIXTURES, dest_dir=dest)
        assert report.ok, report.failures
        assert report.copied == len(EXPECTED)
        assert report.skipped == 0
        assert not ingest_mod.verify_store(manifest, dest_dir=dest)

    def test_second_run_skips_everything(self, tmp_path: Path) -> None:
        """Resume-by-hash: an interrupted ingest costs the current file only."""
        scanned, _ = scan.scan_tree(FIXTURES, progress_every=0)
        manifest = manifest_mod.build(scanned, source_root=FIXTURES, tool_version="test")
        dest = tmp_path / "store"

        ingest_mod.ingest(manifest, source_root=FIXTURES, dest_dir=dest)
        second = ingest_mod.ingest(manifest, source_root=FIXTURES, dest_dir=dest)
        assert second.copied == 0
        assert second.skipped == len(EXPECTED)

    def test_a_corrupted_copy_is_replaced_not_trusted(self, tmp_path: Path) -> None:
        scanned, _ = scan.scan_tree(FIXTURES, progress_every=0)
        manifest = manifest_mod.build(scanned, source_root=FIXTURES, tool_version="test")
        dest = tmp_path / "store"
        ingest_mod.ingest(manifest, source_root=FIXTURES, dest_dir=dest)

        victim = dest / manifest["entries"][0]["store_name"]
        victim.write_bytes(b"corrupted")
        assert ingest_mod.verify_store(manifest, dest_dir=dest)

        again = ingest_mod.ingest(manifest, source_root=FIXTURES, dest_dir=dest)
        assert again.copied == 1
        assert again.ok
        assert not ingest_mod.verify_store(manifest, dest_dir=dest)

    def test_missing_copy_is_reported_by_verify(self, tmp_path: Path) -> None:
        scanned, _ = scan.scan_tree(FIXTURES, progress_every=0)
        manifest = manifest_mod.build(scanned, source_root=FIXTURES, tool_version="test")
        dest = tmp_path / "store"
        ingest_mod.ingest(manifest, source_root=FIXTURES, dest_dir=dest)
        (dest / manifest["entries"][0]["store_name"]).unlink()
        problems = ingest_mod.verify_store(manifest, dest_dir=dest)
        assert len(problems) == 1
        assert "missing" in problems[0][1]

    def test_duplicates_across_albums_collapse_to_one_copy(self, tmp_path: Path) -> None:
        """The corpus is 1,265 files but only 687 distinct hashes."""
        staged = tmp_path / "src"
        (staged / "AlbumOne").mkdir(parents=True)
        (staged / "AlbumTwo").mkdir(parents=True)
        shutil.copy2(FIXTURES / "squirrel.fpx", staged / "AlbumOne" / "DCP00123.fpx")
        shutil.copy2(FIXTURES / "squirrel.fpx", staged / "AlbumTwo" / "squirrel on a fence.fpx")

        scanned, _ = scan.scan_tree(staged, progress_every=0)
        manifest = manifest_mod.build(scanned, source_root=staged, tool_version="test")
        assert manifest["counts"]["files_seen"] == 2
        assert manifest["counts"]["distinct_sha256"] == 1

        entry = manifest["entries"][0]
        assert entry["duplicate_count"] == 2
        assert entry["albums"] == ["AlbumOne", "AlbumTwo"]
        # The human-authored name is the one that survives the collapse.
        assert entry["store_name"] == "squirrel on a fence.fpx"

        dest = tmp_path / "store"
        report = ingest_mod.ingest(manifest, source_root=staged, dest_dir=dest)
        assert report.copied == 1
        assert [p.name for p in dest.iterdir()] == ["squirrel on a fence.fpx"]
