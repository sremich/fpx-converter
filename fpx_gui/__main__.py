"""`python -m fpx_gui` — and, in the frozen exe, `fpx-converter.exe` itself.

Two jobs, and the order matters. The sentinel is checked **before Qt is
imported at all**: when the packaged exe re-executes itself to run a
conversion, that child is a command line tool and has no business starting a
GUI toolkit, allocating a window or touching a display.
"""

from __future__ import annotations

import sys

from .invoke import take_sentinel


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    cli_args = take_sentinel(args)
    if cli_args is not None:
        # Imported here, not at module level: this branch must stay free of Qt.
        from fpx_converter.batch import interrupt_on_break
        from fpx_converter.cli import main as cli_main

        # Ctrl+Break has to raise KeyboardInterrupt here, or the parent's
        # Cancel button kills this process outright and no audit report is
        # written. See `batch.interrupt_on_break` and `runner.CliProcess.cancel`.
        interrupt_on_break()
        return cli_main(cli_args)

    from .app import run

    return run(args)


if __name__ == "__main__":
    sys.exit(main())
