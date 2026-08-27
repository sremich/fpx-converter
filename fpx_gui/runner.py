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

import contextlib
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
#: A console for the child that is never shown. Used **only** when this
#: process has no console of its own -- see `creation_flags`.
CREATE_NO_WINDOW = 0x08000000
CTRL_BREAK_EVENT = 1
#: `AttachConsole` failing this way means "you already have one".
_ERROR_ACCESS_DENIED = 5


def has_console() -> bool:
    """Does this process have a console attached?

    True under a terminal, false for the packaged windowed exe. The answer
    decides how the child is created, and getting it wrong makes Cancel a
    kill -- see `creation_flags`.

    Asked with `GetConsoleProcessList` and **not** with `GetConsoleWindow`,
    which is the usual idiom and is wrong here. A modern terminal hosts its
    sessions on a pseudo-console, which has no window: `GetConsoleWindow`
    returns 0 inside Windows Terminal and VS Code while a perfectly real
    console is attached. Measured, not guessed -- that reading is what made a
    Cancel from a terminal fall through to killing the run.
    """
    if not sys.platform.startswith("win"):  # pragma: no cover - project is Windows
        return False
    buffer = (ctypes.c_uint * 1)()
    # Returns 0 with no console attached, and otherwise the number of
    # processes sharing it -- which may exceed the buffer, and still answers
    # the only question being asked.
    return ctypes.windll.kernel32.GetConsoleProcessList(buffer, 1) > 0  # type: ignore[attr-defined]


def creation_flags(console: bool | None = None) -> int:
    """How to create the child, which is not the same question in both cases.

    `CREATE_NEW_PROCESS_GROUP` is always wanted: it is what allows this one
    child to be signalled rather than everything sharing a console.

    `CREATE_NO_WINDOW` is wanted only when there is no console to inherit.
    It does not merely hide a window -- it gives the child a **new** console
    of its own. From a terminal that is actively wrong: the child stops
    sharing ours, `GenerateConsoleCtrlEvent` can no longer reach it, and
    Cancel degrades from "stop and write the report" to "kill". That is
    exactly what it did until this was measured.

    So: with a console, inherit it. Without one, make the child a hidden one
    so there is something for the signal to travel through at all, and reach
    it with `AttachConsole`.
    """
    if not sys.platform.startswith("win"):  # pragma: no cover - project is Windows
        return 0
    attached = has_console() if console is None else console
    return CREATE_NEW_PROCESS_GROUP if attached else (
        CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    )

#: How the run ended. Returned by `cancel`, and the difference matters.
CANCELLED = "cancelled"
HARD_STOPPED = "hard-stopped"
NOT_RUNNING = "not-running"

#: Long enough for the engine to finish the file in flight, save its state and
#: write the report; short enough that a person who pressed Cancel believes it.
GRACE_SECONDS = 20.0

#: How long `taskkill /F /T` is given to take down the process tree.
#: Named so the worker can add these up rather than guess at a total; a
#: guessed total was five seconds short, and the case it fell short on was
#: the hard kill it existed to report.
TREE_KILL_TIMEOUT = 15.0
#: The last-resort `terminate()` wait, after the tree kill did not work.
TERMINATE_TIMEOUT = 5.0


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


def _kill_tree(process: subprocess.Popen[str]) -> None:
    """Kill the child and anything it started. The last resort, and a whole tree.

    Killing only the process we launched is not enough once this is frozen. A
    PyInstaller one-file exe is a bootloader that unpacks itself and runs the
    real program as a *child*: `terminate()` on the one we hold would leave a
    conversion running with nothing watching it, still writing into the
    destination folder, invisible to the next run's resume check.

    `taskkill /T` takes the tree. `terminate()` is the fallback for a machine
    where it is unavailable -- better a possible orphan than a Cancel button
    that does nothing at all.
    """
    if sys.platform.startswith("win"):
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(  # noqa: S603, S607 - fixed argv, no shell
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                timeout=TREE_KILL_TIMEOUT,
                check=False,
                creationflags=CREATE_NO_WINDOW,
            )
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=TERMINATE_TIMEOUT)
        except subprocess.TimeoutExpired:  # pragma: no cover - kill of last resort
            process.kill()


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
            creationflags=creation_flags(),
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

    def cancel(self, grace: float = GRACE_SECONDS, stop_file: Path | None = None) -> str:
        """Stop the run, using every way that still leaves a report behind.

        **Two mechanisms, because one of them cannot be relied on.**
        `CTRL_BREAK_EVENT` is the better of the pair where it works: it lands
        at once, wherever the run has got to. But it can only travel through a
        console that this process and the child share, and a windowed
        application has none. Measured, on this project: from a console-less
        parent, `AttachConsole` against the child fails with
        `ERROR_INVALID_HANDLE` whether that child was created with
        `CREATE_NO_WINDOW` or with `CREATE_NEW_CONSOLE`. From a terminal the
        signal works and was watched working. From the packaged exe it may
        not -- and "may not" is not good enough for the guarantee that a
        cancelled run keeps its audit report.

        So the stop file goes down first. `convert --stop-file` looks for it
        between photos and stops on a boundary: no console, no signal, no
        privileges. It costs at most the photo in flight, and it always works.

        Returns `CANCELLED` when the child stopped by itself, which is the
        case where `audit_report.json` exists, and `HARD_STOPPED` when it had
        to be killed, which is the case where it does not. The caller is
        expected to say which one happened.
        """
        if self._process is None or self._process.poll() is not None:
            self.cancel_status = NOT_RUNNING
            return NOT_RUNNING

        if stop_file is not None:
            try:
                stop_file.parent.mkdir(parents=True, exist_ok=True)
                stop_file.write_text("stop\n", encoding="utf-8")
            except OSError:  # pragma: no cover - the signal is still to come
                pass

        _send_ctrl_break(self._process.pid)

        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                self.cancel_status = CANCELLED
                return CANCELLED
            time.sleep(0.1)

        _kill_tree(self._process)
        if stop_file is not None:
            # Not left behind to cancel the run somebody starts next.
            stop_file.unlink(missing_ok=True)
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
