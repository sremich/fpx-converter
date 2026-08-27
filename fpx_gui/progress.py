"""Reading progress out of what the CLI prints, rather than guessing at it.

`convert --progress` puts every line of `conversion.log` on stdout as it is
written, and those lines already carry the two numbers a determinate progress
bar needs:

    2001-01-01T00:00:00 === run start: 40 entries, outputs archive/tiff/full
    2001-01-01T00:00:00 OK   [1/40] example-0001.fpx -> 2 files in 0.6s
    2001-01-01T00:00:00 FAIL [2/40] example-0002.fpx: source file not found
    2001-01-01T00:00:00 WARN example-0003.fpx: no capture date could be defended
    2001-01-01T00:00:00 INTERRUPTED by the operator

**This is a display convenience and must never be able to fail a run.** A
line it cannot read is a line the log pane shows verbatim and the bar ignores;
`parse_line` returns `None` rather than raising, for anything at all. The
authority on what happened is `audit_report.json`, never this.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: `OK   [3/40] ...` / `FAIL [4/40] ...`, wherever the timestamp prefix ends.
_FILE_LINE = re.compile(r"\b(OK|FAIL)\s+\[(\d+)\s*/\s*(\d+)\]")
#: The header, which is the earliest point the total is known.
_RUN_START = re.compile(r"===\s*run start:\s*(\d+)\s+entries")
_INTERRUPTED = re.compile(r"\bINTERRUPTED\b")


@dataclass(frozen=True)
class ProgressEvent:
    """What one line said about how far along the run is.

    `done` and `total` are `None` on a line that only carried one of them --
    the header knows the total before any file has finished.
    """

    done: int | None = None
    total: int | None = None
    failed: bool = False
    interrupted: bool = False


def parse_line(line: object) -> ProgressEvent | None:
    """One line of CLI output, or `None` if it says nothing about progress.

    Catches everything. A progress bar that can raise is a progress bar that
    can kill a conversion, and this one watches a run over an irreplaceable
    archive.
    """
    try:
        text = line if isinstance(line, str) else str(line)
        match = _FILE_LINE.search(text)
        if match is not None:
            return ProgressEvent(
                done=int(match.group(2)),
                total=int(match.group(3)),
                failed=match.group(1) == "FAIL",
            )
        start = _RUN_START.search(text)
        if start is not None:
            return ProgressEvent(total=int(start.group(1)))
        if _INTERRUPTED.search(text):
            return ProgressEvent(interrupted=True)
    except Exception:  # noqa: BLE001 -- see the docstring; never propagate
        return None
    return None


class ProgressTracker:
    """Running totals fed one line at a time.

    Holds `total` once it has been seen, so a bar can stay determinate even
    across a line that failed to parse. `total` of `None` means "not known
    yet" and should read as an indeterminate bar rather than as zero.
    """

    def __init__(self) -> None:
        self.total: int | None = None
        self.done: int = 0
        self.failed: int = 0
        self.interrupted: bool = False

    def feed(self, line: str) -> bool:
        """Take one line. Returns whether anything about the run changed."""
        event = parse_line(line)
        if event is None:
            return False
        if event.total is not None:
            self.total = event.total
        if event.done is not None:
            # max, not assignment: the numbers arrive in order today, and a
            # bar that walked backwards on one reordered line would look like
            # a fault in the conversion rather than in the display.
            self.done = max(self.done, event.done)
        if event.failed:
            self.failed += 1
        if event.interrupted:
            self.interrupted = True
        return True

    @property
    def fraction(self) -> float | None:
        """Progress in 0..1, or `None` while the total is unknown."""
        if not self.total:
            return None
        return min(1.0, self.done / self.total)
