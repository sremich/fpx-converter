"""Tier-1: what the window says at the end, from a hand-built audit report.

The case this file exists for is the partial run. `complete` is in the report
because a `--limit` run over a 687-file manifest once produced
`unexplained_failures: 0` and was indistinguishable from a finished archive.
The window inherits that trap in a worse form -- a progress bar sitting at
100% and a green line saying "0 failed" -- so the tests below insist that an
incomplete run leads with the fact that it is incomplete.

The reports here are built by hand. No archive, no real album, no real
filename.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpx_gui import summary


def report(
    *,
    converted: int = 40,
    resumed: int = 0,
    failed: int = 0,
    with_warnings: int = 0,
    attempted: int | None = None,
    manifest_entries: int = 40,
    complete: bool = True,
    interrupted: bool = False,
) -> dict:
    handled = attempted if attempted is not None else converted + resumed + failed
    return {
        "report_version": 1,
        "elapsed_seconds": 12.5,
        "interrupted": interrupted,
        "complete": complete,
        "unexplained_failures": failed,
        "counts": {
            "manifest_entries": manifest_entries,
            "selected": handled,
            "attempted": handled,
            "converted": converted,
            "resumed": resumed,
            "failed": failed,
            "with_warnings": with_warnings,
        },
    }


class TestACleanRun:
    def test_it_reads_as_finished(self) -> None:
        result = summary.summarise(report())
        assert result.severity == summary.OK
        assert result.finished_cleanly
        assert "Finished" in result.headline

    def test_the_counts_survive(self) -> None:
        result = summary.summarise(report(converted=30, resumed=10, with_warnings=4))
        assert (result.converted, result.resumed, result.with_warnings) == (30, 10, 4)
        assert any("30 converted" in line for line in result.lines)
        assert any("4 finished with warnings" in line for line in result.lines)


class TestAPartialRun:
    """The failure mode this module is written against."""

    def test_a_limited_run_is_not_a_finished_archive(self) -> None:
        result = summary.summarise(
            report(converted=4, manifest_entries=687, complete=False)
        )
        assert result.severity == summary.ERROR
        assert not result.finished_cleanly
        assert "Partial" in result.headline

    def test_it_says_so_before_it_says_zero_failed(self) -> None:
        """Order matters. "0 failed" reads as success to an eye that skims."""
        result = summary.summarise(
            report(converted=4, manifest_entries=687, complete=False)
        )
        assert "not a converted archive" in result.headline
        assert "683 of 687" in result.lines[0]

    def test_zero_failures_does_not_make_it_look_clean(self) -> None:
        result = summary.summarise(
            report(converted=4, failed=0, manifest_entries=687, complete=False)
        )
        assert result.severity != summary.OK

    def test_an_interrupted_run_leads_with_the_interruption(self) -> None:
        result = summary.summarise(
            report(converted=12, manifest_entries=687, complete=False, interrupted=True)
        )
        assert result.interrupted
        assert result.severity == summary.ERROR
        assert "Stopped" in result.headline
        assert any("picks up where it stopped" in line for line in result.lines)


class TestFailures:
    def test_a_complete_run_with_failures_is_a_warning_not_a_success(self) -> None:
        result = summary.summarise(report(converted=38, failed=2))
        assert result.severity == summary.WARN
        assert not result.finished_cleanly
        assert "2 photo(s)" in result.headline


class TestReadingItOffDisk:
    def test_it_renders_a_report_from_a_file(self, tmp_path: Path) -> None:
        path = tmp_path / "audit_report.json"
        path.write_text(json.dumps(report()), encoding="utf-8")
        assert summary.load_summary(path).finished_cleanly

    @pytest.mark.parametrize("content", ["", "{not json", "[]", '"a string"'])
    def test_an_unreadable_report_reads_as_unfinished(
        self, tmp_path: Path, content: str
    ) -> None:
        path = tmp_path / "audit_report.json"
        path.write_text(content, encoding="utf-8")
        result = summary.load_summary(path)
        assert result.severity == summary.ERROR
        assert not result.finished_cleanly

    def test_a_missing_report_reads_as_unfinished(self, tmp_path: Path) -> None:
        """The ending a hard kill leaves behind. It must not look like success."""
        result = summary.load_summary(tmp_path / "nothing.json")
        assert result.severity == summary.ERROR
        assert "unfinished" in result.headline

    def test_a_report_missing_every_field_is_not_called_complete(self) -> None:
        """Tolerant about what it can read; never generous about completeness."""
        result = summary.summarise({})
        assert not result.complete
        assert not result.finished_cleanly
        assert result.severity == summary.ERROR

    def test_nonsense_counts_do_not_raise(self) -> None:
        result = summary.summarise(
            {"complete": True, "counts": {"converted": "many", "manifest_entries": None}}
        )
        assert result.converted == 0
