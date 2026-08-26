"""Tier-1: manifest construction from synthetic scan results."""

from __future__ import annotations

import hashlib
from pathlib import Path

from fpx_converter import manifest as manifest_mod
from fpx_converter.scan import ScannedFile

ROOT = Path("C:/fake-source")


def sha_of(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def scanned(
    relpath: str, *, sha: str, size: int = 100, streams: list[str] | None = None
) -> ScannedFile:
    return ScannedFile(
        path=ROOT / relpath,
        relpath=relpath,
        name=relpath.rpartition("/")[2],
        size=size,
        mtime="2002-07-04T12:00:00+00:00",
        sha256=sha,
        streams=streams if streams is not None else ["\x05SummaryInformation"],
        is_ole=True,
        ole_error=None,
    )


def build(files: list[ScannedFile]) -> dict:
    return manifest_mod.build(files, source_root=ROOT, tool_version="0.1.0", generated_at="T")


class TestGrouping:
    def test_identical_files_collapse_to_one_entry(self) -> None:
        sha = sha_of("same")
        result = build(
            [
                scanned("TreeA/Flat/DCP00123.fpx", sha=sha),
                scanned("TreeB/Albums/Holiday/party hats.fpx", sha=sha),
            ]
        )
        assert result["counts"]["files_seen"] == 2
        assert result["counts"]["distinct_sha256"] == 1
        entry = result["entries"][0]
        assert entry["duplicate_count"] == 2

    def test_every_source_path_is_recorded(self) -> None:
        """Collapsing duplicates must not lose where a photo lived."""
        sha = sha_of("same")
        result = build(
            [
                scanned("TreeA/Flat/DCP00123.fpx", sha=sha),
                scanned("TreeB/Albums/Holiday/party hats.fpx", sha=sha),
                scanned("TreeB/Albums/Winter/party hats.fpx", sha=sha),
            ]
        )
        entry = result["entries"][0]
        assert [s["relpath"] for s in entry["sources"]] == [
            "TreeA/Flat/DCP00123.fpx",
            "TreeB/Albums/Holiday/party hats.fpx",
            "TreeB/Albums/Winter/party hats.fpx",
        ]
        assert entry["albums"] == ["Flat", "Holiday", "Winter"]
        assert entry["trees"] == ["TreeA", "TreeB"]

    def test_human_name_is_the_one_kept(self) -> None:
        sha = sha_of("same")
        result = build(
            [
                scanned("TreeA/Flat/DCP00123.fpx", sha=sha),
                scanned("TreeB/Albums/Holiday/party hats.fpx", sha=sha),
            ]
        )
        entry = result["entries"][0]
        assert entry["preferred_name"] == "party hats.fpx"
        assert entry["preferred_relpath"] == "TreeB/Albums/Holiday/party hats.fpx"
        assert entry["store_name"] == "party hats.fpx"
        assert entry["preferred_name_is_human_authored"] is True

    def test_different_content_sharing_a_name_stays_separate(self) -> None:
        a, b = sha_of("a"), sha_of("b")
        result = build(
            [
                scanned("TreeB/Albums/One/DCP00280.fpx", sha=a),
                scanned("TreeB/Albums/Two/DCP00280.fpx", sha=b),
            ]
        )
        assert result["counts"]["distinct_sha256"] == 2
        store_names = {e["store_name"] for e in result["entries"]}
        assert len(store_names) == 2


class TestCounts:
    def test_byte_totals_distinguish_seen_from_distinct(self) -> None:
        sha = sha_of("same")
        result = build(
            [
                scanned("a/DCP00001.fpx", sha=sha, size=500),
                scanned("b/DCP00001.fpx", sha=sha, size=500),
                scanned("c/other.fpx", sha=sha_of("other"), size=300),
            ]
        )
        assert result["counts"]["bytes_seen"] == 1300
        assert result["counts"]["bytes_distinct"] == 800

    def test_human_authored_names_are_counted(self) -> None:
        result = build(
            [
                scanned("a/DCP00001.fpx", sha=sha_of("1")),
                scanned("b/the cat.fpx", sha=sha_of("2")),
                scanned("c/the dog.fpx", sha=sha_of("3")),
            ]
        )
        assert result["counts"]["human_authored_names"] == 2

    def test_non_ole_files_are_counted(self) -> None:
        broken = scanned("a/broken.fpx", sha=sha_of("broken"))
        broken.is_ole = False
        broken.ole_error = "not an OLE2 compound document"
        result = build([broken, scanned("b/fine.fpx", sha=sha_of("fine"))])
        assert result["counts"]["not_ole"] == 1


def test_entries_are_ordered_by_hash_so_reruns_diff_cleanly() -> None:
    files = [scanned(f"a/f{i}.fpx", sha=sha_of(str(i))) for i in range(5)]
    forward = build(files)
    backward = build(list(reversed(files)))
    hashes = [e["sha256"] for e in forward["entries"]]
    assert hashes == sorted(hashes)
    assert forward == backward


def test_round_trip_through_disk(tmp_path: Path) -> None:
    result = build([scanned("a/x.fpx", sha=sha_of("x"))])
    path = tmp_path / "manifest.json"
    manifest_mod.write(path, result)
    assert manifest_mod.load(path) == result


def test_control_characters_in_stream_names_survive(tmp_path: Path) -> None:
    """FlashPix property-set streams start with \\x05; JSON must not mangle it."""
    result = build([scanned("a/x.fpx", sha=sha_of("x"), streams=["\x05Image Contents"])])
    path = tmp_path / "manifest.json"
    manifest_mod.write(path, result)
    assert manifest_mod.load(path)["entries"][0]["streams"] == ["\x05Image Contents"]
