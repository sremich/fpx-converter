"""Tier-1: a dead reader costs the trail, never the run.

`convert --progress` mirrors each per-file line onto stdout so a front end --
or a person watching a 687-file run -- sees something happen. The callback that
does it was unguarded, and the `log.write` calls sit *outside* the per-file
`except` that turns one bad file into a line in the report. So an exception
from the echo escaped `_handle_entry`, escaped the loop, sailed past the
`except KeyboardInterrupt`, and left the `with ConversionLog` block before
`state.save()` and `write_audit_report()` ever ran.

The reachable version of that: the GUI is killed from Task Manager mid-run,
the read end of the pipe closes, the child's next write raises
`BrokenPipeError`, and a run that would previously have carried on instead
dies with no report at all. Also `convert --progress > file` on a full disk,
and a legacy code page that cannot encode a human-authored filename.

The engine's contract is that it never aborts over one file and that an
interruption still writes the report. A progress display must not be able to
take either away.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fpx_converter import batch


class _Reader:
    """An echo that dies after `n` lines, the way a closed pipe does."""

    def __init__(self, die_after: int, error: type[BaseException] = BrokenPipeError) -> None:
        self.die_after = die_after
        self.error = error
        self.seen: list[str] = []

    def __call__(self, line: str) -> None:
        self.seen.append(line)
        if len(self.seen) > self.die_after:
            raise self.error("the pipe has been ended")


@pytest.mark.parametrize(
    "error",
    [BrokenPipeError, OSError, UnicodeEncodeError],
    ids=["closed-pipe", "disk-full", "legacy-code-page"],
)
def test_an_echo_that_raises_does_not_stop_the_log(
    error: type[BaseException], tmp_path: Path
) -> None:
    """Every way a writer to stdout can fail, on the same code path."""

    def echo(_line: str) -> None:
        if error is UnicodeEncodeError:
            raise UnicodeEncodeError("cp1252", "x", 0, 1, "no")
        raise error("gone")

    with batch.ConversionLog(tmp_path / "conversion.log", echo=echo) as log:
        for i in range(5):
            log.write(f"OK   [{i}/5] something")

    written = (tmp_path / "conversion.log").read_text(encoding="utf-8")
    assert written.count("OK   [") == 5, "the file lost lines because the echo failed"


def test_the_file_keeps_every_line_after_the_reader_goes_away(
    tmp_path: Path,
) -> None:
    """The file is the record; the echo is a second audience."""
    reader = _Reader(die_after=2)
    with batch.ConversionLog(tmp_path / "conversion.log", echo=reader) as log:
        for i in range(6):
            log.write(f"OK   [{i}/6] something")

    written = (tmp_path / "conversion.log").read_text(encoding="utf-8")
    assert written.count("OK   [") == 6


def test_the_echo_is_dropped_rather_than_retried_every_line(
    tmp_path: Path,
) -> None:
    """Once the reader is gone it is not coming back.

    Calling it again for every remaining file would mean raising and swallowing
    an exception 600 more times, which is slower and no more useful.
    """
    reader = _Reader(die_after=1)
    with batch.ConversionLog(tmp_path / "conversion.log", echo=reader) as log:
        for i in range(10):
            log.write(f"line {i}")

    assert len(reader.seen) == 2, (
        f"the echo was called {len(reader.seen)} times; it should stop after it fails"
    )


def test_a_working_echo_still_gets_every_line(tmp_path: Path) -> None:
    """The guard must not cost the feature it protects."""
    seen: list[str] = []
    with batch.ConversionLog(tmp_path / "conversion.log", echo=seen.append) as log:
        for i in range(4):
            log.write(f"line {i}")
    assert len(seen) == 4
    assert all(line.startswith("20") for line in seen), "the echo lost its timestamp"

def test_a_keyboard_interrupt_from_the_echo_still_gets_through(
    tmp_path: Path,
) -> None:
    """The guard must not swallow the interrupt that writes the report.

    `except Exception` lets `KeyboardInterrupt` past, because it is a
    `BaseException` -- but nothing pinned that, and this guard sits directly on
    the path that saves state and writes `audit_report.json`. A later
    "let us be safe and catch everything" would break the interrupt silently,
    and the symptom would be a Ctrl-C that produces no report: the exact bug
    this project has already fixed twice.
    """

    def echo(_line: str) -> None:
        raise KeyboardInterrupt

    with (
        pytest.raises(KeyboardInterrupt),
        batch.ConversionLog(tmp_path / "conversion.log", echo=echo) as log,
    ):
        log.write("OK   [1/5] something")

    # And the line was written and flushed before the echo ran, so the trail
    # keeps what it had.
    assert "OK   [1/5]" in (tmp_path / "conversion.log").read_text(encoding="utf-8")


def test_a_per_line_failure_does_not_cost_the_rest_of_the_run(
    tmp_path: Path,
) -> None:
    """A filename the console cannot encode is not a dead reader.

    Dropping the echo for good on a `UnicodeEncodeError` would cost a terminal
    user the progress display for every remaining file, over one odd filename
    -- the "it looks hung" ending the progress flag exists to prevent. Only
    `OSError` -- a closed pipe, a full disk, a closed handle -- is terminal.
    """
    seen: list[str] = []

    def echo(line: str) -> None:
        seen.append(line)
        if len(seen) == 2:
            raise UnicodeEncodeError("cp1252", "x", 0, 1, "no")

    with batch.ConversionLog(tmp_path / "conversion.log", echo=echo) as log:
        for i in range(6):
            log.write(f"line {i}")

    assert len(seen) == 6, (
        f"the echo stopped after a per-line failure; it saw {len(seen)} of 6"
    )
