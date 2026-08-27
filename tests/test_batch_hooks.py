"""Tier-1: the two hooks the batch engine grew so a front end can watch and stop it.

Both exist for the desktop application and neither is a GUI feature: one puts
the per-file trail somewhere a reader can see it, and the other is what makes
a cancelled run write its audit report instead of dying where it stands.
"""

from __future__ import annotations

import signal
import subprocess
import sys
from pathlib import Path

import pytest

from fpx_converter import batch


class TestTheLogCanBeEchoed:
    def test_a_line_reaches_both_the_file_and_the_echo(self, tmp_path: Path) -> None:
        seen: list[str] = []
        with batch.ConversionLog(tmp_path / "conversion.log", echo=seen.append) as log:
            log.write("OK   [1/2] example-0001.fpx -> 2 files in 0.4s")
        text = (tmp_path / "conversion.log").read_text(encoding="utf-8")
        assert "example-0001.fpx" in text
        assert seen == [text.rstrip("\n")]

    def test_the_echoed_line_is_the_logged_line(self, tmp_path: Path) -> None:
        """Same string, timestamp included.

        A reader parsing stdout and a person reading `conversion.log` must be
        looking at the same text, or the two disagree about what happened.
        """
        seen: list[str] = []
        with batch.ConversionLog(tmp_path / "c.log", echo=seen.append) as log:
            log.write("FAIL [2/2] example-0002.fpx: source file not found")
        assert (tmp_path / "c.log").read_text(encoding="utf-8").splitlines() == seen

    def test_without_an_echo_the_file_is_still_written(self, tmp_path: Path) -> None:
        with batch.ConversionLog(tmp_path / "c.log") as log:
            log.write("=== run start: 3 entries")
        assert "3 entries" in (tmp_path / "c.log").read_text(encoding="utf-8")


class TestCtrlBreakBecomesAnInterrupt:
    """The whole cancellation story rests on this.

    Windows disables `CTRL_C_EVENT` for a process created with
    `CREATE_NEW_PROCESS_GROUP`, which is the only way a parent can signal one
    child without signalling the console. `CTRL_BREAK_EVENT` is what is left,
    and by default it kills the process outright -- no state saved, no
    `audit_report.json`, which is the ending the batch engine exists to avoid.
    """

    def test_it_installs_a_handler_that_raises_keyboard_interrupt(self) -> None:
        sigbreak = getattr(signal, "SIGBREAK", None)
        if sigbreak is None:  # pragma: no cover - not Windows
            assert batch.interrupt_on_break() is False
            return
        previous = signal.getsignal(sigbreak)
        try:
            assert batch.interrupt_on_break() is True
            installed = signal.getsignal(sigbreak)
            assert callable(installed)
            try:
                installed(sigbreak, None)
            except KeyboardInterrupt:
                pass
            else:  # pragma: no cover - the point of the test
                raise AssertionError("the handler did not raise KeyboardInterrupt")
        finally:
            signal.signal(sigbreak, previous)

    def test_the_entry_point_installs_it(self) -> None:
        """Guarding the wiring, not just the function.

        `interrupt_on_break` being correct and never called is the same as not
        having it, and nothing else in a run would notice.

        Asked of a real child process rather than of the source text. The
        first version of this grepped `__main__.py` for the call, which would
        have passed just as well with the call commented out, unreachable, or
        inside an `if False:` -- and this project has already shipped one test
        that could not fail.
        """
        if not hasattr(signal, "SIGBREAK"):  # pragma: no cover - not Windows
            pytest.skip("SIGBREAK exists only on Windows")

        probe = "\n".join(
            [
                "import signal, sys, runpy",
                "sys.argv = ['fpx_converter', '--version']",
                "before = signal.getsignal(signal.SIGBREAK)",
                "try:",
                "    runpy.run_module('fpx_converter', run_name='__main__')",
                "except SystemExit:",
                "    pass",
                "after = signal.getsignal(signal.SIGBREAK)",
                "print('HANDLER-INSTALLED' if after is not before else 'HANDLER-ABSENT')",
            ]
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            cwd=Path(batch.__file__).parent.parent,
            timeout=120,
        )
        assert "HANDLER-INSTALLED" in result.stdout, (
            "the entry point did not install the Ctrl+Break handler; "
            f"stdout={result.stdout!r} stderr={result.stderr[-400:]!r}"
        )
