"""Tier-1: the pipeline worker, with a fake CLI process.

`PipelineWorker` had no test at all. That would be unremarkable for a thin
adapter, except that it owns the cancellation path -- a thread, an `Event`, a
join, and a cross-thread read of the status that decides whether the window
tells somebody their audit report exists. The end-to-end test calls
`runner.CliProcess.cancel` directly and so walks straight past this class.

The whole point of the ending it reports is the difference between two of
them: a run that stopped politely and wrote its report, and one that had to be
killed and did not. Getting that backwards is worse than saying nothing.

No Qt widgets and no real child process: `runner.CliProcess` is replaced with a
fake whose timings are the interesting part.
"""

from __future__ import annotations

import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="the desktop front end needs requirements-gui.txt")

from PySide6.QtCore import Qt  # noqa: E402

from fpx_gui import runner, worker  # noqa: E402


class FakeProcess:
    """Stands in for `runner.CliProcess`.

    `cancel` sleeps for `cancel_takes` and then reports `cancel_status`, which
    is the shape of the real thing: it blocks while the child finishes the
    photo it is on and writes its report.
    """

    instances: list[FakeProcess] = []

    def __init__(self, args, on_line=None, **_kwargs) -> None:  # noqa: ANN001
        self.args = list(args)
        self.on_line = on_line
        self.started = threading.Event()
        self.release = threading.Event()
        self.cancel_calls = 0
        FakeProcess.instances.append(self)

    # Set by each test before the worker starts.
    cancel_takes = 0.0
    cancel_status = runner.CANCELLED
    exit_code = 0

    def start(self) -> None:
        self.started.set()

    def wait(self) -> int:
        # Runs until cancelled, like a real conversion.
        self.release.wait(timeout=30)
        return self.exit_code

    def cancel(self, stop_file=None) -> str:  # noqa: ANN001, ARG002
        """The child stops promptly; classifying *how* is the slow part.

        That order is the whole point. The real `cancel` sends the signal,
        then waits to see whether the child stopped on its own -- so `_run`
        can be released and ready to report the ending while the parent still
        does not know which ending it was. Sleeping before releasing would
        make the race untestable, which is what the first version of this fake
        did.
        """
        self.cancel_calls += 1
        self.release.set()
        time.sleep(type(self).cancel_takes)
        return type(self).cancel_status


@pytest.fixture(autouse=True)
def fake_cli(monkeypatch: pytest.MonkeyPatch) -> type[FakeProcess]:
    FakeProcess.instances = []
    FakeProcess.cancel_takes = 0.0
    FakeProcess.cancel_status = runner.CANCELLED
    FakeProcess.exit_code = 0
    monkeypatch.setattr(runner, "CliProcess", FakeProcess)
    monkeypatch.setattr(worker.runner, "CliProcess", FakeProcess)
    return FakeProcess


def _running_process(timeout: float = 10.0) -> FakeProcess:
    """Wait for the worker's thread to have actually started a step.

    `start()` returns as soon as the thread is spawned, so reading
    `instances[0]` straight afterwards is a race the test loses roughly one
    time in ten.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if FakeProcess.instances:
            process = FakeProcess.instances[0]
            if process.started.wait(timeout=timeout):
                return process
        time.sleep(0.01)
    raise AssertionError("the worker never started a step")


def _endings(w: worker.PipelineWorker) -> list[tuple[int, str]]:
    """Collect what `done` reports.

    `DirectConnection` on purpose. The default is `AutoConnection`, which for
    a signal emitted on a worker thread queues the call onto the receiver's
    event loop -- and there is no event loop here, so nothing would ever
    arrive and every assertion would fail for a reason that has nothing to do
    with the code under test. Direct means the slot runs on the emitting
    thread, which is what this needs and all it needs.
    """
    seen: list[tuple[int, str]] = []
    w.done.connect(
        lambda code, status: seen.append((code, status)),
        Qt.ConnectionType.DirectConnection,
    )
    return seen


class TestTheEndingItReports:
    def test_a_polite_cancel_is_reported_as_cancelled(self) -> None:
        """Not as an ordinary finish.

        The window uses this to decide whether to say "the report below covers
        what it did" or "no audit report was written".
        """
        w = worker.PipelineWorker([("convert", ["convert"])])
        seen = _endings(w)
        w.start()
        _running_process()
        w.cancel()
        w._thread.join(timeout=30)
        assert seen and seen[0][1] == runner.CANCELLED

    def test_a_hard_stop_is_reported_as_a_hard_stop(self) -> None:
        FakeProcess.cancel_status = runner.HARD_STOPPED
        w = worker.PipelineWorker([("convert", ["convert"])])
        seen = _endings(w)
        w.start()
        _running_process()
        w.cancel()
        w._thread.join(timeout=30)
        assert seen and seen[0][1] == runner.HARD_STOPPED

    def test_a_cancel_that_never_settles_is_not_reported_as_a_clean_finish(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The finding. A timeout must not read as "it stopped politely".

        The settle timeout used to be shorter than `CliProcess.cancel`'s own
        worst case, so the one ending it existed to classify -- a hard kill --
        was the one it could time out on, and the run then went down the
        normal-finish path with an empty status.
        """
        monkeypatch.setattr(worker, "CANCEL_SETTLE_TIMEOUT", 0.2)
        FakeProcess.cancel_takes = 1.5
        w = worker.PipelineWorker([("convert", ["convert"])])
        seen = _endings(w)
        w.start()
        _running_process()
        w.cancel()
        w._thread.join(timeout=30)
        assert seen, "the worker never reported an ending"
        assert seen[0][1] == runner.HARD_STOPPED, (
            f"a cancel that outlasted its timeout was reported as {seen[0][1]!r}"
        )

    def test_an_uncancelled_run_reports_no_cancel_status(self) -> None:
        w = worker.PipelineWorker([("convert", ["convert"])])
        seen = _endings(w)
        w.start()
        _running_process().release.set()
        w._thread.join(timeout=30)
        assert seen and seen[0][1] == ""


class TestCancellingIsSafeToDoTwice:
    def test_two_cancels_start_one_thread(self) -> None:
        """The check-and-set used to span two acquisitions of the lock, so two
        callers could both see None and both start a thread."""
        FakeProcess.cancel_takes = 0.4
        w = worker.PipelineWorker([("convert", ["convert"])])
        w.start()
        _running_process()

        started: list[threading.Thread] = []
        barrier = threading.Barrier(2)

        def press() -> None:
            barrier.wait(timeout=10)
            w.cancel()

        pressers = [threading.Thread(target=press) for _ in range(2)]
        for thread in pressers:
            thread.start()
        for thread in pressers:
            thread.join(timeout=30)
        started.append(w._cancel_thread)

        w._thread.join(timeout=30)
        assert FakeProcess.instances[0].cancel_calls == 1, (
            "the child was asked to cancel more than once"
        )

    def test_cancelling_with_nothing_running_returns_and_does_not_hang(self) -> None:
        w = worker.PipelineWorker([("convert", ["convert"])])
        w.cancel(wait=True)  # never started

    def test_cancel_wait_returns_once_the_cancel_has_finished(self) -> None:
        """What `closeEvent` relies on: do not leave a child unwatched."""
        FakeProcess.cancel_takes = 0.5
        w = worker.PipelineWorker([("convert", ["convert"])])
        w.start()
        _running_process()
        began = time.monotonic()
        w.cancel(wait=True)
        assert time.monotonic() - began >= 0.4, "cancel(wait=True) returned too early"
        assert w._cancel_settled.is_set()


class TestThePipeline:
    def test_a_failing_step_stops_the_ones_after_it(self) -> None:
        FakeProcess.exit_code = 1
        w = worker.PipelineWorker([("scan", ["scan"]), ("convert", ["convert"])])
        seen = _endings(w)
        w.start()
        _running_process().release.set()
        w._thread.join(timeout=30)
        assert len(FakeProcess.instances) == 1, "it ran a step after one failed"
        assert seen and seen[0][0] == 1

    def test_the_timeout_is_derived_from_what_it_waits_on(self) -> None:
        """It was guessed at, and was five seconds short of the worst case."""
        worst = (
            runner.GRACE_SECONDS + runner.TREE_KILL_TIMEOUT + runner.TERMINATE_TIMEOUT
        )
        assert worst <= worker.CANCEL_SETTLE_TIMEOUT
