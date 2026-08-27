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

    def __init__(self, steps: list[tuple[str, list[str]]], parent: QObject | None = None):
        super().__init__(parent)
        self._steps = steps
        self._thread: threading.Thread | None = None
        self._process: runner.CliProcess | None = None
        self._cancel_status = ""
        self._cancelling = False
        self._lock = threading.Lock()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        """Ask the running step to stop, and stop the pipeline after it.

        Safe to call when nothing is running: `CliProcess.cancel` says so and
        the flag stops any step that has not started yet.
        """
        with self._lock:
            self._cancelling = True
            process = self._process
        if process is not None:
            status = process.cancel()
            if status != runner.NOT_RUNNING:
                self._cancel_status = status

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
        self.done.emit(code, self._cancel_status)
