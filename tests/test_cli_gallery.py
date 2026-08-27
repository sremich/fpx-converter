"""Tier-2: `gallery` as a command, not as a pile of functions.

`test_gallery.py` proves the page builder. It says nothing about the wiring,
and the wiring is where the defect was: `cmd_gallery` computed its default
output path from the repo root and ignored `--dest` entirely, so pointing the
command at a specific run wrote the page to a fixed `report/` beside the
source tree. Two runs overwrote each other's page, and the page you opened
could describe a run you were not looking at -- the one thing a review
artifact must never do.

That survived because every test built `GalleryItem`s by hand. These drive
the real command over the committed fixtures instead.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpx_converter import batch, gallery
from fpx_converter.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
pytestmark = pytest.mark.fixtures

#: Enough to produce a report with real albums in it; each one is a full
#: decode plus two writes plus an ExifTool round trip.
SAMPLE = 3


@pytest.fixture
def finished_run(tmp_path: Path) -> tuple[Path, Path]:
    """A converted destination and its manifest. Returns `(manifest, dest)`."""
    manifest = tmp_path / "m.json"
    assert main(["scan", "--source", str(FIXTURES), "--manifest", str(manifest)]) == 0
    dest = tmp_path / "out"
    assert (
        main(
            [
                "convert",
                "--manifest", str(manifest),
                "--store", str(FIXTURES),
                "--dest", str(dest),
                "--limit", str(SAMPLE),
            ]
        )
        == 0
    )
    return manifest, dest


def _gallery(manifest: Path, dest: Path, *extra: str) -> int:
    return main(
        [
            "gallery",
            "--manifest", str(manifest),
            "--store", str(FIXTURES),
            "--dest", str(dest),
            *extra,
        ]
    )


class TestWhereThePageLands:
    def test_the_page_lands_inside_the_destination_it_describes(
        self, finished_run: tuple[Path, Path]
    ) -> None:
        """The defect this file was written for."""
        manifest, dest = finished_run
        assert _gallery(manifest, dest) == 0
        assert (dest / "report" / gallery.REPORT_FILENAME).is_file(), (
            "the page was not written beside the run it describes"
        )

    def test_two_runs_do_not_overwrite_each_other(self, tmp_path: Path) -> None:
        """Separate destinations must yield separate pages.

        With the default path pinned to the repo root, the second run's page
        replaced the first's and nothing said so.
        """
        manifest = tmp_path / "m.json"
        main(["scan", "--source", str(FIXTURES), "--manifest", str(manifest)])
        pages = []
        for name in ("run-a", "run-b"):
            dest = tmp_path / name
            main(
                ["convert", "--manifest", str(manifest), "--store", str(FIXTURES),
                 "--dest", str(dest), "--limit", str(SAMPLE)]
            )
            assert _gallery(manifest, dest) == 0
            pages.append(dest / "report" / gallery.REPORT_FILENAME)
        assert all(p.is_file() for p in pages)
        assert pages[0] != pages[1]

    def test_an_explicit_out_still_wins(self, finished_run: tuple[Path, Path]) -> None:
        manifest, dest = finished_run
        chosen = dest.parent / "elsewhere" / "page.html"
        assert _gallery(manifest, dest, "--out", str(chosen)) == 0
        assert chosen.is_file()


class TestThePageItself:
    def test_it_is_self_contained(self, finished_run: tuple[Path, Path]) -> None:
        """No server, no build step, no external asset.

        It has to open by double-clicking it years from now on a machine with
        none of this installed, so nothing may be fetched over the network.
        """
        manifest, dest = finished_run
        _gallery(manifest, dest)
        html = (dest / "report" / gallery.REPORT_FILENAME).read_text(encoding="utf-8")
        for forbidden in ("http://", "https://", "src=\"/", "<link rel=\"stylesheet\""):
            assert forbidden not in html, f"the page reaches outside itself: {forbidden}"
        assert "data:image/jpeg;base64," in html, "no inlined thumbnail"

    def test_every_converted_file_appears(self, finished_run: tuple[Path, Path]) -> None:
        manifest, dest = finished_run
        _gallery(manifest, dest)
        report = json.loads((dest / batch.REPORT_FILENAME).read_text(encoding="utf-8"))
        html = (dest / "report" / gallery.REPORT_FILENAME).read_text(encoding="utf-8")
        converted = report["counts"]["converted"]
        assert html.count("data-album=") >= converted


class TestRefusals:
    def test_a_destination_with_no_run_is_refused(self, tmp_path: Path) -> None:
        """Rather than writing an empty page that looks like a clean archive."""
        empty = tmp_path / "nothing"
        empty.mkdir()
        assert main(["gallery", "--dest", str(empty)]) == 1
        assert not (empty / "report").exists()
