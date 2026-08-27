"""The batch engine: run the whole corpus, survive anything, resume anywhere.

Three properties, each paid for by something that actually happens:

* **It never aborts on one bad file.** A run over 687 irreplaceable
  photographs that stops at file 300 because one has a corrupt tile has
  converted nothing useful and told you about one problem instead of all of
  them. Every failure is recorded and the run continues.
* **It resumes by hash.** A killed run -- the five-hour usage window, a
  crash, a machine switch -- costs the file in flight, not the batch. State
  is keyed on the source SHA-256, which is also this project's dedup key, so
  resuming is exact rather than a guess from timestamps.
* **It reports.** `audit_report.json` is the artifact the 1.0.0 gate reads,
  and `conversion.log` is the human-readable trail beside it.

The report has one job that is easy to get wrong: **roughly 146 output pairs
are pixel-identical and that is correct, not a fault.** Dedup keys on the
whole file, so two `.fpx` files whose pixels match but whose bytes differ are
both kept deliberately. An audit that flagged those would bury the real
failures under 146 false ones, so they are counted and named as expected.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import platform
import signal
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import __version__, outputs
from . import name_template as name_template_mod

STATE_VERSION = 2
STATE_FILENAME = "run-state.json"
LOG_FILENAME = "conversion.log"
REPORT_FILENAME = "audit_report.json"


def now_iso() -> str:
    """Local wall-clock, matching how this project stores every other time."""
    return datetime.datetime.now().isoformat(timespec="seconds")


def _raise_keyboard_interrupt(signum: int, frame: object) -> None:  # noqa: ARG001
    raise KeyboardInterrupt


def interrupt_on_break() -> bool:
    """Make Ctrl+Break behave like Ctrl+C. Returns whether it took effect.

    Everything this engine does to survive an interruption hangs off
    `KeyboardInterrupt`: the run stops, the state is saved, and
    `audit_report.json` is still written. On Windows only `CTRL_C_EVENT`
    arrives that way by default; `CTRL_BREAK_EVENT` takes the OS default and
    kills the process where it stands, leaving no report behind.

    That matters beyond a terminal. A parent process that wants to cancel a
    child **cannot** use `CTRL_C_EVENT`: a child created with
    `CREATE_NEW_PROCESS_GROUP` -- the only way to signal one child without
    signalling the whole console -- has Ctrl+C disabled by Windows.
    `CTRL_BREAK_EVENT` is the one signal that can reach it, so this is what
    makes a cancelled run distinguishable from a killed one.

    Installed by the entry points, not at import: `signal.signal` only works
    on the main thread, and a library that mutated global signal handlers on
    import would do it inside every caller's process too.
    """
    sigbreak = getattr(signal, "SIGBREAK", None)
    if sigbreak is None:  # not Windows
        return False
    try:
        signal.signal(sigbreak, _raise_keyboard_interrupt)
    except (OSError, ValueError):
        # Not the main thread, or a platform that refuses the handler. A run
        # that cannot be cancelled politely is still a run worth having.
        return False
    return True


@dataclass
class FileRecord:
    """What happened to one source file. Everything the audit needs."""

    sha256: str
    store_name: str
    album: str
    status: str  # 'converted' | 'failed' | 'resumed'
    date_source: str = "none"
    is_undated: bool = True
    date_original: str = ""
    transform_status: str = ""
    crop_applied: tuple[int, int, int, int] | None = None
    outputs: list[str] = field(default_factory=list)
    pixel_sha256: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    seconds: float = 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "sha256": self.sha256,
            "store_name": self.store_name,
            "album": self.album,
            "status": self.status,
            "date_source": self.date_source,
            "is_undated": self.is_undated,
            "date_original": self.date_original,
            "transform_status": self.transform_status,
            "crop_applied": list(self.crop_applied) if self.crop_applied else None,
            "outputs": self.outputs,
            "pixel_sha256": self.pixel_sha256,
            "errors": self.errors,
            "warnings": self.warnings,
            "seconds": round(self.seconds, 3),
        }


def record_from_json(raw: dict[str, Any]) -> FileRecord:
    """Rebuild a stored record so a resumed run reports the same detail."""
    box = raw.get("crop_applied")
    return FileRecord(
        sha256=raw.get("sha256", ""),
        store_name=raw.get("store_name", ""),
        album=raw.get("album", ""),
        # Marked as resumed, not converted: this run did not do the work, and
        # a report that claimed otherwise would misreport its own elapsed time
        # and throughput.
        status="resumed",
        date_source=raw.get("date_source", "none"),
        is_undated=bool(raw.get("is_undated", True)),
        date_original=raw.get("date_original", ""),
        transform_status=raw.get("transform_status", ""),
        crop_applied=tuple(box) if box else None,  # type: ignore[arg-type]
        outputs=list(raw.get("outputs", [])),
        pixel_sha256=raw.get("pixel_sha256"),
        # Both lists, not just warnings. Only successful records are stored
        # today so `errors` is always empty -- but a field that is silently
        # dropped on the way back is a bug waiting for that to change.
        errors=list(raw.get("errors", [])),
        warnings=list(raw.get("warnings", [])),
        seconds=float(raw.get("seconds", 0.0)),
    )


def pixel_digest(image) -> str:  # noqa: ANN001 -- PIL.Image.Image
    """SHA-256 of the decoded pixels, for spotting expected duplicates.

    Not a dedup key and never used as one -- `CLAUDE.md` is explicit that
    dedup is on the whole source file. This exists so the audit can *explain*
    the ~146 identical output pairs instead of reporting them as faults.
    """
    rgb = image if image.mode == "RGB" else image.convert("RGB")
    return hashlib.sha256(rgb.tobytes()).hexdigest()


class RunState:
    """Which files this destination has already converted, and under what specs.

    Persisted after every file. Writing it less often would be faster and
    would also mean a kill costs however many files came after the last
    write, which is the thing this exists to prevent.
    """

    def __init__(
        self,
        path: Path,
        specs: tuple[outputs.OutputSpec, ...],
        name_template: str | None = None,
        folder_key: str = "album",
    ) -> None:
        self.path = path
        self.spec_labels = sorted(spec.label for spec in specs)
        self.name_template = name_template or name_template_mod.DEFAULT_TEMPLATE
        self.folder_key = folder_key
        self.done: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # A truncated state file means the last run died mid-write. Losing
            # it costs a re-conversion; trusting it could skip a file that was
            # never actually written.
            return
        if raw.get("state_version") != STATE_VERSION:
            return
        # Specs decide which files exist on disk. A run that changed them is
        # not the same run, and resuming across the change would leave a tree
        # half in one shape and half in the other.
        if raw.get("spec_labels") != self.spec_labels:
            return
        # The filename pattern decides what those files are *called*. Resuming
        # across a change to it would skip nothing and rename nothing, leaving
        # half the tree under the old pattern and half under the new one, with
        # no record of which was which. Same reasoning as the specs above.
        if raw.get("name_template", name_template_mod.DEFAULT_TEMPLATE) != self.name_template:
            return
        # And which folders they land in, for the same reason.
        if raw.get("folder_key", "album") != self.folder_key:
            return
        done = raw.get("done")
        if isinstance(done, dict):
            self.done = done

    def is_done(self, sha: str, output_root: Path) -> bool:
        """Recorded as converted **and** its files are still on disk.

        The second half matters: somebody deleting the output tree and
        re-running must get their files back, not a run that skips everything
        and reports success.
        """
        record = self.done.get(sha)
        if not record:
            return False
        return all((output_root / rel).is_file() for rel in record.get("outputs", []))

    def mark(self, sha: str, record: FileRecord) -> None:
        """Record the whole result, not just the paths.

        `audit_report.json` has to describe the output tree, not the last
        invocation. Without the detail stored here, a resumed run reports
        every file as a bare "resumed" with no date source, no transform
        outcome and no pixel hash -- so a corpus converted across three
        sessions would produce a final report that could not answer the
        questions the 1.0.0 gate asks.
        """
        self.done[sha] = {
            "outputs": record.outputs,
            "at": now_iso(),
            "record": record.to_json(),
        }

    def recall(self, sha: str) -> dict[str, Any] | None:
        """The stored result for a file an earlier run converted."""
        entry = self.done.get(sha)
        return entry.get("record") if entry else None

    def save(self) -> None:
        payload = {
            "state_version": STATE_VERSION,
            "spec_labels": self.spec_labels,
            "name_template": self.name_template,
            "folder_key": self.folder_key,
            "tool_version": __version__,
            "updated": now_iso(),
            "done": self.done,
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
        tmp.replace(self.path)


class ConversionLog:
    """Append-only, flushed per line, so a kill -9 keeps what it had.

    The echo is a second audience and never a substitute: the file is written
    and flushed first, and a callback that raises is dropped rather than
    allowed to end the run.

    `echo` optionally receives each finished line as well, which is how
    `convert --progress` puts the per-file trail on stdout. The file is
    written either way: the echo is a second audience, never a substitute.
    """

    def __init__(self, path: Path, echo: Callable[[str], None] | None = None) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a", encoding="utf-8")
        self._echo = echo

    def write(self, message: str) -> None:
        line = f"{now_iso()} {message}"
        self._handle.write(f"{line}\n")
        self._handle.flush()
        if self._echo is not None:
            try:
                self._echo(line)
            except OSError:
                # A dead reader costs the trail, never the run. These writes
                # sit outside the per-file `except` that makes one bad file a
                # line in the report, so an exception here escaped the loop
                # entirely and no `audit_report.json` was written -- over a
                # 687-file archive, for a closed pipe. Dropped permanently
                # because the reader is not coming back: a closed pipe, a full
                # disk and a closed handle are all `OSError` and none of them
                # heal.
                self._echo = None
            except Exception:
                # Everything else costs one line and no more. The example is a
                # filename the console's code page cannot encode: that is a
                # property of the one line, not of the reader, and dropping
                # the echo for good would cost a terminal user the progress
                # display for every remaining file -- the "it looks hung"
                # ending this exists to avoid.
                pass

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> ConversionLog:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def build_audit_report(
    records: list[FileRecord],
    *,
    specs: tuple[outputs.OutputSpec, ...],
    output_root: Path,
    started: str,
    elapsed: float,
    total_entries: int,
    manifest_entries: int | None = None,
    interrupted: bool = False,
) -> dict[str, Any]:
    """The artifact the release gate reads. Faults first, then explanation.

    `total_entries` is how many entries this run was asked to handle;
    `manifest_entries` is how many exist. They differ under `--limit`, and the
    difference is the whole point: without it a three-file run over a 687-file
    manifest reported `unexplained_failures: 0` and was indistinguishable from
    a finished archive. `complete` is the flag the 1.0.0 gate reads alongside
    the failure count.
    """
    by_status = Counter(r.status for r in records)
    # "Present in the output tree", which is converted plus resumed. The
    # report describes the tree, not this invocation -- a corpus built
    # across three sessions must still produce one complete picture.
    present = [r for r in records if r.status in ("converted", "resumed")]
    failed = [r for r in records if r.status == "failed"]

    pixel_groups: dict[str, list[str]] = defaultdict(list)
    for record in present:
        if record.pixel_sha256:
            pixel_groups[record.pixel_sha256].append(record.store_name)
    duplicates = {k: v for k, v in pixel_groups.items() if len(v) > 1}

    return {
        "report_version": 1,
        "tool_version": __version__,
        "python": platform.python_version(),
        "started": started,
        "finished": now_iso(),
        "elapsed_seconds": round(elapsed, 1),
        "interrupted": interrupted,
        "output_root": str(output_root),
        "outputs": [spec.label for spec in specs],
        "counts": {
            "manifest_entries": (
                manifest_entries if manifest_entries is not None else total_entries
            ),
            "selected": total_entries,
            "attempted": len(records),
            # Entries the run never reached: a `--limit`, or an interrupt.
            # Silence here is how a partial run passes for a whole one.
            "not_attempted": max(0, total_entries - len(records)),
            "converted": by_status.get("converted", 0),
            "resumed": by_status.get("resumed", 0),
            "failed": by_status.get("failed", 0),
            "with_warnings": sum(1 for r in records if r.warnings),
        },
        # The number the 1.0.0 gate is actually about -- but only meaningful
        # beside `complete`. Zero failures over three of 687 files is not a
        # passing run, it is an unfinished one.
        "unexplained_failures": len(failed),
        "complete": (
            not interrupted
            and len(records) == total_entries
            and total_entries
            == (manifest_entries if manifest_entries is not None else total_entries)
        ),
        "failures": [
            {"store_name": r.store_name, "sha256": r.sha256, "errors": r.errors}
            for r in failed
        ],
        "warnings": [
            {"store_name": r.store_name, "warnings": r.warnings}
            for r in records
            if r.warnings
        ],
        "date_sources": dict(Counter(r.date_source for r in present)),
        "transform_status": dict(
            Counter(r.transform_status for r in present if r.transform_status)
        ),
        "crops_applied": sum(1 for r in present if r.crop_applied),
        "albums": dict(Counter(r.album for r in present)),
        # Expected, and labelled as such. Dedup keys on the whole source file,
        # so two files with identical pixels and different bytes are both kept
        # on purpose. Flagging them would bury the real failures.
        "expected_pixel_identical_groups": {
            "count": len(duplicates),
            "files_involved": sum(len(v) for v in duplicates.values()),
            "note": (
                "Not faults. Dedup keys on the whole source file per CLAUDE.md, "
                "so pixel-identical outputs from byte-different sources are the "
                "expected consequence."
            ),
            "groups": [sorted(v) for v in duplicates.values()],
        },
        "files": [r.to_json() for r in records],
    }


def write_audit_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=1, ensure_ascii=True) + "\n", encoding="utf-8")


def summarise(report: dict[str, Any]) -> str:
    """The lines a person reads at the end of a run."""
    counts = report["counts"]
    dupes = report["expected_pixel_identical_groups"]
    lines = [
        f"  converted {counts['converted']}, resumed {counts['resumed']}, "
        f"failed {counts['failed']} of {counts['manifest_entries']}",
        f"  {counts['with_warnings']} with warnings, "
        f"{report['crops_applied']} cropped outputs",
        f"  {dupes['files_involved']} files in {dupes['count']} pixel-identical "
        f"groups (expected, not faults)",
        f"  elapsed {report['elapsed_seconds']}s",
    ]
    if report["interrupted"]:
        lines.append("  INTERRUPTED -- rerun to resume where this stopped")
    if not report.get("complete", True):
        # Stated plainly, because "0 failed" on a partial run reads as
        # success to every eye that skims it.
        untouched = counts["manifest_entries"] - counts.get("attempted", 0)
        lines.append(
            f"  PARTIAL RUN -- {untouched} of {counts['manifest_entries']} "
            "manifest entries were not handled; this is not a finished archive"
        )
    return "\n".join(lines)


def elapsed_since(start: float) -> float:
    return time.time() - start
