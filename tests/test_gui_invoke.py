"""Tier-1: how the front end decides to invoke the CLI, both ways, unfrozen.

The frozen branch is the one that cannot be tried by hand without a
twenty-second PyInstaller build, which is exactly why the decision lives in
one function that takes the answer as an argument.
"""

from __future__ import annotations

from fpx_gui import invoke


class TestCliCommand:
    def test_an_interpreter_gets_dash_m(self) -> None:
        argv = invoke.cli_command(["convert", "--dry-run"], executable="py.exe", frozen=False)
        assert argv == ["py.exe", "-m", "fpx_converter", "convert", "--dry-run"]

    def test_a_frozen_exe_re_executes_itself_behind_the_sentinel(self) -> None:
        """There is no interpreter to hand and no `-m` to give it."""
        argv = invoke.cli_command(["convert"], executable="app.exe", frozen=True)
        assert argv == ["app.exe", invoke.CLI_SENTINEL, "convert"]

    def test_the_arguments_are_passed_through_untouched(self) -> None:
        args = ["convert", "--dest", "C:/out with space", "--archive-framing", "cropped"]
        for frozen in (True, False):
            argv = invoke.cli_command(args, executable="x", frozen=frozen)
            assert argv[-len(args):] == args

    def test_it_reads_the_real_process_when_not_told(self) -> None:
        argv = invoke.cli_command(["scan"])
        assert argv[0]
        assert argv[-1] == "scan"


class TestSentinel:
    def test_it_strips_the_sentinel_and_keeps_the_rest(self) -> None:
        assert invoke.take_sentinel([invoke.CLI_SENTINEL, "convert", "--limit", "3"]) == [
            "convert", "--limit", "3",
        ]

    def test_a_bare_sentinel_is_still_a_cli_run(self) -> None:
        """An empty list, not None: `[]` and `None` mean opposite things here."""
        assert invoke.take_sentinel([invoke.CLI_SENTINEL]) == []

    def test_no_sentinel_means_the_window(self) -> None:
        assert invoke.take_sentinel([]) is None
        assert invoke.take_sentinel(["convert"]) is None

    def test_the_sentinel_only_counts_first(self) -> None:
        """Otherwise a stray copy inside a real command line would hijack it."""
        assert invoke.take_sentinel(["convert", invoke.CLI_SENTINEL]) is None

    def test_the_sentinel_is_not_a_real_subcommand(self) -> None:
        from fpx_converter.cli import build_parser

        actions = [a for a in build_parser()._actions if a.choices]
        commands = {c for a in actions for c in a.choices}
        assert invoke.CLI_SENTINEL not in commands
        assert commands, "the parser exposed no subcommands; this check would pass vacuously"
