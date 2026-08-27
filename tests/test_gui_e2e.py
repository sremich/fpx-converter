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
