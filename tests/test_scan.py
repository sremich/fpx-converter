"""Tier-1: the read-only proof, tested through its failure modes.

The happy path of `verify_unchanged` would pass against a stub that inspects
nothing. Every test here makes a change to a tree and asserts it is caught —
those are the only outcomes that matter, because the check exists to notice
that we damaged an irreplaceable archive.
"""

from __future__ import annotations

import os
import random
from pathlib import Path

import pytest

from fpx_converter import scan
from fpx_converter.config import SourceWriteRefused, ensure_outside_source


def make_tree(root: Path) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    (root / "album").mkdir()
    files = {
        "a": root / "a.fpx",
        "b": root / "album" / "b.FPX",
        "other": root / "album" / "notes.txt",
    }
    files["a"].write_bytes(b"aaaa")
    files["b"].write_bytes(b"bbbb")
    files["other"].write_bytes(b"not an fpx")
    return files


def snapshot_and_hashes(root: Path) -> tuple[dict, dict]:
    snapshot = scan.tree_snapshot(root)
    hashes = {str(p): scan.sha256_file(p) for p in scan.iter_fpx_files(root)}
    return snapshot, hashes


class TestTreeSnapshot:
    def test_covers_every_file_not_just_fpx(self, tmp_path: Path) -> None:
        """An added .txt is still a write into a read-only tree."""
        files = make_tree(tmp_path / "src")
        snapshot = scan.tree_snapshot(tmp_path / "src")
        assert str(files["other"]) in snapshot
        assert len(snapshot) == 3

    def test_directories_are_not_recorded(self, tmp_path: Path) -> None:
        make_tree(tmp_path / "src")
        snapshot = scan.tree_snapshot(tmp_path / "src")
        assert not any(Path(p).is_dir() for p in snapshot)


class TestVerifyUnchanged:
    def test_clean_tree_passes(self, tmp_path: Path) -> None:
        root = tmp_path / "src"
        make_tree(root)
        before, hashes = snapshot_and_hashes(root)
        report = scan.verify_unchanged(before, root, hashes, sample_size=10)
        assert report.ok
        assert report.resampled == 2

    def test_detects_a_modified_file(self, tmp_path: Path) -> None:
        root = tmp_path / "src"
        files = make_tree(root)
        before, hashes = snapshot_and_hashes(root)
        files["a"].write_bytes(b"tampered")
        report = scan.verify_unchanged(before, root, hashes, sample_size=0)
        assert not report.ok
        assert report.modified == [str(files["a"])]

    def test_detects_a_vanished_file(self, tmp_path: Path) -> None:
        root = tmp_path / "src"
        files = make_tree(root)
        before, hashes = snapshot_and_hashes(root)
        files["b"].unlink()
        report = scan.verify_unchanged(before, root, hashes, sample_size=0)
        assert not report.ok
        assert report.vanished == [str(files["b"])]

    def test_detects_an_added_file(self, tmp_path: Path) -> None:
        """Creating a file is a write. A check that only looks at files it
        already knew about cannot see one."""
        root = tmp_path / "src"
        make_tree(root)
        before, hashes = snapshot_and_hashes(root)
        intruder = root / "album" / "intruder.fpx"
        intruder.write_bytes(b"new")
        report = scan.verify_unchanged(before, root, hashes, sample_size=0)
        assert not report.ok
        assert report.added == [str(intruder)]

    def test_detects_a_change_that_preserved_size_and_mtime(self, tmp_path: Path) -> None:
        """The whole reason the re-hash exists.

        Same length, same mtime restored — only hashing the content catches
        it, and only if that file happens to be in the sample. Sampling
        everything here makes the assertion deterministic.
        """
        root = tmp_path / "src"
        files = make_tree(root)
        before, hashes = snapshot_and_hashes(root)

        original = files["a"].stat()
        files["a"].write_bytes(b"zzzz")  # same 4 bytes as b"aaaa"
        os.utime(files["a"], ns=(original.st_atime_ns, original.st_mtime_ns))

        assert scan.tree_snapshot(root)[str(files["a"])] == before[str(files["a"])], (
            "size and mtime should be indistinguishable — otherwise this test proves nothing"
        )
        report = scan.verify_unchanged(before, root, hashes, sample_size=99)
        assert not report.ok
        assert report.rehash_mismatches == [str(files["a"])]

    def test_a_stub_would_not_pass_these(self, tmp_path: Path) -> None:
        """Guard against the check degrading into a no-op that reports ok."""
        root = tmp_path / "src"
        files = make_tree(root)
        before, hashes = snapshot_and_hashes(root)
        files["a"].write_bytes(b"tampered")
        report = scan.verify_unchanged(before, root, hashes, sample_size=0)
        assert report.ok is False

    def test_sampling_is_not_pinned_to_the_same_files_every_run(self, tmp_path: Path) -> None:
        """A fixed seed over a sorted list re-checks the same files forever,
        leaving the rest of the archive permanently unsampled while looking
        exactly like sampling."""
        root = tmp_path / "src"
        root.mkdir()
        for i in range(60):
            (root / f"f{i:03d}.fpx").write_bytes(bytes([i]))
        before, hashes = snapshot_and_hashes(root)

        draws = set()
        for _ in range(12):
            report = scan.verify_unchanged(before, root, hashes, sample_size=5)
            assert report.ok
            draws.add(tuple(report.sampled))
        assert len(draws) > 1, "successive runs re-hashed an identical file set"

    def test_a_supplied_rng_still_pins_the_sample(self, tmp_path: Path) -> None:
        """Tests need determinism; production must not have it."""
        root = tmp_path / "src"
        root.mkdir()
        for i in range(20):
            (root / f"f{i:02d}.fpx").write_bytes(bytes([i]))
        before, hashes = snapshot_and_hashes(root)
        first = scan.verify_unchanged(before, root, hashes, 4, rng=random.Random(7)).sampled
        second = scan.verify_unchanged(before, root, hashes, 4, rng=random.Random(7)).sampled
        assert first == second

    def test_negative_sample_size_is_rejected(self, tmp_path: Path) -> None:
        root = tmp_path / "src"
        make_tree(root)
        before, hashes = snapshot_and_hashes(root)
        with pytest.raises(ValueError, match="negative"):
            scan.verify_unchanged(before, root, hashes, sample_size=-1)

    def test_zero_sample_size_rehashes_nothing(self, tmp_path: Path) -> None:
        root = tmp_path / "src"
        make_tree(root)
        before, hashes = snapshot_and_hashes(root)
        report = scan.verify_unchanged(before, root, hashes, sample_size=0)
        assert report.resampled == 0
        assert report.ok

    def test_report_serialises_for_the_manifest(self, tmp_path: Path) -> None:
        root = tmp_path / "src"
        make_tree(root)
        before, hashes = snapshot_and_hashes(root)
        as_dict = scan.verify_unchanged(before, root, hashes, sample_size=1).as_dict()
        assert as_dict["ok"] is True
        assert set(as_dict) == {
            "ok",
            "files_checked",
            "files_rehashed",
            "modified",
            "vanished",
            "added",
            "rehash_mismatches",
            "sampled",
        }


class TestOleInventory:
    def test_reports_a_non_ole_file_without_raising(self, tmp_path: Path) -> None:
        victim = tmp_path / "fake.fpx"
        victim.write_bytes(b"this is not a compound document")
        result = scan.ole_inventory(victim)
        assert result["is_ole"] is False
        assert result["streams"] == []
        assert "OLE2" in str(result["error"])

    def test_reports_a_truncated_ole_file_without_raising(self, tmp_path: Path) -> None:
        """A bad file must be recorded, never allowed to stop a batch."""
        source = Path(__file__).parent / "fixtures" / "Clouds01.fpx"
        victim = tmp_path / "truncated.fpx"
        victim.write_bytes(source.read_bytes()[:2048])
        result = scan.ole_inventory(victim)
        assert result["streams"] == []
        assert result["error"] is not None
        assert result["is_ole"] in (False, None)

    def test_unreadable_path_is_reported_not_raised(self, tmp_path: Path) -> None:
        result = scan.ole_inventory(tmp_path / "does-not-exist.fpx")
        assert result["error"] is not None
        assert result["streams"] == []


class TestEnsureOutsideSource:
    def test_rejects_a_target_inside_the_source_root(self, tmp_path: Path) -> None:
        source = tmp_path / "archive"
        source.mkdir()
        with pytest.raises(SourceWriteRefused, match="read-only source archive"):
            ensure_outside_source(source / "store", source, "ingest destination")

    def test_rejects_the_source_root_itself(self, tmp_path: Path) -> None:
        source = tmp_path / "archive"
        source.mkdir()
        with pytest.raises(SourceWriteRefused):
            ensure_outside_source(source, source, "ingest destination")

    def test_rejects_a_nested_target(self, tmp_path: Path) -> None:
        source = tmp_path / "archive"
        (source / "albums" / "one").mkdir(parents=True)
        with pytest.raises(SourceWriteRefused):
            ensure_outside_source(source / "albums" / "one" / "x", source, "manifest path")

    def test_allows_a_sibling_directory(self, tmp_path: Path) -> None:
        source = tmp_path / "archive"
        source.mkdir()
        target = tmp_path / "store"
        assert ensure_outside_source(target, source, "ingest destination") == target.resolve()

    def test_allows_a_similarly_named_sibling(self, tmp_path: Path) -> None:
        """`archive-copy` is not inside `archive`; a string prefix test
        would wrongly reject it."""
        source = tmp_path / "archive"
        source.mkdir()
        target = tmp_path / "archive-copy"
        assert ensure_outside_source(target, source, "ingest destination") == target.resolve()
