"""Tier-2: `convert` as a command, not as a pile of functions.

Everything in `test_batch.py` builds records by hand, which proves the engine's
pieces and nothing about the wiring. The features that make 0.5.0 what it is
live entirely in that wiring: whether resume actually skips, whether the flags
reach the writer, whether the log and the report get written at all.

The invariant that makes resume safe is asserted here and nowhere else: a file
is marked done **only** when it converted, and only while all of its outputs --
the images, the `.fpx` copy, and the sidecar -- are still on disk.

Runs over the committed fixtures, so it needs no personal corpus.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from fpx_converter import batch
from fpx_converter.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
pytestmark = pytest.mark.fixtures

#: Four is enough to prove wiring and keeps the suite quick; each conversion
#: decodes, writes two images, shells out to ExifTool and reads back.
SAMPLE = 4


@pytest.fixture
def converted(tmp_path: Path) -> tuple[Path, Path]:
    """A scanned manifest and a destination. Returns `(manifest, dest)`."""
    manifest = tmp_path / "m.json"
    assert main(["scan", "--source", str(FIXTURES), "--manifest", str(manifest)]) == 0
    return manifest, tmp_path / "out"


def _convert(manifest: Path, dest: Path, *extra: str) -> int:
    return main(
        [
            "convert",
            "--manifest", str(manifest),
            "--store", str(FIXTURES),
            "--dest", str(dest),
            "--limit", str(SAMPLE),
            *extra,
        ]
    )


#: The `.fpx` copy and the raw-property sidecar are opt-in. Tests that are
#: about those files ask for them explicitly, which also proves the flags do
#: what they say.
EXTRAS = ("--source-copy", "--sidecar")


def _report(dest: Path) -> dict:
    return json.loads((dest / batch.REPORT_FILENAME).read_text(encoding="utf-8"))


class TestArtifacts:
    def test_a_run_writes_the_log_the_state_and_the_report(
        self, converted: tuple[Path, Path]
    ) -> None:
        manifest, dest = converted
        assert _convert(manifest, dest) == 0
        for name in (batch.LOG_FILENAME, batch.STATE_FILENAME, batch.REPORT_FILENAME):
            assert (dest / name).is_file(), f"{name} was not written"

    def test_the_log_names_every_file_it_handled(
        self, converted: tuple[Path, Path]
    ) -> None:
        manifest, dest = converted
        _convert(manifest, dest)
        text = (dest / batch.LOG_FILENAME).read_text(encoding="utf-8")
        assert text.count("OK   [") == SAMPLE

    def test_a_partial_run_says_so_rather_than_reporting_success(
        self, converted: tuple[Path, Path]
    ) -> None:
        """`--limit 4` over 40 entries is not a finished archive.

        Before this, the report recorded the slice as the manifest size, so
        four converted files produced `unexplained_failures: 0` and looked
        exactly like a completed corpus.
        """
        manifest, dest = converted
        _convert(manifest, dest)
        report = _report(dest)
        assert report["counts"]["manifest_entries"] > SAMPLE
        assert report["counts"]["selected"] == SAMPLE
        assert report["complete"] is False

    def test_a_whole_run_is_marked_complete(self, converted: tuple[Path, Path]) -> None:
        manifest, dest = converted
        assert main(
            ["convert", "--manifest", str(manifest), "--store", str(FIXTURES),
             "--dest", str(dest)]
        ) == 0
        assert _report(dest)["complete"] is True


class TestResume:
    def test_a_second_run_converts_nothing_and_still_reports_everything(
        self, converted: tuple[Path, Path]
    ) -> None:
        manifest, dest = converted
        _convert(manifest, dest)
        _convert(manifest, dest)
        report = _report(dest)
        assert report["counts"]["converted"] == 0
        assert report["counts"]["resumed"] == SAMPLE
        assert report["counts"]["failed"] == 0

    def test_the_resumed_report_keeps_the_detail_of_the_original_run(
        self, converted: tuple[Path, Path]
    ) -> None:
        """A corpus converted across sessions must still yield one full report."""
        manifest, dest = converted
        _convert(manifest, dest)
        first = _report(dest)
        _convert(manifest, dest)
        second = _report(dest)
        assert second["date_sources"] == first["date_sources"]
        assert second["transform_status"] == first["transform_status"]

    def test_no_resume_does_the_work_again(self, converted: tuple[Path, Path]) -> None:
        manifest, dest = converted
        _convert(manifest, dest)
        _convert(manifest, dest, "--no-resume")
        assert _report(dest)["counts"]["converted"] == SAMPLE

    def test_a_deleted_image_comes_back(self, converted: tuple[Path, Path]) -> None:
        manifest, dest = converted
        _convert(manifest, dest)
        victim = next((dest / "archive").rglob("*.tif"))
        victim.unlink()
        _convert(manifest, dest)
        assert victim.is_file(), "a deleted output was not restored by the resume"

    def test_a_deleted_sidecar_comes_back_too(
        self, converted: tuple[Path, Path]
    ) -> None:
        """The finding that made this file necessary.

        Resume checked only the images, so the `.fpx` copy and the sidecar
        were invisible to it: deleting one and re-running restored the TIFF,
        left the sidecar missing, and printed `failed 0`. The source copy is
        not a derivative -- it is the thing being preserved.
        """
        manifest, dest = converted
        _convert(manifest, dest, *EXTRAS)
        victim = next((dest / "archive").rglob("*.fpx.json"))
        victim.unlink()
        _convert(manifest, dest, *EXTRAS)
        assert victim.is_file(), "a deleted sidecar was not restored by the resume"

    def test_a_deleted_fpx_copy_comes_back_too(
        self, converted: tuple[Path, Path]
    ) -> None:
        manifest, dest = converted
        _convert(manifest, dest, *EXTRAS)
        victim = next((dest / "archive").rglob("*.fpx"))
        victim.unlink()
        _convert(manifest, dest, *EXTRAS)
        assert victim.is_file(), "a deleted .fpx copy was not restored by the resume"

    def test_changing_the_output_shape_reconverts(
        self, converted: tuple[Path, Path]
    ) -> None:
        """Different specs mean different files, so it is not the same run."""
        manifest, dest = converted
        _convert(manifest, dest)
        _convert(manifest, dest, "--sharing-framing", "full")
        assert _report(dest)["counts"]["converted"] == SAMPLE


class TestOutputFlags:
    def test_the_defaults_are_a_full_frame_tiff_and_a_cropped_jpeg(
        self, converted: tuple[Path, Path]
    ) -> None:
        manifest, dest = converted
        _convert(manifest, dest)
        assert list((dest / "archive").rglob("*.tif"))
        assert list((dest / "sharing").rglob("*.jpg"))

    def test_by_default_a_photograph_produces_only_its_images(
        self, converted: tuple[Path, Path]
    ) -> None:
        """Asking for a photograph and getting four files is a surprise.

        The `.fpx` copy and the `.fpx.json` sidecar were written on every
        conversion. Both are still available, both are one flag away, and
        neither happens unless asked for.
        """
        manifest, dest = converted
        _convert(manifest, dest)
        assert not list(dest.rglob("*.fpx")), "a source copy was written unasked"
        assert not list(dest.rglob("*.fpx.json")), "a sidecar was written unasked"

    def test_no_sharing_leaves_only_the_lossless_full_frame(
        self, converted: tuple[Path, Path]
    ) -> None:
        """The owner's ask: the largest, non-cropped image."""
        manifest, dest = converted
        _convert(manifest, dest, "--no-sharing")
        assert list((dest / "archive").rglob("*.tif"))
        assert not (dest / "sharing").exists()

    def test_the_source_copy_and_sidecar_survive_no_archive(
        self, converted: tuple[Path, Path]
    ) -> None:
        """Asked for, they land even where no archive image was wanted.

        They used to be written on every run whatever else was asked for, on
        the reasoning that the source copy is not a derivative. It is opt-in
        now -- the source archive is read-only and still there, so this is a
        second copy of something that was never at risk -- but where somebody
        does ask, `--no-archive` must not take it away.
        """
        manifest, dest = converted
        _convert(manifest, dest, "--no-archive", *EXTRAS)
        assert not list((dest / "archive").rglob("*.tif"))
        assert list((dest / "archive").rglob("*.fpx.json"))

    def test_the_sharing_tree_can_be_a_tiff(
        self, converted: tuple[Path, Path]
    ) -> None:
        manifest, dest = converted
        _convert(manifest, dest, "--sharing-format", "tiff")
        assert list((dest / "sharing").rglob("*.tif"))
        assert not list((dest / "sharing").rglob("*.jpg"))

    def test_asking_for_no_output_at_all_is_refused(
        self, converted: tuple[Path, Path]
    ) -> None:
        manifest, dest = converted
        assert _convert(manifest, dest, "--no-archive", "--no-sharing") == 1
        assert not dest.exists() or not list(dest.rglob("*.tif"))

    def test_a_full_frame_sharing_output_is_the_declared_size(
        self, converted: tuple[Path, Path]
    ) -> None:
        manifest, dest = converted
        assert main(
            ["convert", "--manifest", str(manifest), "--store", str(FIXTURES),
             "--dest", str(dest), "--sharing-framing", "full"]
        ) == 0
        crop_fixture = next(
            p for p in (dest / "sharing").rglob("*feeder-crop.jpg")
        )
        with Image.open(crop_fixture) as image:
            assert image.size == (1152, 864), "the full-frame flag did not reach the writer"


def _unreachable_sources(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A manifest whose files cannot be found. Returns `(manifest, store, dest)`.

    Both routes have to be cut. `convert` looks in the ingested store and then
    falls back to the manifest's own `source_root`, so emptying only the store
    still finds every file -- a first draft of these tests "converted" three
    files it was supposed to fail on.
    """
    manifest = tmp_path / "m.json"
    main(["scan", "--source", str(FIXTURES), "--manifest", str(manifest)])
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["source_root"] = str(tmp_path / "vanished")
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    empty_store = tmp_path / "empty"
    empty_store.mkdir()
    return manifest, empty_store, tmp_path / "out"


class TestFailures:
    def test_a_missing_source_is_a_line_in_the_report_not_a_crash(
        self, tmp_path: Path
    ) -> None:
        """One bad file must not end a run over an irreplaceable archive."""
        manifest, store, dest = _unreachable_sources(tmp_path)
        code = main(
            ["convert", "--manifest", str(manifest), "--store", str(store),
             "--dest", str(dest), "--limit", "3"]
        )
        assert code == 2
        report = _report(dest)
        assert report["counts"]["failed"] == 3
        assert report["unexplained_failures"] == 3

    def test_a_failed_file_is_not_recorded_as_done(self, tmp_path: Path) -> None:
        """Otherwise the next run would skip it and call the archive finished."""
        manifest, store, dest = _unreachable_sources(tmp_path)
        main(
            ["convert", "--manifest", str(manifest), "--store", str(store),
             "--dest", str(dest), "--limit", "3"]
        )
        state = json.loads((dest / batch.STATE_FILENAME).read_text(encoding="utf-8"))
        assert state["done"] == {}


class TestPatternsAndResume:
    """A run that renames or refiles is not the same run.

    Resuming across such a change would skip nothing and move nothing: the
    files a previous run wrote are still there under their old names, the new
    run writes its own beside them, and the tree ends up half in each shape
    with nothing recording which is which. The output specs already invalidate
    a resume for the same reason.
    """

    def test_a_changed_filename_pattern_converts_again_rather_than_resuming(
        self, converted: tuple[Path, Path]
    ) -> None:
        manifest, dest = converted
        _convert(manifest, dest)
        assert _report(dest)["counts"]["converted"] == SAMPLE

        _convert(manifest, dest, "--name-template", "{day}-{month}-{year}_{name}")
        assert _report(dest)["counts"]["converted"] == SAMPLE
        assert _report(dest)["counts"]["resumed"] == 0

    def test_a_changed_folder_scheme_converts_again_rather_than_resuming(
        self, converted: tuple[Path, Path]
    ) -> None:
        manifest, dest = converted
        _convert(manifest, dest)
        _convert(manifest, dest, "--folder-scheme", "flat")
        assert _report(dest)["counts"]["converted"] == SAMPLE
        assert _report(dest)["counts"]["resumed"] == 0

    def test_two_custom_folder_patterns_are_two_different_runs(
        self, converted: tuple[Path, Path]
    ) -> None:
        """The scheme name alone is not enough -- both runs are 'custom'."""
        manifest, dest = converted
        _convert(manifest, dest, "--folder-scheme", "custom", "--folder-template", "{year}")
        _convert(manifest, dest, "--folder-scheme", "custom", "--folder-template", "{album}")
        assert _report(dest)["counts"]["converted"] == SAMPLE

    def test_the_same_patterns_twice_still_resumes(
        self, converted: tuple[Path, Path]
    ) -> None:
        """The guard must key on the patterns, not on their presence."""
        manifest, dest = converted
        pattern = ("--name-template", "{name}_{year}")
        _convert(manifest, dest, *pattern)
        _convert(manifest, dest, *pattern)
        assert _report(dest)["counts"]["converted"] == 0
        assert _report(dest)["counts"]["resumed"] == SAMPLE

    def test_a_pattern_that_would_lose_the_filenames_stops_before_writing(
        self, converted: tuple[Path, Path], capsys
    ) -> None:
        manifest, dest = converted
        assert _convert(manifest, dest, "--name-template", "{year}-{month}") == 1
        assert "{name}" in capsys.readouterr().err
        assert not list(dest.rglob("*.tif")), "files were written despite the refusal"

    def test_a_folder_pattern_that_walks_upwards_stops_before_writing(
        self, converted: tuple[Path, Path], capsys
    ) -> None:
        """It could put converted images anywhere on the disk, the read-only
        source archive included."""
        manifest, dest = converted
        code = _convert(
            manifest, dest, "--folder-scheme", "custom", "--folder-template", "../{album}"
        )
        assert code == 1
        assert ".." in capsys.readouterr().err
        assert not list(dest.rglob("*.tif"))
