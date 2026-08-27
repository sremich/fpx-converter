"""Tier-1: how the front end decides to invoke the CLI, both ways, unfrozen.

The frozen branch is the one that cannot be tried by hand without a
twenty-second PyInstaller build, which is exactly why the decision lives in
one function that takes the answer as an argument.
"""

from __future__ import annotations

import os
from pathlib import Path

from fpx_gui import invoke, runner


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


class TestHowTheChildIsCreated:
    """The flags decide whether Cancel can stop a run or only kill it."""

    def test_a_console_is_inherited_rather_than_replaced(self) -> None:
        """With a console, `CREATE_NO_WINDOW` is wrong and not merely useless.

        It gives the child a **new** console, which stops it sharing ours --
        and `GenerateConsoleCtrlEvent` can only reach a process through a
        shared console. That is measured behaviour: it turned Cancel from
        "stop and write the report" into "kill" until it was found.
        """
        flags = runner.creation_flags(console=True)
        assert flags & runner.CREATE_NEW_PROCESS_GROUP
        assert not flags & runner.CREATE_NO_WINDOW

    def test_without_a_console_the_child_is_given_a_hidden_one(self) -> None:
        flags = runner.creation_flags(console=False)
        assert flags & runner.CREATE_NEW_PROCESS_GROUP
        assert flags & runner.CREATE_NO_WINDOW

    def test_the_group_flag_is_never_dropped(self) -> None:
        """It is what makes one child signallable without signalling the rest."""
        for console in (True, False):
            assert runner.creation_flags(console=console) & runner.CREATE_NEW_PROCESS_GROUP

    def test_the_console_question_is_answered_by_process_list_not_by_window(self) -> None:
        """`GetConsoleWindow` returns 0 inside a pseudo-console.

        Windows Terminal and VS Code both host sessions that way, so the usual
        idiom reports "no console" while a real one is attached -- and the
        wrong branch is taken on the most ordinary developer machine there is.
        """
        source = Path(runner.__file__).read_text(encoding="utf-8")
        assert "GetConsoleProcessList" in source
        assert isinstance(runner.has_console(), bool)


class TestTheChildEnvironment:
    def test_the_child_is_unbuffered_so_progress_arrives_as_it_happens(self) -> None:
        env = runner.child_environment({})
        assert env["PYTHONUNBUFFERED"] == "1"
        assert env["PYTHONIOENCODING"] == "utf-8"

    def test_the_package_is_findable_whatever_the_working_directory(self) -> None:
        env = runner.child_environment({})
        assert (Path(env["PYTHONPATH"].split(os.pathsep)[0]) / "fpx_converter").is_dir()

    def test_an_existing_pythonpath_is_kept(self) -> None:
        env = runner.child_environment({"PYTHONPATH": "C:/somewhere/else"})
        assert env["PYTHONPATH"].endswith("C:/somewhere/else")


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
