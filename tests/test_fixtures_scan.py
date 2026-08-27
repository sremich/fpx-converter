"""Tier-2: the scan and ingest path over real `.fpx` files.

Every fixture is an image containing **no people**: the Kodak stock samples
that shipped with Picture Easy, plus archive photographs confirmed
person-free by eye and renamed to a neutral stem -- butterflies in a
conservatory, a cloud time-lapse, modelling clay on a table, an empty station
platform. Never add a photograph with a person in it.

The pinned hashes are load-bearing twice over: they catch a fixture that got
corrupted or replaced, and they catch a scanner that silently reads the wrong
bytes. Regenerate this table only when fixtures are deliberately added --
never to make a red test go green, which is the one failure it exists to
report.
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
    "clay01.fpx": (
        "53e21ff585fd897231c7c6528ff98ae0b198ab237e20e5fdb5ee29b921b04483",
        247808,
    ),
    "clay02.fpx": (
        "ba0d39622eb93b20874d170ea4c54fed01970ec0a0aa8ebadf95625142a692a5",
        212992,
    ),
    "clay03.fpx": (
        "0db37500beaaf62f8dcaedcb194ac837bb21dfb3f13973ff925a47aff8258fbb",
        201728,
    ),
    "clay04.fpx": (
        "1af3c8ffd233e4e5f0d5ddf635c334611ad12c3c3942b9e07d0172aad1388fa1",
        210432,
    ),
    "Clouds01.fpx": (
        "77a413cc466b5c3b8be7045079428094ff016be0fdbe839006d0a9c8259ceb07",
        326656,
    ),
    "clouds02.fpx": (
        "e41db63d50752cee19f3d82049b1c19996a6cd6fed66597e70b482bd82a11f4b",
        316416,
    ),
    "clouds03.fpx": (
        "8d1e98de10aa3b3cda413fa9073f659d2868049203735580fda0098f8a7f04e0",
        325632,
    ),
    "clouds04.fpx": (
        "35ca68221443e8adca5ab30d1ded59a63a5e4c1ee1fbdee35e3d82e32e2840e7",
        324096,
    ),
    "clouds05.fpx": (
        "7f44c8b09ad3e5c5efa4bf5905418fca0005e20bf5e09627177d09b55b2e1877",
        334848,
    ),
    "clouds06.fpx": (
        "23fec4da94a56cf50a77a878ca7915d9ade5fa2bd23799ea363fbca171f7c3ff",
        332800,
    ),
    "clouds07.fpx": (
        "4b2910ca86e6eb6eda9e749e634dd53c0de01a31ecf210753f8372b0994aed4f",
        339968,
    ),
    "clouds08.fpx": (
        "a97caebfccab13943418e321e9f0fac016c90ac45a062ce45171aad16fac3654",
        337920,
    ),
    "clouds09.fpx": (
        "fed9cc74a18b26dca92d784bb881b41ce9605a3b09a7043ef14d8e86907eb089",
        351744,
    ),
    "conservatory01.fpx": (
        "40260d2636be3c34a214c61d74ee317b6805501af02a887ce41a6579b02e36b5",
        338432,
    ),
    "conservatory02.fpx": (
        "d69135b1820fbf899c5d19f7df611683e2d2377df63057288e983093b8978caf",
        338432,
    ),
    "conservatory03.fpx": (
        "2ca2a614f9c6b235bf73965e178208ac94fb595dc2bb4884e082b68040e2c971",
        313856,
    ),
    "conservatory04.fpx": (
        "8ebdc59b5d100ea8ea6c5a9cdaf987ede976ad160e810688dba8ae61aabc43f8",
        313856,
    ),
    "conservatory05.fpx": (
        "8de8c6fa4b7eaffbf661cbbd11149fcff8614bd32448022ac0cf30dfeb7d2325",
        403968,
    ),
    "conservatory06.fpx": (
        "d2ed8193703c6ccf4e8bf957cf8d483f4efebea3dd3c4c6876e1dca51bb31c51",
        403968,
    ),
    "conservatory07.fpx": (
        "3f7bac827243212406fb6d559c83968d74e77aa3c8de3f3b40bfb37d23409e19",
        362496,
    ),
    "conservatory08.fpx": (
        "a1b1f763fbc2bf23c0d8c4e926fccc099c35a4da02afc271060a863ae2efb5b2",
        362496,
    ),
    "dragonfly01.fpx": (
        "8ce87bd00e11ee2dc999af52179f6a324e3a4b745f6a1cf374611945f3c58837",
        196608,
    ),
    "dragonfly02.fpx": (
        "de8d78aa6a249b0abc8be421f02a83ac42bd445dcd0f4d8f5d0d6075c019d85a",
        196608,
    ),
    "feeder-crop.fpx": (
        "be629f0f44e38500dcaf8dd67799b6c697a9576a6f08c7447b0215ed017aa9a2",
        456192,
    ),
    "feeder01.fpx": (
        "a1165d79b2d5b38e78dbd287061a19eebb93492ea5aff367e3beb3b3aa965476",
        455168,
    ),
    "feeder02.fpx": (
        "f55c55adb6e321211a8bb80e3aa63cc3d3fbfb511403311aaf58ab33039de89d",
        455168,
    ),
    "foliage01.fpx": (
        "642218aa3e22d86b20673f3363ea671de7e711683ac6154b8a55e33c3e98b1c4",
        373248,
    ),
    "foliage02.fpx": (
        "7acb2d11fc966df87604364fd1d0245811ecfe42c1110cdd75f40b8c7e2487b2",
        373248,
    ),
    "foliage03.fpx": (
        "7aa1805685be78422a9aa420a3c7875c6c0e79af7e7173cf68fe2de140a203bc",
        349696,
    ),
    "foliage04.fpx": (
        "f1ffba56219900688f869c148bb2b69d0ad739f450e6297beb73dd1e45ff9a69",
        349696,
    ),
    "giraffe.fpx": (
        "29715c4670e074975b7014a2dc43a918f1e40fe0536da9f6bac4d615532250ad",
        324608,
    ),
    "harbor.fpx": (
        "b2a934b0051e464dd11358b07031dd316ddebcb3d150038822a64226814930d3",
        1629696,
    ),
    "mask.fpx": (
        "e9bc48c984d13f6cccc08db30878591c321d04b26c35ef934beabfccea52904f",
        1484800,
    ),
    "P0000016.FPX": (
        "346fde190a07e7cd6e5f569c9d56d0e71452f31e68c2485ed6fb3b83454b2dbc",
        241788,
    ),
    "pond-bed01.fpx": (
        "4040813733d36f73d3f333957e21d32545979be63e3394970a8fdb14c9cbcb63",
        425984,
    ),
    "pond-bed02.fpx": (
        "c75f1bfee2ac538976b146e0582febe632da013ef4d2479aaa84675dacf2108c",
        425984,
    ),
    "squirrel.fpx": (
        "0ce6651ae6940e0ad341dae6344b56dc3d5a80b7bb77a7de7cfa70d0bbbe06b1",
        1820672,
    ),
    "starfish.fpx": (
        "c6feb9c02c7e3cac40fcc841e2e471928e665e3a0ffe8bbe46353a1d50f3c5b1",
        1522688,
    ),
    "storm-fence.fpx": (
        "48d07125cbdfb93bb56ba10c51504354ec8704e107cdf6d1758aa3a23e6e8854",
        1589760,
    ),
    "train-platform.fpx": (
        "0aa28ef6d8da0df43361f002b62e9afd5d3810590cbc6d96073241227ade9674",
        244860,
    ),
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

    # The classifier's job: a camera-generated stem carries no human intent,
    # every other stem does. Exactly one fixture is camera-named. Derived
    # rather than pinned to a number, so adding a fixture does not force an
    # edit here -- but adding a *camera-named* one still moves the count and
    # is worth noticing.
    camera_named = {"P0000016.FPX"}
    assert manifest["counts"]["human_authored_names"] == len(EXPECTED) - len(camera_named)

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
