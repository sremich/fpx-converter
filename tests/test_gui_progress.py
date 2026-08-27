"""Tier-1: reading progress out of the CLI's own output.

The parser is a display convenience watching a run over an irreplaceable
archive, so half of this file is about what it does with lines it cannot
read. The answer has to be "nothing, quietly": a progress bar that can raise
is a progress bar that can kill a conversion.

Every filename here is invented.
"""

from __future__ import annotations

import pytest

from fpx_gui import progress

OK_LINE = "2001-01-01T00:00:00 OK   [3/40] example-0003.fpx -> 2 files in 0.7s"
FAIL_LINE = "2001-01-01T00:00:00 FAIL [4/40] example-0004.fpx: source file not found"
START_LINE = (
    "2001-01-01T00:00:00 === run start: 40 entries, outputs archive/tiff/full, "
    "sharing/jpeg/cropped"
)


class TestParsingTheLinesItKnows:
    def test_a_converted_file_gives_both_numbers(self) -> None:
        event = progress.parse_line(OK_LINE)
        assert event == progress.ProgressEvent(done=3, total=40, failed=False)

    def test_a_failed_file_still_counts_as_progress(self) -> None:
        """It is done with, whatever happened to it; the bar must not stall."""
        event = progress.parse_line(FAIL_LINE)
        assert event is not None
        assert (event.done, event.total, event.failed) == (4, 40, True)

    def test_the_header_gives_the_total_before_any_file_finishes(self) -> None:
        event = progress.parse_line(START_LINE)
        assert event == progress.ProgressEvent(total=40)

    def test_an_interrupt_is_noticed(self) -> None:
        event = progress.parse_line("2001-01-01T00:00:00 INTERRUPTED by the operator")
        assert event is not None and event.interrupted

    def test_it_works_without_the_timestamp_prefix(self) -> None:
        event = progress.parse_line("OK   [7/9] example-0007.fpx -> 1 files in 0.1s")
        assert event is not None and (event.done, event.total) == (7, 9)


class TestLinesItCannotRead:
    @pytest.mark.parametrize(
        "line",
        [
            "",
            "   ",
            "Converting 40 files -> C:/out",
            "2001-01-01T00:00:00 WARN example-0005.fpx: no defensible capture date",
            "OK [not a number/40]",
            "OK   [3/0] example.fpx",
            "\x00\x01 binary noise \uFFFD",
            "OK   [999999999999999999999999/1]",
        ],
    )
    def test_an_unparseable_line_is_ignored_and_never_raises(self, line: str) -> None:
        result = progress.parse_line(line)
        assert result is None or isinstance(result, progress.ProgressEvent)

    @pytest.mark.parametrize("value", [None, 3, object(), b"\xff\xfe"])
    def test_it_survives_something_that_is_not_a_line_at_all(self, value: object) -> None:
        """The claim is that it does not raise, whatever it is handed."""
        result = progress.parse_line(value)
        assert result is None or isinstance(result, progress.ProgressEvent)

    def test_it_swallows_an_exception_from_deep_inside(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A guard that cannot be shown to hold is not a guard.

        The promise is that nothing this parser does can end a conversion, so
        the promise is tested by making the parser itself blow up.
        """
        class Exploding:
            def search(self, _text: str) -> None:
                raise RuntimeError("the parser broke")

        monkeypatch.setattr(progress, "_FILE_LINE", Exploding())
        assert progress.parse_line(OK_LINE) is None
        assert progress.ProgressTracker().feed(OK_LINE) is False

    def test_the_tracker_reports_that_nothing_changed(self) -> None:
        tracker = progress.ProgressTracker()
        assert tracker.feed("Converting 40 files -> C:/out") is False
        assert tracker.done == 0
        assert tracker.fraction is None


class TestTheTracker:
    def test_it_stays_indeterminate_until_the_total_is_known(self) -> None:
        tracker = progress.ProgressTracker()
        assert tracker.fraction is None
        tracker.feed(START_LINE)
        assert tracker.fraction == 0.0

    def test_it_follows_a_run_to_the_end(self) -> None:
        tracker = progress.ProgressTracker()
        tracker.feed(START_LINE)
        for index in range(1, 41):
            tracker.feed(f"OK   [{index}/40] example-{index:04d}.fpx -> 2 files in 0.1s")
        assert tracker.done == 40
        assert tracker.fraction == 1.0

    def test_it_counts_failures_without_stalling(self) -> None:
        tracker = progress.ProgressTracker()
        tracker.feed(OK_LINE)
        tracker.feed(FAIL_LINE)
        assert tracker.failed == 1
        assert tracker.done == 4

    def test_a_line_it_cannot_read_does_not_lose_the_total(self) -> None:
        """The reason `total` is held rather than taken from each line."""
        tracker = progress.ProgressTracker()
        tracker.feed(START_LINE)
        tracker.feed("something entirely unexpected")
        tracker.feed("OK   [5/40] example-0005.fpx -> 2 files in 0.2s")
        assert tracker.total == 40
        assert tracker.fraction == pytest.approx(0.125)

    def test_it_never_walks_backwards(self) -> None:
        """A bar going into reverse reads as a fault in the conversion."""
        tracker = progress.ProgressTracker()
        tracker.feed("OK   [9/40] example-0009.fpx -> 2 files in 0.2s")
        tracker.feed("OK   [2/40] example-0002.fpx -> 2 files in 0.2s")
        assert tracker.done == 9

    def test_it_notices_an_interrupted_run(self) -> None:
        tracker = progress.ProgressTracker()
        tracker.feed("2001-01-01T00:00:00 INTERRUPTED by the operator")
        assert tracker.interrupted is True
