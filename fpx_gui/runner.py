"""Running the CLI as a child process, streaming its output, and stopping it well.

Qt-free on purpose: this is the part that actually does the work, so it is
the part the end-to-end test drives directly, with no window and no event
loop in the way.

**Cancellation is the interesting half.** The batch engine already knows how
to be interrupted -- it catches `KeyboardInterrupt`, saves its state and still
writes `audit_report.json`. Getting that to happen from a parent process on
Windows takes a specific sequence, and every part of it is load-bearing:

1. the child is created with `CREATE_NEW_PROCESS_GROUP`, so it can be
   signalled without signalling everything else sharing the console;
2. Windows disables `CTRL_C_EVENT` for exactly those processes, so the signal
   sent is `CTRL_BREAK_EVENT`, which `batch.interrupt_on_break` has taught the
   child to receive as `KeyboardInterrupt`;
3. `GenerateConsoleCtrlEvent` only reaches processes sharing the caller's
   console, and a windowed application has none -- so the parent attaches to
   the child's console for the moment it takes to send.

If that does not stop it in time, the fallback is `terminate()`, which kills
the run where it stands and leaves no report. **When that happens it is said
out loud**, in the log pane and in the returned status: a run that was killed
without a report must never look like one that finished.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path

import fpx_converter

from .invoke import cli_command, is_frozen

#: Signal the child without touching anything else on the console.
CREATE_NEW_PROCESS_GROUP = 0x00000200
#: A console for the child, never shown. Without a console there is nothing
#: for `GenerateConsoleCtrlEvent` to deliver to; with a visible one, a black
#: window flashes up in front of the application.
CREATE_NO_WINDOW = 0x08000000
CTRL_BREAK_EVENT = 1
#: `AttachConsole` failing this way means "you already have one".
_ERROR_ACCESS_DENIED = 5

#: How the run ended. Returned by `cancel`, and the difference matters.
CANCELLED = "cancelled"
HARD_STOPPED = "hard-stopped"
NOT_RUNNING = "not-running"

#: Long enough for the engine to finish the file in flight, save its state and
#: write the report; short enough that a person who pressed Cancel believes it.
GRACE_SECONDS = 20.0


def _send_ctrl_break(pid: int) -> bool:
    """Ask the process group led by `pid` to stop. Windows only."""
    if not sys.platform.startswith("win"):  # pragma: no cover - project is Windows
        return False
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    attached = bool(kernel32.AttachConsole(pid))
    if not attached and kernel32.GetLastError() != _ERROR_ACCESS_DENIED:
        # No console of our own and none to borrow: nothing can be delivered.
        return False
    try:
        if attached:
            # Ignore the event ourselves while it is in flight. We are not in
            # the target group, but a handler installed by anything else in
            # this process would be, and being killed by our own Cancel button
            # would be a memorable bug.
            kernel32.SetConsoleCtrlHandler(None, True)
        return bool(kernel32.GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT, pid))
    finally:
        if attached:
            kernel32.FreeConsole()
            kernel32.SetConsoleCtrlHandler(None, False)


def child_environment(base: dict[str, str] | None = None) -> dict[str, str]:
    """The environment the child runs in.

    Unbuffered and UTF-8 so its output arrives line by line as it happens
    rather than in one lump at the end -- stdout to a pipe is block-buffered
    otherwise, which would make the progress bar a summary.

    `PYTHONPATH` carries the directory `fpx_converter` was imported from, so
    `python -m fpx_converter` finds the same copy this front end is running
    against whatever the working directory happens to be. The frozen exe
    never takes this branch: it has no `-m` to run and everything is inside
    it already.
    """
    env = dict(os.environ if base is None else base)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if not is_frozen():
        root = str(Path(fpx_converter.__file__).resolve().parent.parent)
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{root}{os.pathsep}{existing}" if existing else root
    return env


class CliProcess:
    """One `fpx_converter` invocation, its output delivered line by line.

    `on_line` is called from a reader thread, once per line, with the newline
    stripped. It is called for stderr too: the two streams are merged, because
    a person reading a log pane wants what happened in the order it happened.
    """

    def __init__(
        self,
        args: Sequence[str],
        *,
        on_line: Callable[[str], None],
        executable: str | None = None,
        frozen: bool | None = None,
    ) -> None:
        self.argv = cli_command(args, executable=executable, frozen=frozen)
        self._on_line = on_line
        self._process: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None
        self.cancel_status: str | None = None

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process else None

    @property
    def returncode(self) -> int | None:
        return self._process.returncode if self._process else None

    def start(self) -> None:
        creationflags = 0
        if sys.platform.startswith("win"):
            creationflags = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        self._process = subprocess.Popen(  # noqa: S603 - argv is built, never a shell string
            self.argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=child_environment(),
            creationflags=creationflags,
        )
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

    def _pump(self) -> None:
        assert self._process is not None
        stream = self._process.stdout
        if stream is None:  # pragma: no cover - stdout is always a pipe here
            return
        try:
            for raw in stream:
                self._on_line(raw.rstrip("\r\n"))
        except (OSError, ValueError):  # pragma: no cover - pipe torn down mid-read
            pass

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def wait(self, timeout: float | None = None) -> int:
        """Wait for the child and for every line of its output to be delivered."""
        if self._process is None:
            raise RuntimeError("start() was never called")
        code = self._process.wait(timeout=timeout)
        if self._reader is not None:
            self._reader.join(timeout=5.0)
        return code

    def cancel(self, grace: float = GRACE_SECONDS) -> str:
        """Stop the run, preferring the way that still writes a report.

        Returns `CANCELLED` when the child stopped on its own after the
        signal -- which is the case where `audit_report.json` exists and the
        state file is up to date -- and `HARD_STOPPED` when it had to be
        killed, which means neither is guaranteed. The caller is expected to
        say which one happened.
        """
        if self._process is None or self._process.poll() is not None:
            self.cancel_status = NOT_RUNNING
            return NOT_RUNNING

        if _send_ctrl_break(self._process.pid):
            deadline = time.monotonic() + grace
            while time.monotonic() < deadline:
                if self._process.poll() is not None:
                    self.cancel_status = CANCELLED
                    return CANCELLED
                time.sleep(0.1)

        self._process.terminate()
        try:
            self._process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:  # pragma: no cover - kill of last resort
            self._process.kill()
        self.cancel_status = HARD_STOPPED
        return HARD_STOPPED


def run_cli(
    args: Sequence[str],
    *,
    on_line: Callable[[str], None] | None = None,
    executable: str | None = None,
    frozen: bool | None = None,
) -> int:
    """Run one CLI command to completion. The blocking form of `CliProcess`."""
    sink = on_line if on_line is not None else (lambda _line: None)
    process = CliProcess(args, on_line=sink, executable=executable, frozen=frozen)
    process.start()
    return process.wait()
