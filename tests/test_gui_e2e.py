"""Tier-2: a real conversion, driven the way the window drives one.

Not `cli.main` called in-process -- the actual child process, launched by
`fpx_gui.runner` from argv that `fpx_gui.options` built, with its output read
back line by line. Everything between the buttons and the pixels is in the
path: the invocation choice, the flags, the streamed log, the progress
parser, and the audit report the summary is rendered from.

Runs over the committed person-free fixtures, needs no personal corpus, and
needs no Qt -- `runner` is deliberately Qt-free, so this runs in CI on an
install of `requirements-dev.txt` alone.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from fpx_converter import batch
from fpx_gui import options as options_mod
from fpx_gui import progress, runner, summary
from fpx_gui.options import ConvertOptions

FIXTURES = Path(__file__).parent / "fixtures"
pytestmark = pytest.mark.fixtures

#: Every fixture would be slow and prove nothing extra; the whole point of
#: this file is the wiring, and four files exercise all of it.
SAMPLE = 4


@pytest.fixture(scope="module")
def run_result(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """One conversion, driven end to end. Shared: it is the expensive part."""
    dest = tmp_path_factory.mktemp("gui-out")
    chosen = ConvertOptions(source=FIXTURES, dest=dest)
    options_mod.validate(chosen)
    before = _snapshot(FIXTURES)

    lines: list[str] = []
    codes: list[int] = []
    for _label, args in options_mod.convert_pipeline(chosen):
        # `--limit` is not one of the window's controls; it is added here so
        # the suite stays quick. The result is a deliberately partial run,
        # which is also the case the summary most needs to get right.
        if args[0] == "convert":
            args = [*args, "--limit", str(SAMPLE)]
        codes.append(runner.run_cli(args, on_line=lines.append))
    return {
        "dest": dest,
        "lines": lines,
        "codes": codes,
        "options": chosen,
        "source_before": before,
    }


def _snapshot(root: Path) -> dict[str, str]:
    """Every file under `root`, by relative path and content hash."""
    import hashlib

    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            snapshot[str(path.relative_to(root))] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return snapshot


class TestItActuallyConverts:
    def test_both_output_trees_were_written(self, run_result: dict) -> None:
        dest: Path = run_result["dest"]
        assert list((dest / "archive").rglob("*.tif")), "no archival TIFF was written"
        assert list((dest / "sharing").rglob("*.jpg")), "no shareable JPEG was written"

    def test_the_run_left_its_report_and_its_log(self, run_result: dict) -> None:
        dest: Path = run_result["dest"]
        for name in (batch.REPORT_FILENAME, batch.LOG_FILENAME, batch.STATE_FILENAME):
            assert (dest / name).is_file(), f"{name} was not written"

    def test_every_step_succeeded(self, run_result: dict) -> None:
        assert run_result["codes"] == [0, 0]

    def test_the_manifest_landed_in_the_destination(self, run_result: dict) -> None:
        """Never beside the source. The source folder is only ever read."""
        chosen: ConvertOptions = run_result["options"]
        assert chosen.manifest.is_file()
        assert not list(FIXTURES.glob("manifest.json"))


class TestTheOutputReachesTheWindow:
    def test_the_child_s_lines_came_back(self, run_result: dict) -> None:
        assert run_result["lines"], "nothing was streamed back from the child process"

    def test_the_per_file_lines_are_on_the_stream_not_only_in_the_log(
        self, run_result: dict
    ) -> None:
        """What `--progress` is for. Without it the window sees a long silence."""
        file_lines = [ln for ln in run_result["lines"] if "OK   [" in ln]
        assert len(file_lines) == SAMPLE

    def test_the_streamed_lines_match_the_log_file(self, run_result: dict) -> None:
        dest: Path = run_result["dest"]
        logged = (dest / batch.LOG_FILENAME).read_text(encoding="utf-8").splitlines()
        streamed = set(run_result["lines"])
        assert set(logged) <= streamed, "the log file holds lines the stream never saw"

    def test_the_progress_parser_tracked_the_real_run_to_the_end(
        self, run_result: dict
    ) -> None:
        tracker = progress.ProgressTracker()
        for line in run_result["lines"]:
            tracker.feed(line)
        assert tracker.total == SAMPLE
        assert tracker.done == SAMPLE
        assert tracker.fraction == 1.0
        assert tracker.failed == 0


class TestTheSummaryTheWindowWouldShow:
    def test_it_is_read_from_the_report_that_was_written(self, run_result: dict) -> None:
        result = summary.load_summary(run_result["dest"] / batch.REPORT_FILENAME)
        assert result.converted == SAMPLE
        assert result.failed == 0

    def test_a_limited_run_is_reported_as_partial_and_not_as_finished(
        self, run_result: dict
    ) -> None:
        """The real thing, not a hand-built report: four of forty is not done."""
        result = summary.load_summary(run_result["dest"] / batch.REPORT_FILENAME)
        assert result.manifest_entries > SAMPLE
        assert not result.complete
        assert not result.finished_cleanly
        assert result.severity == summary.ERROR


class TestTheReadOnlyRuleEndToEnd:
    def test_the_source_folder_is_byte_identical_afterwards(
        self, run_result: dict
    ) -> None:
        """The rule, checked against the bytes rather than asserted.

        Every file hashed before the run and again after it: nothing added,
        nothing removed, nothing changed. A GUI is a new way to point this
        tool at a folder, and it is the one rule whose violation cannot be
        undone.
        """
        before: dict[str, str] = run_result["source_before"]
        assert before, "the source snapshot was empty; this check would pass vacuously"
        assert _snapshot(FIXTURES) == before

    def test_a_destination_inside_the_fixtures_never_launches_anything(self) -> None:
        """Refused before a child process exists, by the CLI's own guard."""
        from fpx_converter import config

        with pytest.raises(config.SourceWriteRefused):
            options_mod.validate(
                ConvertOptions(source=FIXTURES, dest=FIXTURES / "converted")
            )
        assert not (FIXTURES / "converted").exists()


class TestCancellingARealRun:
    """The guarantee: Cancel stops it **and** the audit report still lands.

    Anything else and a cancelled run is indistinguishable from one that was
    killed, which is indistinguishable from one that finished badly. This
    starts a real conversion, cancels it partway, and insists on the report.
    """

    def test_a_cancelled_run_still_writes_its_audit_report(
        self, tmp_path: Path
    ) -> None:
        import time

        dest = tmp_path / "cancelled"
        chosen = ConvertOptions(source=FIXTURES, dest=dest)
        options_mod.validate(chosen)
        assert runner.run_cli(options_mod.scan_args(chosen)) == 0

        lines: list[str] = []
        process = runner.CliProcess(
            options_mod.convert_args(chosen), on_line=lines.append
        )
        process.start()

        # Let a couple of photos through, so the cancel lands mid-run rather
        # than before anything has happened.
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if sum(1 for line in lines if "OK   [" in line) >= 2:
                break
            time.sleep(0.1)

        status = process.cancel(grace=60.0, stop_file=chosen.stop_file)
        process.wait(timeout=30)

        assert status == runner.CANCELLED, (
            "the run had to be killed; a killed run leaves no audit report"
        )
        result = summary.load_summary(dest / batch.REPORT_FILENAME)
        assert result.interrupted is True
        assert result.complete is False
        assert result.converted > 0, "it stopped before converting anything"
        assert result.converted < 40, "it was not actually cancelled"
        assert result.severity == summary.ERROR

    def test_the_stop_marker_does_not_survive_to_poison_the_next_run(
        self, tmp_path: Path
    ) -> None:
        """A leftover marker must not cancel the following run.

        This used to be arranged by deleting the marker at startup, and
        this test asserted the deletion. That mechanism was wrong twice
        over: the delete happened only after the manifest load and the
        stem assignment, so a Cancel arriving during that window was
        swallowed by the very run it was meant to stop; and a marker that
        could not be deleted -- a directory, an antivirus lock -- stopped
        every future run into that destination, for ever and silently.

        A marker is now honoured only if it is newer than the run, so a
        stale one is ignored rather than removed. The property this test
        cares about is unchanged and is what it now asserts. Whether the
        marker is still on disk afterwards is not a fault either way, so
        it is no longer asserted.
        """
        dest = tmp_path / "stale"
        dest.mkdir(parents=True)
        chosen = ConvertOptions(source=FIXTURES, dest=dest)
        chosen.stop_file.write_text("stop\n", encoding="utf-8")
        # Unambiguously older than the run that is about to start.
        os.utime(chosen.stop_file, (0, 0))

        assert runner.run_cli(options_mod.scan_args(chosen)) == 0
        args = [*options_mod.convert_args(chosen), "--limit", "2"]
        assert runner.run_cli(args) == 0

        result = summary.load_summary(dest / batch.REPORT_FILENAME)
        assert result.interrupted is False
        assert result.converted == 2

    def test_an_undeletable_marker_does_not_wedge_the_destination(
        self, tmp_path: Path
    ) -> None:
        """The second half of the same finding.

        A marker that cannot be removed -- here a directory, which
        `unlink` refuses on Windows -- used to stop every run into that
        destination for ever, while the window cheerfully advised pressing
        Convert again.
        """
        dest = tmp_path / "wedged"
        dest.mkdir(parents=True)
        chosen = ConvertOptions(source=FIXTURES, dest=dest)
        chosen.stop_file.mkdir(parents=True)
        os.utime(chosen.stop_file, (0, 0))

        assert runner.run_cli(options_mod.scan_args(chosen)) == 0
        args = [*options_mod.convert_args(chosen), "--limit", "2"]
        assert runner.run_cli(args) == 0

        result = summary.load_summary(dest / batch.REPORT_FILENAME)
        assert result.interrupted is False, "an undeletable marker wedged the run"
        assert result.converted == 2


class TestTheCliIsReachedTheWayThePackagedAppWouldReachIt:
    def test_the_unfrozen_invocation_runs_the_real_cli(self, tmp_path: Path) -> None:
        lines: list[str] = []
        code = runner.run_cli(["--version"], on_line=lines.append, frozen=False)
        assert code == 0
        assert any("fpx-converter" in line for line in lines)

    def test_the_child_finds_the_package_whatever_the_working_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`-m fpx_converter` resolves through PYTHONPATH, not through the cwd.

        A window launched from a shortcut has whatever working directory
        Windows felt like giving it.
        """
        monkeypatch.chdir(tmp_path)
        lines: list[str] = []
        assert runner.run_cli(["--version"], on_line=lines.append, frozen=False) == 0
        assert lines
