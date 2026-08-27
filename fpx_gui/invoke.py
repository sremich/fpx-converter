"""How this front end invokes the CLI. One decision, one function.

There are two shapes the answer takes and they are not interchangeable:

* **Running from a source tree or a venv**, `sys.executable` is a Python
  interpreter, so `python -m fpx_converter ...` is the whole story.
* **Running frozen** (the single-file PyInstaller exe), `sys.executable` is
  the exe itself. There is no interpreter to hand and no `-m` to give it, so
  the exe re-executes *itself* with `--run-cli` in front of the arguments.
  `fpx_gui.__main__` sees that sentinel first thing and dispatches straight
  into `fpx_converter.cli.main`, before Qt is imported at all.

Keeping both in one function is what makes the frozen path testable without
freezing anything: `cli_command(..., frozen=True)` answers the question the
bootloader would ask.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

#: First argument that turns a launch of this program into a CLI run.
#: Deliberately not a valid `fpx_converter` subcommand, so a stray copy of it
#: in a real command line cannot be mistaken for one.
CLI_SENTINEL = "--run-cli"


def is_frozen() -> bool:
    """Are we running as the packaged exe rather than under an interpreter?"""
    return bool(getattr(sys, "frozen", False))


def cli_command(
    args: Sequence[str],
    *,
    executable: str | None = None,
    frozen: bool | None = None,
) -> list[str]:
    """The full argv that runs `fpx_converter` with `args`.

    `executable` and `frozen` exist for the tests: they let both branches be
    exercised on an ordinary interpreter.
    """
    exe = executable if executable is not None else sys.executable
    packaged = is_frozen() if frozen is None else frozen
    if packaged:
        return [exe, CLI_SENTINEL, *args]
    return [exe, "-m", "fpx_converter", *args]


def take_sentinel(argv: Sequence[str]) -> list[str] | None:
    """The CLI arguments hiding behind the sentinel, or `None` if it is absent.

    Returns a list -- possibly empty -- when this launch is a CLI run, so an
    argument-less `--run-cli` is still recognised as one rather than reading
    as a request for the window.
    """
    if argv and argv[0] == CLI_SENTINEL:
        return list(argv[1:])
    return None
