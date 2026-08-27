"""`audit_report.json`, turned into the sentences a person reads at the end.

The report is the authority on what happened -- not the exit code, not the
lines that scrolled past in the log pane. It is read back off disk after the
run and rendered here.

One thing this file exists to get right: **a partial or interrupted run must
say so, loudly and first.** `complete` is in the report precisely because a
limited run once produced `unexplained_failures: 0` and was indistinguishable
from a finished archive. "0 failed" reads as success to every eye that skims
it, so on an incomplete run the headline says the run is unfinished and the
counts come second.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

#: How a summary should be shown. The window maps these onto colours; they are
#: named for what they mean, not for what colour they are.
OK = "ok"
WARN = "warn"
ERROR = "error"


@dataclass(frozen=True)
class RunSummary:
    """What the run did, and how plainly it needs to be said."""

    headline: str
    severity: str
    lines: list[str] = field(default_factory=list)
    converted: int = 0
    resumed: int = 0
    failed: int = 0
    with_warnings: int = 0
    attempted: int = 0
    manifest_entries: int = 0
    complete: bool = False
    interrupted: bool = False

    @property
    def finished_cleanly(self) -> bool:
        return self.complete and not self.failed and not self.interrupted


def _int(counts: dict, key: str) -> int:
    try:
        return int(counts.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def summarise(report: dict) -> RunSummary:
    """Render one audit report. Tolerates a report missing any given field.

    Tolerant on purpose: a report written by a future version, or truncated by
    a kill mid-write, should still produce something a person can read. What
    it must never do is *invent* completeness -- `complete` defaults to False,
    so an unreadable report reads as unfinished rather than as finished.
    """
    counts = report.get("counts") or {}
    converted = _int(counts, "converted")
    resumed = _int(counts, "resumed")
    failed = _int(counts, "failed")
    warned = _int(counts, "with_warnings")
    attempted = _int(counts, "attempted")
    entries = _int(counts, "manifest_entries")
    complete = bool(report.get("complete", False))
    interrupted = bool(report.get("interrupted", False))

    lines = [
        f"{converted} converted, {resumed} already done, {failed} failed",
        f"{warned} finished with warnings",
        f"{attempted} of {entries} photos in the source folder were handled",
    ]
    elapsed = report.get("elapsed_seconds")
    if elapsed is not None:
        lines.append(f"took {elapsed} seconds")

    if interrupted:
        untouched = max(0, entries - attempted)
        return RunSummary(
            headline="Stopped before it finished — this is not a converted archive",
            severity=ERROR,
            lines=[
                f"{untouched} of {entries} photos were never reached.",
                "Nothing was lost: press Convert again and it picks up where it stopped.",
                *lines,
            ],
            converted=converted, resumed=resumed, failed=failed,
            with_warnings=warned, attempted=attempted, manifest_entries=entries,
            complete=complete, interrupted=True,
        )

    if not complete:
        untouched = max(0, entries - attempted)
        return RunSummary(
            headline="Partial run — this is not a converted archive",
            severity=ERROR,
            lines=[
                f"{untouched} of {entries} photos were not handled.",
                "Press Convert again to finish the rest.",
                *lines,
            ],
            converted=converted, resumed=resumed, failed=failed,
            with_warnings=warned, attempted=attempted, manifest_entries=entries,
            complete=False, interrupted=False,
        )

    if failed:
        return RunSummary(
            headline=f"Finished, but {failed} photo(s) could not be converted",
            severity=WARN,
            lines=[
                "The rest converted. Open the review page to see which failed and why.",
                *lines,
            ],
            converted=converted, resumed=resumed, failed=failed,
            with_warnings=warned, attempted=attempted, manifest_entries=entries,
            complete=True, interrupted=False,
        )

    headline = f"Finished — all {entries} photos converted"
    return RunSummary(
        headline=headline,
        severity=OK,
        lines=lines,
        converted=converted, resumed=resumed, failed=failed,
        with_warnings=warned, attempted=attempted, manifest_entries=entries,
        complete=True, interrupted=False,
    )


MISSING_REPORT = RunSummary(
    headline="No audit report was written — treat this run as unfinished",
    severity=ERROR,
    lines=[
        "Every finished run leaves audit_report.json in the destination folder.",
        "Its absence means the conversion was stopped in a way that gave it no "
        "chance to write one.",
    ],
)


def load_summary(report_path: Path) -> RunSummary:
    """Read and render the report at `report_path`.

    A missing or unreadable report is reported as such, never as a clean
    finish. That is the whole point of reading the file rather than trusting
    the exit code.
    """
    try:
        report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return MISSING_REPORT
    if not isinstance(report, dict):
        return MISSING_REPORT
    return summarise(report)
