"""Tier-1: `--stop-file` is a path this program deletes.

Every other path `convert` writes to goes through `config.ensure_outside_source`.
This one did not, and both its uses are `unlink`. Passing a path inside the
source archive destroyed that photograph, and the run then reported success --
`scan`'s `verify_unchanged` belongs to an earlier command and never sees it.

That is the one rule in this project whose violation cannot be undone, so the
guard gets a test of its own rather than riding along with the others.

Also covers the two ways removing the marker can raise on Windows, both on the
code path whose entire purpose is making sure the audit report still lands.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpx_converter import config
from fpx_converter.cli import _remove_stop_file, main


def _manifest_naming(source_root: Path, path: Path) -> Path:
    """A manifest with no entries, pointing at `source_root`.

    The refusal has to happen before any conversion, so an empty manifest is
    enough -- and it means the test cannot accidentally depend on a fixture.
    """
    path.write_text(
        json.dumps({"source_root": str(source_root), "entries": [], "counts": {}}),
        encoding="utf-8",
    )
    return path


class TestTheGuard:
    def test_a_stop_file_inside_the_source_root_is_refused(
        self, tmp_path: Path
    ) -> None:
        """The finding. Before the guard, this deleted the file."""
        source = tmp_path / "archive"
        source.mkdir()
        decoy = source / "irreplaceable.fpx"
        decoy.write_bytes(b"the only copy")

        manifest = _manifest_naming(source, tmp_path / "m.json")
        code = main(
            [
                "convert",
                "--manifest", str(manifest),
                "--dest", str(tmp_path / "out"),
                "--stop-file", str(decoy),
            ]
        )

        assert code != 0, "a stop file inside the archive was accepted"
        assert decoy.is_file(), "a source file was deleted by --stop-file"
        assert decoy.read_bytes() == b"the only copy"

    def test_a_stop_file_in_a_nested_source_directory_is_refused_too(
        self, tmp_path: Path
    ) -> None:
        """Nested, because `is_relative_to` is the whole check."""
        source = tmp_path / "archive"
        (source / "2001" / "some album").mkdir(parents=True)
        decoy = source / "2001" / "some album" / "photo.fpx"
        decoy.write_bytes(b"pixels")

        manifest = _manifest_naming(source, tmp_path / "m.json")
        assert (
            main(
                ["convert", "--manifest", str(manifest),
                 "--dest", str(tmp_path / "out"), "--stop-file", str(decoy)]
            )
            != 0
        )
        assert decoy.is_file()

    def test_a_stop_file_outside_the_source_root_is_allowed(
        self, tmp_path: Path
    ) -> None:
        """The guard must not refuse the ordinary case."""
        source = tmp_path / "archive"
        source.mkdir()
        manifest = _manifest_naming(source, tmp_path / "m.json")
        assert (
            main(
                ["convert", "--manifest", str(manifest),
                 "--dest", str(tmp_path / "out"),
                 "--stop-file", str(tmp_path / "out" / "stop")]
            )
            == 0
        )

    def test_the_refusal_is_the_shared_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """It must be a *call* to the project's guard, not a second copy.

        Two implementations of one invariant is how they drift apart, and this
        is the invariant that has no second chance. The first version of this
        test called `ensure_outside_source` itself and asserted it raised --
        which proves the guard works and says nothing at all about whether
        `convert` uses it. It would have passed against a hand-rolled copy in
        `cli.py`, which is precisely what it claims to rule out.

        A call-through spy instead: the real function still runs, and the test
        can see that it was the one asked.
        """
        source = tmp_path / "archive"
        source.mkdir()
        marker = source / "stop"

        calls: list[tuple[Path, Path, str]] = []
        real = config.ensure_outside_source

        def spy(target: Path, source_root: Path, what: str) -> Path:
            calls.append((Path(target), Path(source_root), what))
            return real(target, source_root, what)

        monkeypatch.setattr(config, "ensure_outside_source", spy)
        manifest = _manifest_naming(source, tmp_path / "m.json")
        main(
            ["convert", "--manifest", str(manifest),
             "--dest", str(tmp_path / "out"), "--stop-file", str(marker)]
        )

        assert any(target == marker for target, _root, _what in calls), (
            "the stop file was never passed to config.ensure_outside_source"
        )


class TestRemovingTheMarker:
    """Neither way this can fail may end the run.

    `unlink` raises `PermissionError` for a file something has open for a
    moment -- an indexer, a virus scanner -- and for a path that is a
    directory. Both escaped from the one code path whose purpose is making
    sure `audit_report.json` is still written.
    """

    def test_a_missing_marker_is_not_an_error(self, tmp_path: Path) -> None:
        _remove_stop_file(tmp_path / "never-existed")

    def test_a_directory_where_the_marker_should_be_is_not_an_error(
        self, tmp_path: Path
    ) -> None:
        awkward = tmp_path / "stop"
        awkward.mkdir()
        _remove_stop_file(awkward)
        assert awkward.is_dir(), "a directory was removed by the stop-file cleanup"

    def test_an_ordinary_marker_is_removed(self, tmp_path: Path) -> None:
        marker = tmp_path / "stop"
        marker.write_text("", encoding="utf-8")
        _remove_stop_file(marker)
        assert not marker.exists()
