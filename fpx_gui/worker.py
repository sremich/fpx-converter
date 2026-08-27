"""Running a pipeline of CLI steps off the GUI thread, reporting back by signal.

`runner.CliProcess` reads the child's output on a plain thread, which is
exactly what a window must not do with it. Everything crossing back into the
window crosses as a Qt signal, so the widgets are only ever touched from the
thread that owns them.

The pipeline stops at the first step that fails. That is not the same as
stopping at the first step that reports failures: `convert` exits 2 when some
files could not be converted, and it is the last step, so the run is over
either way and `audit_report.json` is what says what happened.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from . import runner


class PipelineWorker(QObject):
    """A sequence of `(label, cli_args)` steps, run one after another."""

    #: One line of child output, already stripped of its newline.
    line = Signal(str)
    #: A step is starting: label, its 1-based number, how many there are.
    step = Signal(str, int, int)
    #: The run is over: last exit code, and how it ended -- "" for normally,
    #: `runner.CANCELLED` or `runner.HARD_STOPPED` for a Cancel.
    done = Signal(int, str)

    def __init__(
        self,
        steps: list[tuple[str, list[str]]],
        parent: QObject | None = None,
        stop_file: Path | None = None,
    ):
        super().__init__(parent)
        self._steps = steps
        self._stop_file = stop_file
        self._thread: threading.Thread | None = None
        self._process: runner.CliProcess | None = None
        self._cancel_status = ""
        self._cancelling = False
        self._lock = threading.Lock()
        #: Set once a cancel has finished deciding how the run ended, so
        #: `_run` does not report the ending before `cancel` knows it.
        self._cancel_settled = threading.Event()
        self._cancel_thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self, *, wait: bool = False) -> None:
        """Ask the running step to stop, and stop the pipeline after it.

        Returns immediately by default. Stopping a run politely means waiting
        for the engine to finish the photo it is on, save its state and write
        its report -- up to `runner.GRACE_SECONDS` -- and doing that on the
        Qt thread froze the window for the whole of it, right after the person
        pressed Cancel. A window that stops repainting reads as a crash, and
        the crash remedy is Task Manager, which is the one ending that leaves
        no audit report.

        `wait=True` is for closing the window, where blocking briefly is the
        lesser evil: the alternative is a converter still running with nothing
        watching it.

        Safe to call when nothing is running: `CliProcess.cancel` says so and
        the flag stops any step that has not started yet.
        """
        with self._lock:
            already = self._cancel_thread
            self._cancelling = True
        if already is None:
            thread = threading.Thread(target=self._do_cancel, daemon=True)
            with self._lock:
                self._cancel_thread = thread
            thread.start()
        else:
            thread = already
        if wait:
            thread.join(timeout=runner.GRACE_SECONDS + 15.0)

    def _do_cancel(self) -> None:
        """The blocking half, off the Qt thread."""
        try:
            with self._lock:
                process = self._process
            if process is not None:
                status = process.cancel(stop_file=self._stop_file)
                if status != runner.NOT_RUNNING:
                    self._cancel_status = status
        finally:
            self._cancel_settled.set()

    def _run(self) -> None:
        code = 0
        total = len(self._steps)
        for index, (label, args) in enumerate(self._steps, start=1):
            with self._lock:
                if self._cancelling:
                    break
            self.step.emit(label, index, total)
            process = runner.CliProcess(args, on_line=self.line.emit)
            with self._lock:
                self._process = process
            try:
                process.start()
                code = process.wait()
            except OSError as exc:
                self.line.emit(f"could not start the converter: {exc}")
                code = 1
            finally:
                with self._lock:
                    self._process = None
            if code != 0:
                break
        with self._lock:
            cancelling = self._cancelling
        if cancelling:
            # The child usually dies before `cancel` has finished classifying
            # how it died. Reporting first would lose the difference between a
            # run that stopped politely -- report written -- and one that had
            # to be killed.
            self._cancel_settled.wait(timeout=runner.GRACE_SECONDS + 15.0)
        self.done.emit(code, self._cancel_status)
